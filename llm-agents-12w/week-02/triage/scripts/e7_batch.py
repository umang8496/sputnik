"""Exercise 7: run the 5 incidents through the Message Batches API (50% price).
Run from triage/:
    python ../week-02/exercises/e7_batch.py submit            # prints the batch id
    python ../week-02/exercises/e7_batch.py collect <batch_id> # waits until ended, validates, logs
Cost: about half of 5 sync filtered calls (fractions of a cent on Haiku)."""
import json, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, "src")
from anthropic import transform_schema
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from triage.llm import client, cost_usd, text_of
from triage.schemas import IncidentSummary
from triage.summarize import check_citations
from triage.summarize_validated import render_incident
from triage.prompts import load_prompt

MODEL, MODE, VERSION = "claude-haiku-5-5", "filtered", "v1"
INCIDENTS = ["INC-001", "INC-002", "INC-003", "INC-004", "INC-005"]
SYSTEM, PV, SHA = load_prompt(f"summarize.{MODE}", VERSION)
SCHEMA = transform_schema(IncidentSummary)       # the JSON schema parse() would send for us

def cid(inc: str) -> str:
    """custom_id must match ^[a-zA-Z0-9_-]{1,64}$  ->  'INC-001__filtered-v1'"""
    return f"{inc}__{MODE}-{VERSION}"

def submit():
    reqs = [Request(
        custom_id=cid(inc),
        params=MessageCreateParamsNonStreaming(
            model=MODEL, max_tokens=16000, system=SYSTEM,
            # no cache_control: each incident block is unique, so a marker would only
            # pay the 1.25x write price on bytes no other request will read
            messages=[{"role": "user", "content":
                       render_incident(Path(f"data/incidents/{inc}"), MODE)
                       + "\n\nSummarize this incident."}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
        )) for inc in INCIDENTS]
    b = client.messages.batches.create(requests=reqs)
    Path("runs").mkdir(exist_ok=True)
    with Path("runs/batches.txt").open("a") as f:      # the id is the only handle you get
        f.write(f"{b.id}\t{datetime.now(timezone.utc).isoformat()}\t{PV}\n")
    print(json.dumps({"id": b.id, "processing_status": b.processing_status,
                      "request_counts": b.request_counts.model_dump()}, indent=2))

def collect(batch_id: str):
    t0 = time.perf_counter()
    while (b := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
        print(f"{time.perf_counter() - t0:6.0f}s  {b.processing_status}  {b.request_counts.model_dump()}")
        time.sleep(30)
    print(f"ended: {b.request_counts.model_dump()}  created={b.created_at}  ended={b.ended_at}\n")

    total = 0.0
    for res in client.messages.batches.results(batch_id):          # JSONL, any order
        inc = res.custom_id.split("__")[0]                          # route by custom_id
        folder = Path(f"data/incidents/{inc}")
        if res.result.type != "succeeded":
            err = getattr(res.result, "error", None)
            print(f"{inc}: {res.result.type} {err.error.type if err else ''}")
            continue
        msg = res.result.message                                    # a normal Message
        s = IncidentSummary.model_validate_json(text_of(msg))
        problems = check_citations(s, folder)
        truth = json.loads((folder / "truth.json").read_text())
        correct = s.error_signature.strip().lower() == truth["error_signature"].strip().lower()
        cost = cost_usd(MODEL, msg.usage) / 2                       # batch = 50% of every token
        total += cost
        with Path("runs.jsonl").open("a") as f:                     # same log as sync calls
            f.write(json.dumps({
                "run_id": uuid.uuid4().hex[:12], "tag": "w02.batch", "model": MODEL,
                "prompt_version": PV, "prompt_sha": SHA, "mode": MODE, "batch": True,
                "batch_id": batch_id, "incident": inc, "msg_id": msg.id,
                "stop_reason": msg.stop_reason, "input_tokens": msg.usage.input_tokens,
                "cache_write": msg.usage.cache_creation_input_tokens or 0,
                "cache_read": msg.usage.cache_read_input_tokens or 0,
                "output_tokens": msg.usage.output_tokens, "cost_usd": round(cost, 6),
                "ok": not problems, "correct": correct,
                "ts": datetime.now(timezone.utc).isoformat()}) + "\n")
        print(f"{inc}: sig={s.error_signature!r:<18} truth={truth['error_signature']!r:<18} "
              f"correct={correct!s:<5} citations={'OK' if not problems else len(problems)}  "
              f"in={msg.usage.input_tokens} out={msg.usage.output_tokens} ${cost:.6f}")
    print(f"\nbatch total: ${total:.6f}  (sync would be ~${total * 2:.6f})")

if __name__ == "__main__":
    if sys.argv[1:2] == ["submit"]:
        submit()
    elif sys.argv[1:2] == ["collect"] and len(sys.argv) == 3:
        collect(sys.argv[2])
    else:
        sys.exit(__doc__)
