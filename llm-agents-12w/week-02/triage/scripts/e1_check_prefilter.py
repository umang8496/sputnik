"""Exercise 1: inflate an incident to 50k lines and prove the prefilter keeps the cause.
Run from the triage project root: python scripts/e1_check_prefilter.py INC-001 INC-101
No API calls."""
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
from gen_incidents import Scenario, expand           # week 1 script
from triage.prefilter import prefilter               # this exercise

src, dst = sys.argv[1], sys.argv[2]                  # e.g. INC-001 INC-101
s = Scenario.model_validate_json(Path(f"data/scenarios/{src}.json").read_text())
s.incident_id = dst
out = Path(f"data/incidents/{dst}")
expand(s, out, seed=101, n_lines=50_000)             # same scenario, 50k lines

lines = (out / "app.log").read_text().splitlines()
truth = json.loads((out / "truth.json").read_text())
view = prefilter(lines)
kept = {int(row.split("\t")[0]) for row in view.splitlines()}

print(f"raw lines     : {len(lines):,}  chars: {sum(map(len, lines)):,}")
print(f"filtered rows : {len(view.splitlines())}  chars: {len(view):,}")
print(f"reduction     : {sum(map(len, lines)) / len(view):.0f}x")
print(f"trigger line {truth['trigger_line']} kept     : {truth['trigger_line'] in kept}")
print(f"first error {truth['first_error_line']} kept  : {truth['first_error_line'] in kept}")
print("--- filtered view ---")
print(view)
assert truth["trigger_line"] in kept, "prefilter dropped the root cause"
assert truth["first_error_line"] in kept, "prefilter dropped the first error"
