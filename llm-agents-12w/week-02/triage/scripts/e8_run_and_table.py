"""Exercise 8: measure raw vs filtered on the same incidents and print the week 2 table.
Run from triage/:
    python ../week-02/exercises/e8_run_and_table.py                 # raw + filtered (~$0.50-0.80)
    python ../week-02/exercises/e8_run_and_table.py --filtered-only # filtered only (~$0.01)
Each mode runs every incident twice back to back; run 2 should read the cache.
Prints a markdown table to paste into week-02/notes.md, and saves it to week-02/e8_table.md."""
import json, sys, statistics
from pathlib import Path
sys.path.insert(0, "src")
import pandas as pd
from triage.llm import LLMError
from triage.summarize import check_citations
from triage.summarize_validated import summarize_validated

INCIDENTS = ["INC-001", "INC-002", "INC-003", "INC-004", "INC-005"]
MODES = ["filtered"] if "--filtered-only" in sys.argv else ["filtered", "raw"]
RUNS = Path("runs.jsonl")

def new_rows(before: int) -> list[dict]:
    """Rows call() appended to runs.jsonl since line `before` (one per attempt)."""
    return [json.loads(l) for l in RUNS.read_text().splitlines()[before:]]

records = []
for mode in MODES:
    for run in (1, 2):                                  # run 2 within minutes -> cache reads
        for inc in INCIDENTS:
            folder = Path(f"data/incidents/{inc}")
            truth = json.loads((folder / "truth.json").read_text())
            before = len(RUNS.read_text().splitlines())
            try:
                s = summarize_validated(folder, mode, version="v1", tag=f"w02.e8.r{run}",
                                        log=lambda *_: None)
                correct = s.error_signature.strip().lower() == truth["error_signature"].strip().lower()
                cites_ok, sig = not check_citations(s, folder), s.error_signature
            except LLMError as e:                       # invalid after the one retry
                correct, cites_ok, sig = False, False, f"FAILED: {e}"[:40]
            rows = new_rows(before)
            a1 = rows[0]
            rec = {"mode": mode, "run": run, "incident": inc,
                   "prompt_version": a1.get("prompt_version"),
                   "prompt_tokens": a1["input_tokens"] + a1["cache_write"] + a1["cache_read"],
                   "cache_read": sum(r["cache_read"] for r in rows),
                   "cost": sum(r["cost_usd"] for r in rows),
                   "latency": sum(r["latency_s"] for r in rows),
                   "attempts": len(rows), "correct": correct, "citations_ok": cites_ok}
            records.append(rec)
            print(f"{mode:<8} r{run} {inc}: sig={sig!r:<22} truth={truth['error_signature']!r:<20} "
                  f"correct={correct!s:<5} attempts={len(rows)} tokens={rec['prompt_tokens']:>7,} "
                  f"read={rec['cache_read']:>7,} ${rec['cost']:.5f} {rec['latency']:.1f}s")

df = pd.DataFrame(records)
table = (df.groupby(["mode", "run", "prompt_version"])
           .agg(median_prompt_tokens=("prompt_tokens", "median"),
                cache_read_total=("cache_read", "sum"),
                cost_5_incidents=("cost", "sum"),
                median_latency_s=("latency", "median"),
                correct=("correct", "sum"),
                citations_ok=("citations_ok", "sum"),
                retries=("attempts", lambda a: int((a - 1).sum())))
           .reset_index())
table["correct"] = table.correct.astype(int).astype(str) + "/5"
table["citations_ok"] = table.citations_ok.astype(int).astype(str) + "/5"
table["cost_5_incidents"] = table.cost_5_incidents.map(lambda c: f"${c:.4f}")
table["median_prompt_tokens"] = table.median_prompt_tokens.map(lambda n: f"{int(n):,}")
table["cache_read_total"] = table.cache_read_total.map(lambda n: f"{int(n):,}")
table["median_latency_s"] = table.median_latency_s.map(lambda s: f"{s:.1f}")

# batch row from E7 (latest batch in runs.jsonl)
all_rows = pd.read_json(RUNS, lines=True)
batch = all_rows[all_rows.tag == "w02.batch"]
md = table.to_markdown(index=False)
if len(batch):
    last = batch[batch.batch_id == batch.batch_id.iloc[-1]]
    md += (f"\n\nBatch (E7, {last.prompt_version.iloc[0]}): {len(last)} incidents, "
           f"cost ${last.cost_usd.sum():.4f} (50% price), correct {int(last.correct.sum())}/{len(last)}")
print("\n" + md)
Path("../week-02/e8_table.md").write_text(md + "\n")
