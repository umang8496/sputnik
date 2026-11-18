"""Train MiniLLM v2. Written by v2_builder.ipynb (section 08).

Run from the v2/ folder in a terminal:   caffeinate -i nice -n 19 python v2_train.py
  caffeinate -i keeps the Mac awake; nice -n 19 gives the run the lowest CPU priority.
Ctrl+C stops it; the same command resumes from the last checkpoint.
Optional step count:  python v2_train.py 6000
(The step count also sets the cosine schedule, so resume with the same number.)"""
import math, pathlib, sys, time
import numpy as np, torch, torch.nn.functional as F

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
from v2_model import MiniLLM

# ── settings (cfg must match section 01 of the notebook) ─────────────────────
cfg = dict(vocab=2048, width=384, layers=6, heads=6, inner=1536, seq=512)
BATCH, WARMUP, PEAK_LR = 16, 300, 1e-3
STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
EVAL_EVERY, SAVE_EVERY = 250, 500
DATA, CKPT = HERE / "v2_data", HERE / "v2_ckpt.pt"

device = "mps" if torch.backends.mps.is_available() else "cpu"
if device == "mps":
    torch.mps.set_per_process_memory_fraction(0.5)       # leave GPU memory for other apps

# ── data: memory-mapped, read from disk on demand instead of loaded into RAM ─
train = np.memmap(DATA / "train.bin", dtype=np.uint16, mode="r")
val = np.memmap(DATA / "val.bin", dtype=np.uint16, mode="r")
SEQ = cfg["seq"]

def get_batch(split):
    src = train if split == "train" else val
    starts = np.random.randint(0, len(src) - SEQ - 1, BATCH)
    x = np.stack([src[s:s + SEQ] for s in starts]).astype(np.int64)
    y = np.stack([src[s + 1:s + SEQ + 1] for s in starts]).astype(np.int64)   # target = input shifted by 1
    return torch.from_numpy(x).to(device), torch.from_numpy(y).to(device)

# ── model + optimizer; resume from the checkpoint if one exists ──────────────
model = MiniLLM(**cfg).to(device)
opt = torch.optim.AdamW(model.parameters(), lr=PEAK_LR, weight_decay=0.1, betas=(0.9, 0.95))   # beta2 0.95: common for LLMs
step = 0
if CKPT.exists():
    ck = torch.load(CKPT, map_location=device)
    model.load_state_dict(ck["model"]); opt.load_state_dict(ck["opt"]); step = ck["step"]
    print(f"resumed from step {step}")

def lr_at(s):                                             # warm-up, then cosine decay to 10%
    if s < WARMUP: return PEAK_LR * (s + 1) / WARMUP
    p = min(1.0, (s - WARMUP) / max(1, STEPS - WARMUP))
    return PEAK_LR * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * p)))

@torch.no_grad()
def eval_loss(split, n=20):
    # average loss over n random batches, without updating the model
    model.eval()
    tot = sum(F.cross_entropy(model(x).view(-1, cfg["vocab"]), y.view(-1)).item()
              for x, y in (get_batch(split) for _ in range(n)))
    model.train()
    return tot / n

# ── logging: print and append to v2_train_log.txt ────────────────────────────
log = open(HERE / "v2_train_log.txt", "a")
def say(msg):
    print(msg, flush=True); log.write(msg + "\n"); log.flush()

tps = BATCH * SEQ                                         # tokens per step
say(f"params {sum(p.numel() for p in model.parameters()):,} | device {device} | train tokens {len(train):,} | "
    f"{STEPS:,} steps x {tps:,} = {STEPS*tps/1e6:.0f}M tokens = {STEPS*tps/len(train):.1f} passes")

# ── training loop ─────────────────────────────────────────────────────────────
t_last, s_last = time.time(), step
while True:
    if step % EVAL_EVERY == 0 or step == STEPS:          # progress report
        tr, va, now = eval_loss("train"), eval_loss("val"), time.time()
        tok_s = (step - s_last) * tps / (now - t_last) if step > s_last else 0
        eta = f"{(STEPS - step) * tps / tok_s / 60:.0f} min" if tok_s else "-"
        say(f"step {step:6} | lr {lr_at(step):.5f} | train {tr:.3f} | held-out {va:.3f} | {tok_s:,.0f} tok/s | ETA {eta}")
        t_last, s_last = time.time(), step
    if (step % SAVE_EVERY == 0 and step > 0) or step == STEPS:   # checkpoint (with optimizer state, for resuming)
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "cfg": cfg}, CKPT)
    if step >= STEPS:
        break
    for g in opt.param_groups:
        g["lr"] = lr_at(step)                             # apply the schedule
    x, y = get_batch("train")
    loss = F.cross_entropy(model(x).view(-1, cfg["vocab"]), y.view(-1))   # read + judge
    opt.zero_grad(set_to_none=True)
    loss.backward()                                                       # backprop
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)               # cap any wild step
    opt.step()                                                            # write
    step += 1
say(f"done, checkpoint at {CKPT}")
