"""summarize v2: cached incident block + one validation-retry.
Goes in triage/src/triage/summarize_validated.py (product code)."""
from pathlib import Path
from .llm import call, LLMError
from .schemas import IncidentSummary
from .summarize import check_citations
from .prompts import load_prompt
from .prefilter import prefilter

def render_incident(folder: Path, mode: str) -> str:
    """Stable incident block: identical bytes for every call on this incident + mode."""
    lines = (folder / "app.log").read_text().splitlines()
    logs = ("\n".join(f"{i}\t{l}" for i, l in enumerate(lines, 1)) if mode == "raw"
            else prefilter(lines))
    return (f'<incident id="{folder.name}">\n'
            f"<alert>{(folder / 'alert.txt').read_text().strip()}</alert>\n"
            f"<logs>\n{logs}\n</logs>\n"
            f"<metrics>\n{(folder / 'metrics.csv').read_text().strip()}\n</metrics>\n"
            "</incident>")

def build_messages(folder: Path, mode: str) -> list[dict]:
    return [{"role": "user", "content": [
        {"type": "text", "text": render_incident(folder, mode),
         "cache_control": {"type": "ephemeral"}},             # end of the stable part
        {"type": "text", "text": "Summarize this incident."},  # volatile tail
    ]}]

def summarize_validated(folder: Path, mode: str = "filtered", *, version: str = "v1",
                        inject_fault: bool = False, tag: str | None = None, log=print) -> IncidentSummary:
    """Call, verify citations against app.log, retry ONCE with the exact problems, then fail.

    inject_fault=True corrupts attempt 1's first citation (line number + 1) to simulate a
    model mistake, so the retry path can be exercised on demand."""
    system, pv, sha = load_prompt(f"summarize.{mode}", version)   # raw and filtered differ
    log(f"prompt {pv} sha={sha}")
    tag = tag or f"w02.{mode}"                                    # per-attempt suffix added below
    msgs = build_messages(folder, mode)
    for attempt in (1, 2):
        r = call(msgs, system=system, schema=IncidentSummary, tag=f"{tag}.a{attempt}",
                 prompt=(pv, sha), mode=mode)                    # both land in runs.jsonl
        s = r.parsed_output
        if inject_fault and attempt == 1:
            s = s.model_copy(deep=True)
            s.evidence[0].line += 1                           # now points at the wrong line
        problems = check_citations(s, folder)
        u = r.usage
        log(f"attempt {attempt}: cache_write={u.cache_creation_input_tokens or 0} "
            f"cache_read={u.cache_read_input_tokens or 0} input={u.input_tokens} "
            f"-> {'OK' if not problems else f'{len(problems)} problem(s)'}")
        for p in problems:
            log("   " + p.replace("\n", "\n   "))
        if not problems:
            return s
        msgs = msgs + [                                       # APPEND only: cached prefix stays valid
            {"role": "assistant", "content": s.model_dump_json()},   # the (faulty) answer as given
            {"role": "user", "content":
                "Validation failed:\n" + "\n".join(problems)
                + "\nReturn a corrected summary. Cite only lines that exist, with their exact text."},
        ]
    raise LLMError(f"{folder.name}: invalid after retry: {problems[:3]}")
