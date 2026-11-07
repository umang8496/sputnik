"""Exercise 5: exercise the validation-retry path.
Run from triage/:
    python ../week-02/exercises/e5_validation_retry.py INC-001          # normal: expect 1 attempt
    python ../week-02/exercises/e5_validation_retry.py INC-001 --fault  # injected bad citation: 2 attempts
Cost: 1-2 small Haiku calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from triage.llm import LLMError
from triage.summarize_validated import summarize_validated

inc = sys.argv[1] if len(sys.argv) > 1 else "INC-001"
fault = "--fault" in sys.argv
try:
    s = summarize_validated(Path(f"data/incidents/{inc}"), "filtered", inject_fault=fault)
except LLMError as e:
    print(f"FAILED: {e}")
    sys.exit(4)
print(f"\nfinal: signature={s.error_signature!r} component={s.suspected_component!r} "
      f"severity={s.severity} confidence={s.confidence}")
for ev in s.evidence:
    print(f"  line {ev.line}: {ev.text[:90]}")
