"""Print each scenario in a reviewable form and flag mechanical problems."""
import json
from collections import Counter
from pathlib import Path

paths = sorted(Path("data/scenarios").glob("INC-*.json"))
scen = [json.loads(p.read_text()) for p in paths]
sig_count = Counter(s["error_signature"] for s in scen)

for s in scen:
    t = json.loads(Path(f"data/incidents/{s['incident_id']}/truth.json").read_text())
    print(f"=== {s['incident_id']}  {s['service']}  {s['severity']}")
    print(f"alert      : {s['alert']}")
    print(f"root_cause : {s['root_cause']}")
    print(f"trigger    : line {t['trigger_line']}: [{s['trigger_event']['level']}] {s['trigger_event']['message']}")
    print(f"signature  : {s['error_signature']}")
    for e in s["error_lines"]:
        ok = s["error_signature"].lower() in e["message"].lower()
        print(f"  error  {'ok ' if ok else 'MISSING-SIG'} [{e['level']}] [{e['component']}] {e['message']}")
    for n in s["noise_lines"]:
        if n["level"] in ("WARN", "ERROR"):
            print(f"  herring     [{n['level']}] [{n['component']}] {n['message']}")
    print(f"metric     : {s['metric']} {s['metric_baseline']} -> {s['metric_peak']}")
    flags = []
    if s["trigger_event"]["level"] != "INFO": flags.append("trigger is not INFO")
    if not 3 <= len(s["error_lines"]) <= 6: flags.append(f"{len(s['error_lines'])} error templates (want 3-6)")
    if not 10 <= len(s["noise_lines"]) <= 20: flags.append(f"{len(s['noise_lines'])} noise templates (want 10-20)")
    if any(s["error_signature"].lower() in n["message"].lower() for n in s["noise_lines"]):
        flags.append("signature appears in a noise line")
    if sig_count[s["error_signature"]] > 1: flags.append("signature shared with another incident")
    print("FLAGS      :", "; ".join(flags) if flags else "none")
    print()
