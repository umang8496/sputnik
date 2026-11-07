import re
LINE = re.compile(r"^(\S+) (\w+)\s+\[([^\]]+)\] (.*)$")
VARS = [(re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27}\b"), "<uuid>"),
        (re.compile(r"\d+(\.\d+)?"), "<n>")]
def signature(level, comp, msg):
    for rx, rep in VARS: msg = rx.sub(rep, msg)
    return f"{level} [{comp}] {msg}"
def prefilter(lines, rare=3):
    groups = {}
    for i, line in enumerate(lines, start=1):
        m = LINE.match(line)
        if not m: continue
        ts, level, comp, msg = m.groups()
        g = groups.setdefault(signature(level, comp, msg), {"first": i, "text": line, "level": level, "n": 0})
        g["n"] += 1; g["last_ts"] = ts
    keep = sorted((g for g in groups.values() if g["level"] in ("WARN","ERROR") or g["n"] <= rare), key=lambda g: g["first"])
    return "\n".join(f'{g["first"]}\t{g["n"]}x\tlast={g["last_ts"]}\t{g["text"]}' for g in keep)
