#!/usr/bin/env python3
"""
serve.py - a tiny HTTP server for the v1 Mini LLM.

Loads `mini_llm_v1.pt` (built by v1_builder.ipynb) once at start-up and answers
HTTP POST requests by generating Python code. Standard library + PyTorch only.

Run
    python serve.py                         # http://127.0.0.1:8000
    python serve.py --port 9000 --device cpu

Endpoints
    GET  /               usage help (plain text)
    GET  /health         model + server info (JSON)
    POST /generate       generate a completion from a JSON body

/generate JSON body (every field is optional)
    prompt       string to continue. Empty / missing = "start a new file".
    max_new      tokens to generate               1 .. 1000  (default 150)
    temperature  0 = greedy, <1 = safer            0 .. 2     (default 0.8)
    top_k        sample from the k best, 0 = all   0 .. 512   (default 40)
    seed         integer for a repeatable sample   (default: random)
    format       "json" (default) or "text" for a plain-text reply

Examples
    curl -X POST http://127.0.0.1:8000/generate \\
         -H 'Content-Type: application/json' \\
         -d '{"prompt": "def read_config(path):", "max_new": 80, "seed": 1}'

    # multi-line prompt ("\\n" inside the JSON string), plain-text reply
    curl -X POST http://127.0.0.1:8000/generate \\
         -H 'Content-Type: application/json' \\
         -d '{"prompt": "class Stack:\\n    def push(self, item):", "seed": 1, "format": "text"}'

    # from Python
    import json, urllib.request
    req = urllib.request.Request("http://127.0.0.1:8000/generate",
                                 data=json.dumps({"prompt": "def f(x):"}).encode(),
                                 headers={"Content-Type": "application/json"})
    print(json.load(urllib.request.urlopen(req))["text"])

Tip: end the prompt at a non-space character (e.g. at the ':'), not after a
space or newline - see section 5 of v1_inference.ipynb for why.
"""
import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
MAX_PROMPT_CHARS = 4000
MAX_BODY_BYTES = 64 * 1024

# ═════════════════════════════════════════════════════════════════════════════
# Tokenizer
# The pre-split regex and EOF marker are NOT stored in the checkpoint; they must
# match v1_builder.ipynb exactly or the token IDs will not line up.
# ═════════════════════════════════════════════════════════════════════════════
SPLIT = re.compile(r" ?[A-Za-z_]+| ?\d+| ?[^\sA-Za-z_\d]+|\s+(?!\S)|\s+")
EOF_MARK = "<|eof|>"


class Tokenizer:
    """Byte-level BPE tokenizer rebuilt from the saved `merges` and `vocab`."""

    def __init__(self, merges, vocab):
        self.merges, self.vocab = merges, vocab
        self.rank = {pair: i for i, pair in enumerate(merges)}   # insertion order = learning order
        self.eof_id = len(vocab) - 1                             # last ID = end-of-file marker
        assert vocab[self.eof_id] == EOF_MARK.encode(), "checkpoint vocab does not end with <|eof|>"
        self._cache = {}

    def _encode_chunk(self, c):
        if c in self._cache:
            return self._cache[c]
        ids = list(c.encode("utf-8"))                            # start from raw bytes
        while len(ids) > 1:
            pair = min(zip(ids, ids[1:]), key=lambda p: self.rank.get(p, 1e9))  # earliest-learned pair
            if pair not in self.merges:
                break
            new, out, i = self.merges[pair], [], 0
            while i < len(ids):
                if i < len(ids) - 1 and (ids[i], ids[i + 1]) == pair:
                    out.append(new); i += 2
                else:
                    out.append(ids[i]); i += 1
            ids = out
        if len(self._cache) > 200_000:                           # keep memory bounded for a long-running server
            self._cache.clear()
        self._cache[c] = ids
        return ids

    def encode(self, s):
        return [i for c in SPLIT.findall(s) for i in self._encode_chunk(c)]

    def decode(self, ids):
        return b"".join(self.vocab[i] for i in ids).decode("utf-8", errors="replace")


# ═════════════════════════════════════════════════════════════════════════════
# Model - same architecture and parameter names as v1_builder.ipynb, so the
# saved state_dict loads strictly.
# ═════════════════════════════════════════════════════════════════════════════
def rope(t):
    """Rotary position embedding over (batch, head, position, field)."""
    T, D = t.shape[-2], t.shape[-1]
    half = D // 2
    freqs = 1.0 / (10000 ** (torch.arange(half, device=t.device) / half))
    ang = torch.arange(T, device=t.device)[:, None] * freqs[None, :]
    t1, t2 = t[..., :half], t[..., half:]
    return torch.cat([t1 * ang.cos() - t2 * ang.sin(), t1 * ang.sin() + t2 * ang.cos()], dim=-1)


class Block(nn.Module):
    """One transformer layer: attention (Mix) + feed-forward (Refine), pre-norm + residuals."""

    def __init__(self, W, H, I):
        super().__init__()
        self.W, self.H, self.D = W, H, W // H
        self.norm1, self.norm2 = nn.RMSNorm(W), nn.RMSNorm(W)
        self.Wq, self.Wk, self.Wv, self.Wo = [nn.Linear(W, W, bias=False) for _ in range(4)]
        self.Up, self.Down = nn.Linear(W, I, bias=False), nn.Linear(I, W, bias=False)

    def forward(self, g):
        B, T, _ = g.shape
        h = self.norm1(g)
        sp = lambda t: t.view(B, T, self.H, self.D).transpose(1, 2)
        q, k, v = sp(self.Wq(h)), sp(self.Wk(h)), sp(self.Wv(h))
        m = F.scaled_dot_product_attention(rope(q), rope(k), v, is_causal=True)
        g = g + self.Wo(m.transpose(1, 2).reshape(B, T, self.W))          # Mix + residual
        return g + self.Down(F.gelu(self.Up(self.norm2(g))))              # Refine + residual


class MiniLLM(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        V, W, L, H, I = cfg["vocab"], cfg["width"], cfg["layers"], cfg["heads"], cfg["inner"]
        self.emb = nn.Embedding(V, W)
        self.blocks = nn.ModuleList([Block(W, H, I) for _ in range(L)])
        self.norm = nn.RMSNorm(W)
        self.out = nn.Linear(W, V, bias=False)

    def forward(self, ids):
        g = self.emb(ids)
        for b in self.blocks:
            g = b(g)
        return self.out(self.norm(g))                                     # (batch, seq, vocab) logits


# ═════════════════════════════════════════════════════════════════════════════
# Service: owns the model and does the generation
# ═════════════════════════════════════════════════════════════════════════════
class BadRequest(ValueError):
    """A client error; carries the HTTP status to reply with (400 by default)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# name -> (type, min, max, default)
PARAMS = {
    "max_new":     (int,   1,   1000, 150),
    "temperature": (float, 0.0, 2.0,  0.8),
    "top_k":       (int,   0,   512,  40),
}


class LLMService:
    def __init__(self, ckpt_path, device):
        t0 = time.time()
        ckpt = torch.load(ckpt_path, map_location=device)
        self.cfg, self.device, self.ckpt_path = ckpt["cfg"], device, Path(ckpt_path)
        self.tok = Tokenizer(ckpt["merges"], ckpt["vocab"])
        self.model = MiniLLM(self.cfg).to(device)
        self.model.load_state_dict(ckpt["model"])                         # strict: names + shapes must match
        self.model.eval()
        self.seq = self.cfg["seq"]
        self.n_params = sum(p.numel() for p in self.model.parameters())
        self.lock = threading.Lock()          # one generation at a time (shared model + global RNG)
        self.load_s = time.time() - t0

    def info(self):
        return {
            "status": "ok",
            "checkpoint": self.ckpt_path.name,
            "device": self.device,
            "params": self.n_params,
            "context_tokens": self.seq,
            "cfg": self.cfg,
            "defaults": {k: v[3] for k, v in PARAMS.items()},
        }

    @staticmethod
    def parse(body):
        """Validate a decoded JSON body -> (prompt, settings dict, seed, format)."""
        if not isinstance(body, dict):
            raise BadRequest("request body must be a JSON object, e.g. {\"prompt\": \"def f(x):\"}")
        unknown = set(body) - {"prompt", "seed", "format", *PARAMS}
        if unknown:                                                        # catches typos like "max_tokens"
            raise BadRequest(f"unknown field(s): {', '.join(sorted(unknown))}; "
                             f"allowed: prompt, {', '.join(PARAMS)}, seed, format")

        prompt = body.get("prompt") or ""
        if not isinstance(prompt, str):
            raise BadRequest("prompt must be a string")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise BadRequest(f"prompt is longer than {MAX_PROMPT_CHARS} characters")

        settings = {}
        for name, (typ, lo, hi, default) in PARAMS.items():
            val = body.get(name)
            if val is None:
                settings[name] = default
                continue
            kind = "an integer" if typ is int else "a number"
            if isinstance(val, bool) or not isinstance(val, (int, float)):   # bool is an int subclass
                raise BadRequest(f"{name} must be {kind}, got {val!r}")
            if not lo <= val <= hi:                                          # also rejects NaN / Infinity
                raise BadRequest(f"{name} must be between {lo} and {hi}, got {val}")
            if typ is int and val != int(val):
                raise BadRequest(f"{name} must be {kind}, got {val!r}")
            settings[name] = typ(val)

        seed = body.get("seed")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63):
            raise BadRequest(f"seed must be an integer between 0 and 2**63-1, got {seed!r}")

        fmt = body.get("format", "json")
        if fmt not in ("json", "text"):
            raise BadRequest(f"format must be 'json' or 'text', got {fmt!r}")
        return prompt, settings, seed, fmt

    @torch.inference_mode()
    def generate(self, prompt, max_new, temperature, top_k, seed=None):
        tok, warnings = self.tok, []
        prompt_ids = tok.encode(prompt)
        if prompt and prompt[-1].isspace():
            warnings.append("prompt ends in whitespace; the model works best when the prompt ends at a "
                            "non-space character (e.g. at the ':'). See v1_inference.ipynb, section 5.")
        if len(prompt_ids) > self.seq:
            warnings.append(f"prompt is {len(prompt_ids)} tokens; only the last {self.seq} are visible to the model")
        # empty prompt -> start from <|eof|>, which in training always meant "a new file begins"
        start = prompt_ids or [tok.eof_id]

        with self.lock:
            if seed is not None:
                torch.manual_seed(seed)
            t0 = time.time()
            ids = torch.tensor([start], device=self.device)
            stopped = "max_new"
            for _ in range(max_new):
                logits = self.model(ids[:, -self.seq:])[:, -1, :]          # scores for the next token
                if temperature == 0:
                    nxt = logits.argmax(dim=-1, keepdim=True)              # greedy
                else:
                    logits = logits / temperature
                    if top_k:
                        kth = torch.topk(logits, top_k).values[:, [-1]]
                        logits[logits < kth] = -float("inf")               # keep the top-k
                    nxt = torch.multinomial(F.softmax(logits, dim=-1), 1)
                if nxt.item() == tok.eof_id:                               # model says "file over"
                    stopped = "eof"
                    break
                ids = torch.cat([ids, nxt], dim=1)
            elapsed = time.time() - t0

        new_ids = ids[0, len(start):].tolist()
        completion = tok.decode(new_ids)
        return {
            "prompt": prompt,
            "completion": completion,
            "text": prompt + completion,
            "tokens": {"prompt": len(prompt_ids), "generated": len(new_ids), "stopped": stopped},
            "settings": {"max_new": max_new, "temperature": temperature, "top_k": top_k, "seed": seed},
            "elapsed_ms": round(elapsed * 1000),
            "tokens_per_s": round(len(new_ids) / elapsed, 1) if elapsed > 0 else None,
            "warnings": warnings,
        }


# ═════════════════════════════════════════════════════════════════════════════
# HTTP layer
# ═════════════════════════════════════════════════════════════════════════════
class Handler(BaseHTTPRequestHandler):
    service: LLMService = None            # set in main()
    server_version = "MiniLLM/1"

    ROUTES = {"/": "GET", "/health": "GET", "/generate": "POST"}          # path -> allowed method

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._method_ok(path, "GET"):
            return
        if path == "/":
            self._send(200, __doc__, "text/plain")
        else:                                                              # /health
            self._send_json(200, self.service.info())

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._method_ok(path, "POST"):
            return
        try:                                                               # /generate
            prompt, settings, seed, fmt = LLMService.parse(self._read_json())
            result = self.service.generate(prompt, seed=seed, **settings)
            self._log_generation(result)
            if fmt == "text":
                self._send(200, result["text"], "text/plain")
            else:
                self._send_json(200, result)
        except BadRequest as e:
            self._send_json(e.status, {"error": str(e)})
        except Exception as e:                                             # never crash the server
            self.log_error("generation failed: %r", e)
            self._send_json(500, {"error": f"internal error: {type(e).__name__}"})

    # ── helpers ──
    def _method_ok(self, path, method):
        """404 for unknown paths, 405 (with an Allow header) for the wrong method."""
        allowed = self.ROUTES.get(path)
        if allowed is None:
            self._send_json(404, {"error": f"unknown path {path!r}; try GET /, GET /health or POST /generate"})
            return False
        if allowed != method:
            hint = " with a JSON body, e.g. {\"prompt\": \"def f(x):\"}" if allowed == "POST" else ""
            self._send_json(405, {"error": f"use {allowed} for {path}{hint}"}, {"Allow": allowed})
            return False
        return True

    def _read_json(self):
        """Read and decode the request body as JSON (an empty body counts as {})."""
        length = self.headers.get("Content-Length")
        if length is None:
            raise BadRequest("missing Content-Length header; send a JSON body", status=411)
        try:
            n = int(length)
        except ValueError:
            raise BadRequest("invalid Content-Length header")
        if n > MAX_BODY_BYTES:
            raise BadRequest(f"body is larger than {MAX_BODY_BYTES} bytes", status=413)
        raw = self.rfile.read(n) if n > 0 else b""
        if not raw.strip():
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise BadRequest(f"body is not valid JSON: {e}")

    def _send(self, status, body, ctype, headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status, obj, headers=None):
        self._send(status, json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "application/json", headers)

    def _log_generation(self, r):
        t = r["tokens"]
        print(f"  ↳ {t['prompt']} prompt + {t['generated']} new tokens ({t['stopped']}) "
              f"in {r['elapsed_ms']} ms, {r['tokens_per_s']} tok/s", flush=True)

    def log_message(self, fmt, *args):                                    # compact access log
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Serve the v1 Mini LLM over HTTP GET.")
    ap.add_argument("--host", default="127.0.0.1", help="interface to bind (default: localhost only)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--ckpt", default=str(HERE / "mini_llm_v1.pt"), help="checkpoint path")
    ap.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    args = ap.parse_args()

    device = args.device
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"

    Handler.service = svc = LLMService(args.ckpt, device)
    print(f"loaded {svc.ckpt_path.name}: {svc.n_params:,} params on {device} in {svc.load_s:.1f}s")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"serving on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    print(f"try:  curl -X POST http://{args.host}:{args.port}/generate -H 'Content-Type: application/json' "
          f"""-d '{{"prompt": "def read_config(path):", "seed": 1, "format": "text"}}'""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
