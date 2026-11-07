"""Exercise 6: versioned prompts, logged per run.
Run from triage/:  python ../week-02/exercises/e6_prompt_versions.py INC-001
Cost: 1-2 small Haiku calls."""
import json, sys
from pathlib import Path
sys.path.insert(0, "src")
from triage.summarize_validated import summarize_validated

inc = sys.argv[1] if len(sys.argv) > 1 else "INC-001"
truth = json.loads(Path(f"data/incidents/{inc}/truth.json").read_text())
s = summarize_validated(Path(f"data/incidents/{inc}"), "filtered", version="v1")
print(f"\nsignature: model={s.error_signature!r}  truth={truth['error_signature']!r}")

print("\nlast runs.jsonl rows:")
rows = [json.loads(l) for l in Path("runs.jsonl").read_text().splitlines()[-2:]]
for r in rows:
    print({k: r.get(k) for k in ("tag", "prompt_version", "prompt_sha", "mode",
                                 "cache_write", "cache_read", "input_tokens", "ok")})
