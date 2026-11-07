"""Exercise 2: measure prompt size for raw vs filtered with count_tokens (free endpoint).
Run from the triage project root: python scripts/e2_count_tokens.py"""
import sys
from pathlib import Path
import anthropic
sys.path.insert(0, "src")
from triage.llm import client                 # week 1 client (reads ANTHROPIC_API_KEY)
from triage.summarize import SYSTEM           # week 1 system prompt
from triage.prefilter import prefilter        # exercise 1

MODEL = "claude-haiku-5-5"
WINDOW = 1_000_000                            # context window, tokens
GATE = 150_000                                # our own budget for one call

def render(folder: Path, mode: str) -> str:
    """Same incident block the summarizer will send (alert + logs + metrics)."""
    lines = (folder / "app.log").read_text().splitlines()
    logs = ("\n".join(f"{i}\t{l}" for i, l in enumerate(lines, 1)) if mode == "raw"
            else prefilter(lines))
    return (f'<incident id="{folder.name}">\n'
            f"<alert>{(folder / 'alert.txt').read_text().strip()}</alert>\n"
            f"<logs>\n{logs}\n</logs>\n"
            f"<metrics>\n{(folder / 'metrics.csv').read_text().strip()}\n</metrics>\n"
            "</incident>\n\nSummarize this incident.")

if __name__ == "__main__":                     # only runs when executed, not when imported
    print(f"{'incident':<9} {'mode':<9} {'chars':>11} {'tokens':>11} {'chars/tok':>9}  verdict")
    for inc in ["INC-001", "INC-101"]:
        for mode in ["filtered", "raw"]:
            text = render(Path(f"data/incidents/{inc}"), mode)
            try:
                n = client.messages.count_tokens(          # no generation, no charge
                    model=MODEL, system=SYSTEM,
                    messages=[{"role": "user", "content": text}],
                ).input_tokens
            except anthropic.APIStatusError as e:          # e.g. 413 if the body is too large
                print(f"{inc:<9} {mode:<9} {len(text):>11,} {'-':>11} {'-':>9}  rejected: {e.status_code} {e.message[:60]}")
                continue
            verdict = ("does not fit window" if n > WINDOW else
                       "over our gate -> filter" if n > GATE else "ok to send")
            print(f"{inc:<9} {mode:<9} {len(text):>11,} {n:>11,} {len(text)/n:>9.1f}  {verdict}")
