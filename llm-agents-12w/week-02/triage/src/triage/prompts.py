"""Versioned prompt loader. Goes in triage/src/triage/prompts.py (product code).
Prompt files live in triage/prompts/<name>.<version>.md and are never edited after release."""
import hashlib
from pathlib import Path

PROMPTS = Path("prompts")                       # relative to triage/ (the working directory)

def load_prompt(name: str, version: str) -> tuple[str, str, str]:
    """Return (text, label, sha8) for prompts/<name>.<version>.md.

    label -> logged as prompt_version, e.g. "summarize.filtered.v1"
    sha8  -> logged as prompt_sha; same label with a different sha = a released file was edited"""
    text = (PROMPTS / f"{name}.{version}.md").read_text()
    sha8 = hashlib.sha256(text.encode()).hexdigest()[:8]
    return text, f"{name}.{version}", sha8
