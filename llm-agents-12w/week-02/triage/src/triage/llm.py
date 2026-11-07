import json, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()                                  # ANTHROPIC_API_KEY from .env
RUNS = Path("runs.jsonl")                      # one JSON line per call

client = anthropic.Anthropic(timeout=60.0, max_retries=4)  # shared client, 4 retries, 600 s timeout

# $/1M tokens: (input, output). Long-context tier applies when the whole prompt exceeds the threshold.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}
LONG_TIER = {"claude-haiku-5-5": (100_000, 0.50, 2.50)}   # (threshold, input, output)

class LLMError(RuntimeError):
    """Call returned but the result is unusable (truncated or refused)."""

# def cost_usd(model, u):
#     pin, pout = PRICES[model]
#     prompt = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
#     if model in LONG_TIER and prompt > LONG_TIER[model][0]:
#         _, pin, pout = LONG_TIER[model]
#     return (u.input_tokens * pin + (u.cache_creation_input_tokens or 0) * pin * 1.25
#             + (u.cache_read_input_tokens or 0) * pin * 0.10 + u.output_tokens * pout) / 1e6

def cost_usd(model, u):
    prompt = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
    pin, pout = PRICES[model]
    if model == "claude-haiku-5-5" and prompt > 100_000:     # Haiku 5.5 long-prompt tier
        pin, pout = 0.50, 2.50
    return (u.input_tokens * pin + (u.cache_creation_input_tokens or 0) * pin * 1.25
            + (u.cache_read_input_tokens or 0) * pin * 0.10 + u.output_tokens * pout) / 1e6

def _log(rec):
    with RUNS.open("a") as f:
        f.write(json.dumps(rec) + "\n")

def text_of(r):
    """Join text blocks only; never r.content[0].text."""
    return "".join(b.text for b in r.content if b.type == "text")

def call(messages, *, system=None, model="claude-haiku-5-5", effort="low",
         max_tokens=16000, tag="adhoc", schema=None, stream=False,
         prompt=None, mode=None):
    """prompt=(version, sha) and mode are optional metadata, logged to runs.jsonl only."""
    if isinstance(messages, str):              # plain string -> one user turn
        messages = [{"role": "user", "content": messages}]
    kw = dict(model=model, max_tokens=max_tokens, messages=messages,
              output_config={"effort": effort})
    if system:
        kw["system"] = system
    if schema is not None:
        kw["output_format"] = schema           # parse() / stream() turn the class into a schema
    rec = {"run_id": uuid.uuid4().hex[:12], "tag": tag, "model": model, "effort": effort,
           "schema": schema.__name__ if schema else None, "stream": stream,
           "prompt_version": prompt[0] if prompt else None,
           "prompt_sha": prompt[1] if prompt else None, "mode": mode,
           "ts": datetime.now(timezone.utc).isoformat()}
    t0 = time.perf_counter()
    ttft = None
    try:
        if stream:
            with client.messages.stream(**kw) as s:
                for chunk in s.text_stream:    # text deltas only; thinking is skipped
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    sys.stderr.write(chunk); sys.stderr.flush()   # live tokens -> stderr
                r = s.get_final_message()      # full Message, same as create()
            sys.stderr.write("\n")
        elif schema is not None:
            r = client.messages.parse(**kw)
        else:
            r = client.messages.create(**kw)
    except anthropic.APIError as e:            # log failures too, then re-raise
        rec |= {"ok": False, "error": type(e).__name__, "status": getattr(e, "status_code", None),
                "latency_s": round(time.perf_counter() - t0, 3)}
        _log(rec); raise
    u = r.usage
    rec |= {"ok": r.stop_reason in ("end_turn", "stop_sequence"), "msg_id": r.id,
            "request_id": getattr(r, "_request_id", None), "stop_reason": r.stop_reason,
            "input_tokens": u.input_tokens, "cache_write": u.cache_creation_input_tokens or 0,
            "cache_read": u.cache_read_input_tokens or 0, "output_tokens": u.output_tokens,
            "thinking_tokens": u.output_tokens_details.thinking_tokens if u.output_tokens_details else None,
            "cost_usd": round(cost_usd(model, u), 6), "latency_s": round(time.perf_counter() - t0, 3),
            "ttft_s": round(ttft, 3) if ttft else None}
    _log(rec)                                  # log before any check
    if r.stop_reason == "max_tokens":
        raise LLMError(f"truncated at max_tokens={max_tokens} ({rec['run_id']})")
    if r.stop_reason == "refusal":
        raise LLMError(f"refused: {r.stop_details} ({rec['run_id']})")
    return r
