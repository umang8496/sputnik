"""Exercise 3: prove prompt caching works by reading the usage counters.
Run from the triage project root: python scripts/e3_cache.py INC-001
Cost: 3 small Haiku calls on the filtered view (well under $0.01)."""
import sys, time
from pathlib import Path
sys.path.insert(0, "src")
sys.path.insert(0, str(Path(__file__).parent))   # sibling e2_count_tokens.py, wherever exercises live
from triage.llm import call                    # week 1 wrapper: logs to runs.jsonl
from triage.schemas import IncidentSummary
from triage.summarize import SYSTEM
from e2_count_tokens import render             # same incident block as E2

inc = sys.argv[1] if len(sys.argv) > 1 else "INC-001"
block = render(Path(f"data/incidents/{inc}"), "filtered").rsplit("\n\nSummarize", 1)[0]

def messages():
    return [{"role": "user", "content": [
        {"type": "text", "text": block,
         "cache_control": {"type": "ephemeral"}},          # cache everything up to here
        {"type": "text", "text": "Summarize this incident."}, # volatile tail
    ]}]

def show(label, r):
    u = r.usage
    total = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
    print(f"{label:<28} write={u.cache_creation_input_tokens or 0:>6}  "
          f"read={u.cache_read_input_tokens or 0:>6}  input={u.input_tokens:>5}  total={total:>6}")

r = call(messages(), system=SYSTEM, schema=IncidentSummary, tag="w02.e3.A")
show("A first call", r)

time.sleep(5)                                              # well inside the 5-minute TTL
r = call(messages(), system=SYSTEM, schema=IncidentSummary, tag="w02.e3.B")
show("B same request, +5s", r)

r = call(messages(), system="Note: " + SYSTEM, schema=IncidentSummary, tag="w02.e3.C")
show("C SYSTEM prefixed 'Note: '", r)                     # real content change at the very front
