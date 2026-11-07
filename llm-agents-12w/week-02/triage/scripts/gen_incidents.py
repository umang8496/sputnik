"""Generate 5 incidents: Haiku writes a small Scenario, Python writes the logs and the truth."""
import csv, json, random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from triage.llm import call                    # logged to runs.jsonl like every other call


# ---------- 1. what Haiku fills in (structured output) ----------
class LogTemplate(BaseModel):
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    component: str
    message: str = Field(description="One log message, may contain {n} for a random number")

class Scenario(BaseModel):
    incident_id: str
    service: str
    alert: str = Field(description="Pager alert text as the on-call engineer would see it")
    root_cause: str = Field(description="One sentence, unambiguous, names the change that caused it")
    suspected_component: str
    severity: Literal["sev1", "sev2", "sev3", "sev4"]
    trigger_event: LogTemplate = Field(description="The INFO line recording the bad change, e.g. a deploy or config push")
    error_signature: str = Field(description="Stable identifier of the main error, e.g. 'PoolTimeout'")
    error_lines: list[LogTemplate] = Field(description="3-6 templates for errors caused by the root cause; each contains error_signature")
    noise_lines: list[LogTemplate] = Field(description="10-20 normal or unrelated lines, including 2 red-herring WARNs")
    metric: str = Field(description="Metric that degrades, e.g. p99_latency_ms")
    metric_baseline: float
    metric_peak: float

PROMPT = """Design a realistic production incident for a training dataset.
Service: {service}. Failure mode: {failure}.
The root cause must be a single, specific change visible in the logs as one INFO line.
Error templates must contain the error_signature text. Red herrings must be plausible but unrelated."""

CASES = [
    ("checkout", "DB connection pool shrunk by a config change"),
    ("search", "cache TTL set to 0 causing cache stampede on the DB"),
    ("payments", "TLS certificate for an upstream provider expired"),
    ("auth", "memory leak introduced in a new release, pods OOMKilled"),
    ("notifications", "rate limit to an email provider lowered, 429s pile up"),
]


# ---------- 2. what code does (deterministic expansion + ground truth) ----------
def expand(s: Scenario, out: Path, seed: int, n_lines: int = 3000) -> None:
    rnd = random.Random(seed)                  # same seed -> identical files on re-run
    t0 = datetime(2026, 11, 1, 10, 0, 0)
    trigger_at = rnd.randint(n_lines // 3, n_lines // 2)   # 0-based index of the bad change
    lines, first_error = [], None
    for i in range(n_lines):
        ts = t0 + timedelta(milliseconds=400 * i)
        if i == trigger_at:
            tpl = s.trigger_event
        elif i > trigger_at + 5 and rnd.random() < 0.15:   # errors start shortly after the change
            tpl = rnd.choice(s.error_lines)
        else:
            tpl = rnd.choice(s.noise_lines)
        msg = tpl.message.replace("{n}", str(rnd.randint(1, 999)))
        lines.append(f"{ts:%Y-%m-%dT%H:%M:%S.%f}"[:-3] + f" {tpl.level:<5} [{tpl.component}] {msg}")
        if first_error is None and tpl in s.error_lines:
            first_error = (i + 1, ts)          # 1-based line number
    assert first_error, "no error line was generated; check error_lines"

    out.mkdir(parents=True, exist_ok=True)
    (out / "app.log").write_text("\n".join(lines) + "\n")
    (out / "alert.txt").write_text(s.alert + "\n")
    with (out / "metrics.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", s.metric])
        trigger_ts = t0 + timedelta(milliseconds=400 * trigger_at)
        for m in range(0, n_lines * 400 // 60000 + 1):     # one point per minute
            ts = t0 + timedelta(minutes=m)
            base = s.metric_peak if ts >= trigger_ts else s.metric_baseline
            w.writerow([ts.isoformat(), round(base * rnd.uniform(0.9, 1.1), 1)])
    truth = {                                  # computed from what was written, never by the model
        "incident_id": s.incident_id, "service": s.service, "root_cause": s.root_cause,
        "suspected_component": s.suspected_component, "severity": s.severity,
        "error_signature": s.error_signature,
        "trigger_line": trigger_at + 1, "trigger_text": lines[trigger_at],
        "first_error_line": first_error[0], "first_error_ts": first_error[1].isoformat(),
    }
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n")


def generate(i: int, service: str, failure: str) -> Scenario:
    r = call(PROMPT.format(service=service, failure=failure),
             schema=Scenario, effort="low", max_tokens=8000, tag=f"gen:{service}")
    s: Scenario = r.parsed_output
    s.incident_id = f"INC-{i:03d}"             # ids are ours, not the model's
    return s


if __name__ == "__main__":
    import sys
    only_expand = "--expand-only" in sys.argv  # re-expand hand-fixed scenarios, no model calls
    sc_dir = Path("data/scenarios"); sc_dir.mkdir(parents=True, exist_ok=True)
    for i, (service, failure) in enumerate(CASES, start=1):
        path = sc_dir / f"INC-{i:03d}.json"
        if only_expand:
            s = Scenario.model_validate_json(path.read_text())
        else:
            s = generate(i, service, failure)
            path.write_text(s.model_dump_json(indent=2))
        expand(s, Path(f"data/incidents/{s.incident_id}"), seed=i)
        t = json.loads(Path(f"data/incidents/{s.incident_id}/truth.json").read_text())
        print(f"{s.incident_id} {service:<14} trigger@{t['trigger_line']:<5} "
              f"first_error@{t['first_error_line']:<5} sig={s.error_signature}")

###
