<!-- markdownlint-disable MD001 -->
<!-- markdownlint-disable MD024 -->
<!-- markdownlint-disable MD025 -->
<!-- markdownlint-disable MD026 -->
<!-- markdownlint-disable MD029 -->
<!-- markdownlint-disable MD033 -->
<!-- markdownlint-disable MD036 -->
<!-- markdownlint-disable MD040 -->
<!-- markdownlint-disable MD056 -->
<!-- markdownlint-disable MD060 -->

# Week 2 — Cost, Caching, Long Inputs, Failure Handling

---

## Table of contents

00. [Overview](#0-overview)
01. [Long inputs](#1-long-inputs)
02. [Prompt caching](#2-prompt-caching)
03. [Failure handling](#3-failure-handling)
04. [Prompts as versioned files](#4-prompts-as-versioned-files)
05. [Batches API](#5-batches-api)
06. [Measurement and deliverable](#6-measurement-and-deliverable)
07. [Code changes summary](#7-code-changes-summary)
08. [Glossary](#8-glossary)
09. [Links to the rest of the plan](#9-links-to-the-rest-of-the-plan)
10. [Q&A from the sessions](#10-qa-from-the-sessions)

---

## 0. Overview

### 0.1 Goal of the week

Week 1 made one model call work: send logs, get a validated `IncidentSummary`. Week 2 makes that call **production-shaped**.  
The model is treated as a dependency with four properties that every LLM system has to engineer around:

| Property of the LLM                  | Problem it causes                            | Week 2 answer                                               |
|--------------------------------------|----------------------------------------------|-------------------------------------------------------------|
| Bounded: finite context window       | Large inputs do not fit, or bury the signal  | Section 1: count tokens, pre-filter in code, map-reduce     |
| Metered: every token is billed       | Repeated input wastes money                  | Section 2: prompt cache, response cache. Section 5: Batches |
| Unreliable: rate limits, bad outputs | Crashes, silent wrong answers                | Section 3: retries, timeouts, validation-retry              |
| Changeable: output depends on prompt | Silent regressions when the prompt is edited | Section 4: versioned prompts, version logged per run        |

Section 6 measures all of it (tokens, cost, latency, accuracy) so every design choice is backed by a number, not a belief.

Week 2 is about **leveraging the LLM effectively**. Serving many clients (API service, webhooks, queues, concurrency limits) is weeks 11-12; those weeks reuse every idea here at a larger scale.

### 0.2 What `triage summarize` v2 adds over v1

| Capability          | v1 (week 1)          | v2 (week 2)                                                       |
|---------------------|----------------------|-------------------------------------------------------------------|
| Input size          | Whole log, ~3k lines | `--mode raw\|filtered`, token gate, works on 50k-line logs        |
| Cost control        | Logged only          | Prompt caching on the incident block, batch mode at 50% price     |
| API failures        | Stack trace          | Configured SDK retries, timeouts, clean exit codes                |
| Bad output          | Reported             | One corrective validation-retry, then a loud failure              |
| Prompt              | Python string        | `prompts/summarize.<mode>.vN.md`, version + hash in every log row |
| Evidence of quality | Manual               | Table in `notes/w02.md`: tokens, cost, latency, correctness       |

### 0.3 Prerequisites from week 1

| Week 1 artifact     | Used in week 2 for                                             |
|---------------------|----------------------------------------------------------------|
| `call()` wrapper    | Every call; gains `prompt=` and `batch=` fields in its log row |
| `runs.jsonl`        | Source of every number in the week 2 table                     |
| `IncidentSummary`   | Output schema for sync and batch runs                          |
| `check_citations()` | Drives the validation-retry and the "citations OK" column      |
| `gen_incidents.py`  | `expand()` reused to inflate incidents to 50k lines            |
| `truth.json`        | Ground truth for the "correct signature" column                |

### 0.4 API note carried over from week 1

Week 1 code passed `output_format=IncidentSummary` to `parse()`/`stream()`.  
On `messages.create()` the current parameter for structured output is `output_config={"format": {"type": "json_schema", "schema": ...}}`;  
`client.messages.parse()` remains the recommended helper for synchronous calls because it validates into the Pydantic model.  
The Batches API (Section 5) has no `parse()` helper, so the raw `output_config.format` form is used there.

---

## 1. Long inputs

### 1.1 The problem: three limits, in order of how they bite

An incident hands you far more log text than the model can usefully read.

| Limit          | Kind   | What happens                                                                                                                  |
|----------------|--------|-------------------------------------------------------------------------------------------------------------------------------|
| Context window | Hard   | Haiku 5.5 takes at most 1M tokens. A larger request is rejected.                                                              |
| Cost           | Soft   | Every input token is billed on every call. Haiku 5.5 is $0.10/M up to 100k prompt tokens, $0.50/M above.                      |
| Quality        | Silent | The cause is one line in 50,000. More noise means a higher chance of missing it or citing the wrong line. No error is raised. |

Worked numbers (estimate ~30 tokens per log line; measure your own with `count_tokens`):

| Log size     | Approx. tokens | Fits 1M window? | Haiku 5.5 input cost per call |
|--------------|----------------|-----------------|-------------------------------|
| 3,000 lines  | ~90,000        | Yes             | ~$0.009                       |
| 25,000 lines | ~750,000       | Yes             | ~$0.375 (above-100k rate)     |
| 50,000 lines | ~1,500,000     | No (rejected)   | n/a                           |

Raw stuffing fails before it even gets expensive.

### 1.2 Measure first: `count_tokens`

`POST /v1/messages/count_tokens` takes the same body as a Messages request and returns how many input tokens it would use.  
It is free and has its own rate limit. Put it in front of every call so the strategy is chosen from a measured number.

```python
import anthropic

client = anthropic.Anthropic()

def prompt_tokens(model: str, system: str, messages: list) -> int:
    """Exact input-token count for this request, without running the model."""
    r = client.messages.count_tokens(
        model=model,          # counts differ per tokenizer, so pass the real model
        system=system,        # system prompt counts toward input
        messages=messages,    # same messages you are about to send
    )
    return r.input_tokens

n = prompt_tokens("claude-haiku-5-5", SYSTEM, messages)
if n > 150_000:               # your budget, not the model's limit
    mode = "filtered"         # or: map-reduce, or refuse with a clear message
```

Use the tokenizer of the model you will call.  
Never estimate with a different vendor's tokenizer.

### 1.3 Three strategies

| Strategy           | What the model sees                        | Cost      | Use when                                 |
|--------------------|--------------------------------------------|-----------|------------------------------------------|
| Raw stuffing       | Every line                                 | Highest   | Small inputs (under ~50k tokens)         |
| Pre-filter in code | A condensed, deterministic view            | Lowest    | Default for structured data such as logs |
| Map-reduce         | Per-chunk extractions, then one merge call | N+1 calls | Still too big after filtering            |

Governing rule: **code does whatever it can do exactly** (filter by level, dedupe, count, sort, take time windows).  
The model gets only the part that needs judgment: which event caused which symptom.

### 1.4 Signature collapse (the filter)

Most log lines are a template repeated with different variables:

```text
2026-11-01T10:12:03.400 ERROR [db-pool] PoolTimeout after 302ms waiting for connection
2026-11-01T10:12:07.200 ERROR [db-pool] PoolTimeout after 977ms waiting for connection
```

Replace the variable parts (numbers, UUIDs) with placeholders and both become one **signature**:

```text
ERROR [db-pool] PoolTimeout after <n>ms waiting for connection
```

Group by signature and keep: count, first line number, first line text verbatim, last timestamp.  
Thousands of lines become roughly 25 groups.

**The trap in this dataset.**  
The plan says "keep ERROR/WARN". In `gen_incidents.py`, the root cause is `trigger_event`: a single **INFO** line (a deploy or config change).  
A level filter deletes the answer. The fix: keep every WARN/ERROR signature **plus every rare signature** (count ≤ 3) at any level. A change that happens once is rare, so it survives.

```python
# src/triage/prefilter.py
import re

# Log format produced by gen_incidents.expand():
# "2026-11-01T10:00:00.400 INFO  [component] message"
LINE = re.compile(r"^(\S+) (\w+)\s+\[([^\]]+)\] (.*)$")

# Variable parts replaced by placeholders, most specific first
VARS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27}\b"), "<uuid>"),   # request ids
    (re.compile(r"\b\d+(\.\d+)?\b"), "<n>"),                   # numbers, durations, counts
]

def signature(level: str, comp: str, msg: str) -> str:
    """Stable identity of a log template: same event, different numbers -> same string."""
    for rx, rep in VARS:
        msg = rx.sub(rep, msg)
    return f"{level} [{comp}] {msg}"

def prefilter(lines: list[str], rare: int = 3) -> str:
    """Collapse lines to signatures; keep WARN/ERROR and rare signatures.

    Output: one row per kept signature, tab-separated:
        <first line no>\t<count>x\tlast=<last ts>\t<first line text verbatim>
    The first field and the last field are what check_citations() verifies.
    """
    groups: dict[str, dict] = {}
    for i, line in enumerate(lines, start=1):          # 1-based, like the citations
        m = LINE.match(line)
        if not m:
            continue                                  # stack-trace continuation etc.
        ts, level, comp, msg = m.groups()
        g = groups.setdefault(
            signature(level, comp, msg),
            {"first": i, "text": line, "level": level, "n": 0},
        )
        g["n"] += 1
        g["last_ts"] = ts
    keep = sorted(
        (g for g in groups.values() if g["level"] in ("WARN", "ERROR") or g["n"] <= rare),
        key=lambda g: g["first"],                     # chronological order
    )
    return "\n".join(
        f'{g["first"]}\t{g["n"]}x\tlast={g["last_ts"]}\t{g["text"]}' for g in keep
    )
```

Result: about 25 rows, ~1-2k tokens, down from ~1.5M.

### 1.5 Keeping evidence traceable

Each kept row carries its **original line number** and its **first line verbatim**.  
The model cites those, and `check_citations()` verifies them against the real `app.log`, not against the filtered view.  
The SYSTEM prompt for filtered mode must say that the cited text is the **last tab-separated field** (raw mode keeps the week-1 wording).  
That difference is why raw and filtered get separate prompt versions (Section 4.7).

### 1.6 Map-reduce

Used only when the filtered view is still too large.

```text
chunks = split(filtered_or_raw, size=~50k tokens)
notes  = [haiku_extract(chunk) for chunk in chunks]      # map: structured candidates per chunk
answer = summarize(notes)                                # reduce: one call over all extractions
```

| Cost of map-reduce        | Why                                                                               |
|---------------------------|-----------------------------------------------------------------------------------|
| N+1 calls                 | One per chunk plus the reduce call                                                |
| Lost cross-chunk evidence | A cause in chunk 2 and its symptom in chunk 5 are never seen together by one call |
| More prompts to maintain  | `map_extract` and `reduce` are separate versioned prompts                         |

It is the last resort after filtering.

### 1.7 Inflating incidents (no API cost)

```python
import json
from pathlib import Path
from gen_incidents import Scenario, expand   # week 1 script

for src, dst, seed in [("INC-001", "INC-101", 101), ("INC-003", "INC-103", 103)]:
    s = Scenario.model_validate_json(Path(f"data/scenarios/{src}.json").read_text())
    s.incident_id = dst
    expand(s, Path(f"data/incidents/{dst}"), seed=seed, n_lines=50_000)  # same scenario, bigger log
```

### 1.8 The general pattern (beyond logs)

The specific filter depends on the domain. These four steps carry over to any problem:

1. **Measure**: count tokens before sending; the budget decides the strategy.
2. **Reduce with code what code can reduce exactly**: dedupe, aggregate, window, rank, retrieve.
3. **Keep a pointer back to the source**: line numbers, doc ids, offsets, so every claim can be verified.
4. **Escalate only when needed**: raw → filtered → map-reduce → agentic retrieval.

| Input type      | Typical reduction                               |
|-----------------|-------------------------------------------------|
| Logs            | Signature collapse, plus rare events            |
| Contracts       | Section split, plus clause retrieval            |
| Codebase        | grep / AST, plus only the touched files         |
| Support tickets | Dedupe, plus cluster by intent                  |
| Metrics         | Change-point detection; send only the anomalies |

Failure check for any reducer: **can it delete the answer?**  
Test that with ground truth, as `truth.json` does here. In week 6 (RAG) the same question becomes retrieval recall.

---

## 2. Prompt caching

### 2.1 Why it is needed

The Messages API is **stateless**. Every request carries the entire prompt, and the model reads all of it from token 1, every time.

Concrete case: INC-001 raw is ~90k tokens. In week 3 the agent calls the model ~10 times on the same incident. Each call resends those 90k tokens plus the growing history. The model re-reads the identical 90k ten times: ~900k input tokens billed and ten long waits before the first output token, all to redo work it already did.

### 2.2 What "reading the prompt" costs: prefill and the KV cache

Before writing a single output token, the model runs every input token through all its layers. For each token, each layer produces two internal vectors, a **key** and a **value**, that later tokens attend to. This phase is **prefill**. It is the cost behind input-token pricing and the delay before the first output token (time to first token). The result is the **KV cache**: the model's processed memory of the prompt.

Key property: token 500's vectors depend only on tokens 1-500, never on what comes after. So if two prompts share their first 90k tokens exactly, the processed state for those 90k tokens is identical and can be reused. That is why caching works on **prefixes**, and only on prefixes.

### 2.3 What prompt caching is, and who does what

Prompt caching: Anthropic's servers keep the processed state of a prompt prefix for a short time. When the next request starts with the same bytes, they load it instead of recomputing it, and prefill runs only on the new part at the end. The output is unchanged; only cost and latency change.

| Actor               | Responsibility                                                                                                      |
|---------------------|---------------------------------------------------------------------------------------------------------------------|
| Anthropic's servers | Fingerprinting, storing, lookup, expiry, billing. The model itself never knows.                                     |
| You (the client)    | Mark where the reusable part ends (`cache_control`); keep that part byte-identical; order the prompt; verify usage. |
| The SDK             | Nothing special. It sends your marker inside the JSON body unchanged.                                               |

Caching is **opt-in** on the Claude API. Without a marker nothing is stored. Products such as Claude Code do this internally; the raw API leaves it to you.

### 2.4 How the client asks for caching: wire format

There is no separate cache endpoint and no special header. One field on a content block: `"cache_control": {"type": "ephemeral"}`. It means "everything up to and including this block is worth storing".

**Python**

```python
r = client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=16000,
    system=SYSTEM,                                   # ~150 tokens: too small to cache alone
    messages=[{
        "role": "user",
        "content": [                                 # a LIST of blocks, so a block can carry the marker
            {
                "type": "text",
                "text": incident_text,               # alert + logs + metrics, ~90k tokens
                "cache_control": {"type": "ephemeral"},   # cache everything up to here
            },
            {
                "type": "text",
                "text": "Summarize this incident.",  # after the marker: volatile, not cached
            },
        ],
    }],
)
```

A plain string `content` cannot carry a marker; the block list is required.

**What the SDK sends over the wire**

```http
POST https://api.anthropic.com/v1/messages
x-api-key: sk-ant-...
anthropic-version: <set by the SDK>
content-type: application/json

{
  "model": "claude-haiku-5-5",
  "max_tokens": 16000,
  "system": "You are an SRE triaging...",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "<incident id=\"INC-001\">...",
       "cache_control": {"type": "ephemeral"}},
      {"type": "text", "text": "Summarize this incident."}
    ]
  }]
}
```

**What comes back (the only proof)**

```json
// Call 1: miss, stored
"usage": {"input_tokens": 12, "cache_creation_input_tokens": 90150,
          "cache_read_input_tokens": 0, "output_tokens": 640}

// Call 2 within 5 minutes: hit
"usage": {"input_tokens": 12, "cache_creation_input_tokens": 0,
          "cache_read_input_tokens": 90150, "output_tokens": 655}
```

**Variations of the same field**

```python
# 1-hour TTL instead of the default 5 minutes
{"type": "text", "text": incident_text, "cache_control": {"type": "ephemeral", "ttl": "1h"}}

# Marker on the system prompt: system becomes a list of blocks
system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]

# Automatic placement: top-level field, the server marks the LAST cacheable block itself.
# Good for chats; wrong for triage, because our last block is the volatile instruction.
client.messages.create(..., cache_control={"type": "ephemeral"})
```

Up to **4 markers per request**, on tool definitions, system blocks, or message blocks.

### 2.5 What the server does when it sees the marker

Documented behavior. The exact storage internals (hash function, where state lives on hardware) are not published; treat that layer as conceptual.

1. **Render** the prompt in fixed order: `tools` → `system` → `messages`. One long token sequence.
2. **Locate** the marker: the last token of the marked block (~90,150 tokens in).
3. **Fingerprint** the prefix: an identity for "exactly these tokens, positions 1 to 90,150, on this model, in this workspace". One different byte gives a different identity.
4. **Look up** the identity.
   - Hit: load the stored processed state; skip prefill for those tokens.
   - Miss: walk **backward up to 20 content blocks** looking for a shorter prefix stored earlier at a position where an earlier request placed a marker; reuse it if found.
5. **Prefill the remainder**: the uncached tail, or everything on a full miss.
6. **Store** the new prefix if it was not already stored, but only if it is at least the model's **minimum cacheable length** (512 tokens on the 5.5 models). Below that, nothing is stored and no error is raised.
7. **Start or refresh the timer**: 5 minutes (or 1 hour with `"ttl": "1h"`), measured from the **start** of the request. Every hit resets it to the full TTL at no cost. The entry becomes readable once this response **starts streaming**; parallel requests sent at the same instant all miss.
8. **Generate** the output exactly as without caching.
9. **Report** in `usage` and bill each part at its own rate.

### 2.6 The three input counters

They split the prompt into parts that sum to the full prompt:

```
total prompt tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens
```

| Field                         | Meaning                                                    | Billed at (Haiku 5.5, $0.10/M base)       |
|-------------------------------|------------------------------------------------------------|-------------------------------------------|
| `cache_read_input_tokens`     | Loaded from an existing entry; prefill skipped             | ~0.1x → $0.01/M                           |
| `cache_creation_input_tokens` | Processed now **and** saved as a new entry                 | 1.25x (5m) / 2x (1h) → $0.125/M / $0.20/M |
| `input_tokens`                | Processed now, not saved: everything after the last marker | 1x → $0.10/M                              |

`input_tokens` alone is **not** the prompt size once caching is on; it is only the uncached tail. The week 1 `cost_usd()` already prices the three counters separately.

### 2.7 Worked timeline: one incident, several requests

```
Prompt layout:  [system 150 tok][incident 90k tok ◄marker][ "Summarize this incident." ]
```

| Time     | Request                                        | read   | creation | input           | Why                                                                 |
|----------|------------------------------------------------|--------|----------|-----------------|---------------------------------------------------------------------|
| 10:00:00 | First call                                     | 0      | 90,150   | 12              | Nothing stored: full prefill, prefix saved, 5-min timer starts      |
| 10:02:00 | Validation-retry (same prefix + reply + error) | 90,150 | 0        | 12 + retry text | Exact prefix found; only the new tail is prefilled; timer reset     |
| 10:03:00 | Retry with a second marker further down        | 90,150 | ~700     | 12              | Reads the old prefix, writes only the new stretch to the 2nd marker |
| 10:04:00 | Same call, one character of SYSTEM edited      | 0      | 90,150   | 12              | Different bytes at position 1: everything after it misses           |
| 10:20:00 | Same call, no change                           | 0      | 90,150   | 12              | Entry expired at 10:09 (5 min after the last hit)                   |

Writes bill only the part past the deepest hit.

Diagnosis from the counters:

| Pattern                                        | Cause                                                              |
|------------------------------------------------|--------------------------------------------------------------------|
| `creation` high on every call, `read` always 0 | Prefix changes between calls (a silent invalidator), or gaps > TTL |
| Both 0 on every call                           | Prefix under the minimum (512 tokens), or no marker                |
| `read` grows turn over turn, `creation` small  | Healthy agent loop                                                 |

### 2.8 Rules that follow from the mechanics

**Prefix match only.** Order is `tools` → `system` → `messages`. Stable content first, volatile content after the last marker.

**Minimum cacheable prefix (model-dependent):**

| Models                                                                 | Minimum     |
|------------------------------------------------------------------------|-------------|
| Claude Opus 5.5, Opus 5, Sonnet 5.5, Haiku 5.5, Fable 5 / 5.1          | 512 tokens  |
| Opus 4.8, Sonnet 5, Sonnet 4.6, Sonnet 4.5, Opus 4.1, Opus 4, Sonnet 4 | 1024 tokens |
| Opus 4.7, Haiku 3.5                                                    | 2048 tokens |
| Opus 4.6, Opus 4.5, Haiku 4.5                                          | 4096 tokens |

**The trap in our code.** The plan says "cache the system prompt". Our `SYSTEM` is ~150 tokens, under 512, so a marker there silently does nothing. The block worth caching is the **incident block** (system + alert + logs + metrics). It is identical for every call about the same incident:

- the second run of the done-check,
- the validation-retry (Section 3), which resends the whole incident plus an error message,
- week 3's agent loop, which resends the whole history every step.

**Scope.** Caches are per model and per workspace (Claude API). Organizations never share. Switching Haiku → Sonnet means a cold cache.

**Invalidation tiers.** The prefix is cached in three nested tiers: tools ⊂ system ⊂ messages. A change invalidates its own tier and everything after it:

| What you change                       | Tools part survives | System part survives | Messages part survives |
|---------------------------------------|---------------------|----------------------|------------------------|
| Tool definitions (add/remove/reorder) | no                  | no                   | no                     |
| Model                                 | no                  | no                   | no                     |
| System prompt text                    | yes                 | no                   | no                     |
| `tool_choice`, adding images          | yes                 | yes                  | no                     |
| `thinking` or `effort`                | model-dependent     | model-dependent      | no                     |
| Earlier message content               | yes                 | yes                  | no                     |

**Silent invalidators** (grep anything that feeds the prefix):

| Pattern                                           | Why it breaks caching                           |
|---------------------------------------------------|-------------------------------------------------|
| `datetime.now()` / `time.time()` in system prompt | Prefix changes on every request                 |
| `uuid4()` / `run_id` early in content             | Every request unique                            |
| `json.dumps(d)` without `sort_keys=True`          | Key order can differ → bytes differ             |
| Iterating a `set` to build text                   | Non-deterministic order                         |
| `if flag: system += ...`                          | Each flag combination is a separate prefix      |
| Tool list that varies per user                    | Tools render first; nothing caches across users |

Our code has none of these. Keep `run_id` in `runs.jsonl` only.

### 2.9 How the cache key is computed

Anthropic does not publish the algorithm. What is documented is what the key **depends on**, which is all you need:

1. The exact content up to the marker, rendered tools → system → messages. Every byte counts: text, images, tool definitions, `tool_use`/`tool_result` blocks, whitespace, JSON key order inside tool schemas.
2. The model.
3. The workspace (Claude API).
4. Some request settings, by tier (table above).

Mental model, not the real implementation:

```
key = H(model, workspace, settings, tokens[1 .. marker])
```

You do not need the hash. Make the request bytes deterministic: `json.dumps(..., sort_keys=True)`, fixed tool order, no clock or ids in the prefix, model and effort pinned per route.

### 2.10 Economics

| Operation           | Multiplier on base input price                    |
|---------------------|---------------------------------------------------|
| Cache write, 5-min  | 1.25x                                             |
| Cache write, 1-hour | 2x                                                |
| Cache read          | ~0.1x (Haiku/Sonnet 5.5 class; 0.05x on Opus 5.5) |

Break-even: with the 5-minute TTL, **two** requests already win (1.25 + 0.1 = 1.35 vs 2.0 uncached). With the 1-hour TTL, three or more (2 + 0.1 + 0.1 = 2.2 vs 3.0).

On the INC-001 numbers (Haiku 5.5, $0.10/M input, 90k-token prefix):

| Scenario               | Without caching | With caching                                  |
|------------------------|-----------------|-----------------------------------------------|
| 2 calls (call + retry) | $0.018          | $0.01125 + $0.0009 ≈ $0.012                   |
| 10 agent steps         | $0.090          | $0.01125 + 9 × $0.0009 ≈ $0.019 (~5x cheaper) |

Time to first token also drops on every hit.

**When not to bother:** one-off prompts, prefixes under the minimum, calls on the same prefix more than an hour apart.

### 2.11 Wiring it into the project

`call()` already accepts a list for `messages`; only the prompt builder changes:

```python
# src/triage/summarize.py
from pathlib import Path
from .prefilter import prefilter

def render_incident(folder: Path, mode: str) -> str:
    """Stable incident block: identical bytes for every call on this incident and mode."""
    lines = (folder / "app.log").read_text().splitlines()
    if mode == "raw":
        logs = "\n".join(f"{i}\t{line}" for i, line in enumerate(lines, start=1))
    else:
        logs = prefilter(lines)
    return (f'<incident id="{folder.name}">\n'
            f"<alert>{(folder / 'alert.txt').read_text().strip()}</alert>\n"
            f"<logs>\n{logs}\n</logs>\n"
            f"<metrics>\n{(folder / 'metrics.csv').read_text().strip()}\n</metrics>\n"
            "</incident>")

def build_messages(folder: Path, mode: str) -> list[dict]:
    return [{"role": "user", "content": [
        {"type": "text", "text": render_incident(folder, mode),
         "cache_control": {"type": "ephemeral"}},          # end of the stable part
        {"type": "text", "text": "Summarize this incident."},  # volatile tail
    ]}]
```

Verification as a standing check, not a one-time look (caching usually breaks months later when someone edits prompt-building code):

```python
def test_second_call_reads_cache():                     # integration test, costs a few cents
    msgs = build_messages(Path("data/incidents/INC-001"), "filtered")
    call(msgs, system=SYSTEM, schema=IncidentSummary, tag="test.cache")
    r = call(msgs, system=SYSTEM, schema=IncidentSummary, tag="test.cache")
    assert r.usage.cache_read_input_tokens > 0
```

### 2.12 Optimizations on top of prompt caching

1. **Measure the hit rate**: `read / (read + creation + input)` per tag in `runs.jsonl`. Without it every other item is a guess.
2. **Append-only history**: never edit or delete earlier messages in an agent loop. To change instructions mid-run, append a `{"role": "system", ...}` message to `messages` instead of editing top-level `system` (supported on Opus 5.5, Sonnet 5.5, Haiku 5.5); the cached prefix survives.
3. **Pin model and effort per route**: switching either means a cold cache.
4. **Two markers in agent loops**: one explicit marker at the end of tools + system, plus top-level automatic caching for the growing tail. If one turn adds more than ~15 blocks, add an intermediate marker (the lookback reaches only 20 blocks).
5. **Choose the TTL from the gap between calls**:

   | Start-to-start gap on the same prefix | TTL     |
   |---------------------------------------|---------|
   | Under 5 minutes                       | 5m      |
   | 5 to 60 minutes, bursty               | 1h      |
   | Over 60 minutes                       | Neither |

6. **Fan-out ordering**: N parallel requests over the same prefix all miss. Send one, wait for its first streamed token, then send the other N-1.
7. **Pre-warm**: a request with `max_tokens: 0` writes the cache and returns immediately, so the first real request is already a hit (not supported inside batches).

### 2.13 Response caching (application side)

Two different layers:

| Layer            | What is reused                      | Who runs it        | Saves                                                       |
|------------------|-------------------------------------|--------------------|-------------------------------------------------------------|
| Prompt caching   | The model's processing of the input | Anthropic's server | Most input cost, part of the latency; model still generates |
| Response caching | The final output                    | Your application   | The whole call: $0, ~1 ms                                   |

**Valid only when** the same input should get the same answer and a stale answer is acceptable. Re-running `triage summarize INC-001` on unchanged logs: yes. A chat whose context differs per user: no.

The key must include everything that affects the output:

```python
import hashlib, json

def cache_key(model, effort, prompt_version, schema, system, messages, tenant) -> str:
    blob = json.dumps(
        {"t": tenant,                              # never share across customers
         "m": model, "e": effort,                  # different model/effort -> different answer
         "p": prompt_version,                      # prompt change must miss
         "s": schema.__name__ if schema else None,
         "sys": system, "msg": messages},          # the actual input (hashes the log content)
        sort_keys=True,                            # deterministic bytes
    )
    return hashlib.sha256(blob.encode()).hexdigest()

key = cache_key(...)
if (hit := store.get(key)) is not None:            # check before calling the API
    return hit
summary = summarize(...)                           # only reached on a miss
if not check_citations(summary, folder):           # store only VALIDATED results
    store.set(key, summary, ttl=86_400)
```

| Rule                            | Why                                                                |
|---------------------------------|--------------------------------------------------------------------|
| Store only validated results    | Otherwise a wrong answer is served forever                         |
| `prompt_version` in the key     | A prompt change must miss, or old-prompt answers keep being served |
| Scope per tenant                | Serving user A's answer to user B is a classic data-leak bug       |
| TTL or invalidation rule        | Hashing the input makes new log lines a new key automatically      |
| Disable in evals (`--no-cache`) | Evals need fresh samples to measure run-to-run variance (week 9)   |

**Semantic caching** (embed the query, serve the answer of a *similar* past query) fits FAQ-type questions with one canonical answer. Avoid it for triage: two incidents with similar alerts and different root causes would get the same answer, a confident wrong result.

Order of savings: response-cache hit (whole call skipped) > prompt-cache read (~90% of input saved) > filtering (fewer tokens) > cheaper model or lower effort (trades quality).

---

## 3. Failure handling

### 3.1 Why it is needed

Every `call()` is a network request to a shared, rate-limited service. On a busy day some calls fail even with perfect code. A CLI that crashes with a stack trace on the 4th of 5 incidents is unusable; so is one that retries forever.

### 3.2 Two families of failure

| Family                      | What you see              | Examples                                                                           | Handled by                        |
|-----------------------------|---------------------------|------------------------------------------------------------------------------------|-----------------------------------|
| A. No usable response       | An exception from the SDK | 429, 529, timeout, bad key                                                         | Retries (or fail fast)            |
| B. HTTP 200, but bad output | A normal response         | `stop_reason: max_tokens`, refusal, Pydantic error, cited line that does not exist | Validation + one corrective retry |

### 3.3 Family A: retry or not

| HTTP | Python class (`anthropic.*`)                    | Meaning                     | Retry?                              |
|------|-------------------------------------------------|-----------------------------|-------------------------------------|
| 400  | `BadRequestError`                               | Request malformed           | No: same bytes, same error          |
| 401  | `AuthenticationError`                           | Bad or missing key          | No                                  |
| 402  | `APIStatusError` (type `billing_error`)         | Billing problem             | No                                  |
| 403  | `PermissionDeniedError`                         | No access                   | No                                  |
| 404  | `NotFoundError`                                 | Wrong model id or endpoint  | No                                  |
| 413  | `APIStatusError` (type `request_too_large`)     | Request over the size limit | No: filter it (Section 1)           |
| 429  | `RateLimitError`                                | Your quota exceeded         | Yes, after the `retry-after` header |
| 500  | `InternalServerError`                           | Anthropic-side error        | Yes                                 |
| 529  | `InternalServerError` (type `overloaded_error`) | API busy for everyone       | Yes, with backoff                   |
| —    | `APIConnectionError` / `APITimeoutError`        | Network failure or timeout  | Yes                                 |

Rule: **4xx means you are wrong; retrying is useless. 429, 5xx and network errors are temporary; retry.** Every `APIStatusError` also exposes `.type` (for example `"overloaded_error"`) to classify by name.

### 3.4 What the SDK already does

| Setting       | Default           | Behavior                                                                                                           |
|---------------|-------------------|--------------------------------------------------------------------------------------------------------------------|
| `max_retries` | 2                 | Retries 408/409/429/5xx and connection errors automatically, exponential backoff with jitter, honors `retry-after` |
| `timeout`     | 600 s per attempt | Raises `APITimeoutError`, which is then retried                                                                    |

Worst-case wait = `timeout × (max_retries + 1)` = 30 minutes by default. Far too long for a CLI. Configure, do not reimplement:

```python
import anthropic

client = anthropic.Anthropic(
    timeout=60.0,      # seconds per attempt (Python SDK uses seconds)
    max_retries=4,     # 1 attempt + 4 retries = 5 HTTP requests max per logical call
)

# Granular timeouts
client = anthropic.Anthropic(timeout=anthropic.Timeout(60.0, read=30.0, write=10.0, connect=2.0))

# Per-call override without mutating the client
client.with_options(timeout=10.0, max_retries=0).messages.count_tokens(...)
```

**Backoff, concretely:** wait ~0.5 s, 1 s, 2 s, 4 s (doubling), each with random jitter. Jitter matters: after an outage, 1,000 clients retrying at exactly t+1 s would knock the API over again (**thundering herd**). Random spread avoids it.

### 3.5 CLI error handling and exit codes

An exception that reaches your code means the SDK's retries are used up. Catch most-specific first; print one line; exit with a meaningful code.

```python
# src/triage/cli.py
import anthropic, typer
from .llm import LLMError
from .summarize import summarize

app = typer.Typer()

@app.command("summarize")
def summarize_cmd(incident: str, mode: str = "filtered"):
    folder = Path("data/incidents") / incident
    try:
        s = summarize(folder, mode)
    except anthropic.AuthenticationError:                      # 401: config problem, no retry
        typer.echo("auth failed: check ANTHROPIC_API_KEY", err=True)
        raise typer.Exit(2)
    except (anthropic.RateLimitError,                          # 429 after retries
            anthropic.InternalServerError,                     # 5xx / 529 after retries
            anthropic.APIConnectionError) as e:                # network / timeout after retries
        typer.echo(f"API unavailable after retries: {type(e).__name__}", err=True)
        raise typer.Exit(3)
    except anthropic.APIStatusError as e:                      # any other 4xx: our bug
        typer.echo(f"request rejected ({e.status_code}): {e.message}", err=True)
        raise typer.Exit(5)
    except LLMError as e:                                      # family B, bad output after retry
        typer.echo(f"bad output: {e}", err=True)
        raise typer.Exit(4)
    typer.echo(s.model_dump_json(indent=2))
```

| Exit code | Meaning                               |
|-----------|---------------------------------------|
| 0         | Success                               |
| 2         | Authentication / configuration        |
| 3         | API unavailable after retries         |
| 4         | Output invalid after validation-retry |
| 5         | Request rejected (other 4xx)          |

`call()` already logs failures to `runs.jsonl` before re-raising, so every failed call leaves a row (`ok: false`, `error`, `status`).

### 3.6 Family B: validation-retry, once

The model returned something, but it fails `check_citations()`. Send the exact problems back **once**, then stop.

```python
# src/triage/summarize.py
from .llm import call, LLMError
from .schemas import IncidentSummary

def summarize(folder: Path, mode: str) -> IncidentSummary:
    msgs = build_messages(folder, mode)          # incident block carries the cache marker
    for attempt in (1, 2):
        r = call(msgs, system=SYSTEM, schema=IncidentSummary,
                 tag=f"w02.{mode}.a{attempt}")    # attempt visible in runs.jsonl
        problems = check_citations(r.parsed_output, folder)
        if not problems:
            return r.parsed_output
        msgs = msgs + [                           # APPEND only: keeps the cached prefix valid
            {"role": "assistant", "content": r.content},           # its answer, unchanged
            {"role": "user", "content":
                "Validation failed:\n" + "\n".join(problems)
                + "\nReturn a corrected summary. Cite only lines that exist."},
        ]
    raise LLMError(f"{folder.name}: invalid after retry: {problems[:3]}")
```

| Design choice                           | Reason                                                                                      |
|-----------------------------------------|---------------------------------------------------------------------------------------------|
| Exactly one retry                       | If explicit feedback does not fix it, the problem is the prompt or input, not luck          |
| Append, never rewrite                   | The retry's prefix equals the first call's prefix → cache read (Section 2)                  |
| Pass `r.content` back unchanged         | Includes any thinking blocks; editing them breaks preserved-thinking checks on newer models |
| Pydantic `ValidationError` in `parse()` | No usable reply to feed back: retry once without feedback, then fail                        |

### 3.7 Retry budgets multiply

With `timeout=60, max_retries=4` and one validation-retry, one `triage summarize` can send at most:

```
2 logical calls × (1 attempt + 4 retries) = 10 HTTP requests
worst-case time ≈ 10 × 60 s + backoff (~7.5 s per logical call) ≈ 10.5 minutes
```

Every retry layer (SDK retries, validation-retry, later agent steps) multiplies requests, cost and wall-clock. Set an explicit budget at each layer.

### 3.8 Forced-failure tests

**Bad key**

```bash
ANTHROPIC_API_KEY=sk-bad triage summarize INC-001
# expect: immediate failure (401 is not retried), exit code 2,
#         runs.jsonl row with ok:false, status:401
echo $?    # 2
```

**Mocked 529**: a local server that always answers 529, with the client pointed at it.

```python
# scripts/fake_529.py
from http.server import BaseHTTPRequestHandler, HTTPServer

class Overloaded(BaseHTTPRequestHandler):
    def do_POST(self):
        body = b'{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
        self.send_response(529)                               # what the real API sends when busy
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)
        print("hit", flush=True)                              # count attempts in the terminal

HTTPServer(("127.0.0.1", 8529), Overloaded).serve_forever()
```

```bash
python scripts/fake_529.py &                                   # terminal 1
ANTHROPIC_BASE_URL=http://127.0.0.1:8529 triage summarize INC-001
# expect: "hit" printed 5 times with growing gaps, then exit code 3 and a one-line message
```

`ANTHROPIC_BASE_URL` redirects the SDK to any URL, which makes the test independent of the HTTP library the SDK uses internally.

---

## 4. Prompts as versioned files

### 4.1 Why: the root reason

You can only judge a prompt by measuring its outputs, and a measurement is useless unless you know exactly which prompt produced it.

**Step 1: prompts behave like code, without a compiler or tests.** A bug in Python fails loudly (exception, red test). A worse prompt fails silently: the output is still valid JSON that passes the schema, but the root cause is wrong. The only way to know is to run it on incidents and score the results.

**Step 2: outputs vary run to run.** The same prompt on INC-003 can be right 4 times out of 5. One run proves nothing; you compare distributions ("v1: 13/15 over 3 runs, v2: 9/15"). That needs every result row tagged with the prompt that produced it.

**Step 3: without the tag, the data cannot answer anything.**

| Situation                     | Untagged `runs.jsonl`                                                      | Tagged `runs.jsonl`                                       |
|-------------------------------|----------------------------------------------------------------------------|-----------------------------------------------------------|
| Accuracy dropped on Wednesday | Two SYSTEM edits, one effort change, a filter change, or noise: unknowable | `group by prompt_version` → v1 0.87, v2 0.60: cause found |
| Fix                           | Reconstruct the old prompt from memory                                     | Switch one argument back to v1                            |

The essential part is the **logged identity**; the separate file is the convenient way to get it.

### 4.2 The convention

```
prompts/
  summarize.raw.v1.md          # SYSTEM for raw mode, frozen
  summarize.filtered.v1.md     # SYSTEM for filtered mode ("cite the last tab field")
  summarize.filtered.v2.md     # an edit; v1 stays untouched
  retry_feedback.v1.md         # text of the validation-retry message
```

| Rule                              | Why                                                                        |
|-----------------------------------|----------------------------------------------------------------------------|
| Never edit a released version     | "v1" must always mean the same bytes, or old results stop being comparable |
| A change makes a new file         | Old and new can run side by side                                           |
| Code picks the version explicitly | No hidden "latest"                                                         |
| Every run logs label **and** hash | The hash catches an in-place edit of a released file                       |

```python
# src/triage/prompts.py
import hashlib
from pathlib import Path

PROMPTS = Path("prompts")

def load_prompt(name: str, version: str) -> tuple[str, str, str]:
    """Return (text, label, sha8) for prompts/<name>.<version>.md."""
    text = (PROMPTS / f"{name}.{version}.md").read_text()
    sha8 = hashlib.sha256(text.encode()).hexdigest()[:8]   # content identity
    return text, f"{name}.{version}", sha8

SYSTEM, PROMPT_VERSION, PROMPT_SHA = load_prompt("summarize.filtered", "v1")
```

`call()` gains a `prompt=(label, sha)` argument and writes both into the log row:

```json
{"run_id": "a1b2c3d4e5f6", "tag": "w02.filtered.a1", "model": "claude-haiku-5-5", "effort": "low",
 "prompt_version": "summarize.filtered.v1", "prompt_sha": "3f9a2c1e", "mode": "filtered",
 "input_tokens": 12, "cache_write": 0, "cache_read": 1480, "output_tokens": 690,
 "cost_usd": 0.000362, "latency_s": 3.1, "ok": true}
```

Same label with a different hash means the immutability rule was broken.

### 4.3 What counts as "the prompt"

Everything that shapes the output:

| Element                                                | Where it is versioned               |
|--------------------------------------------------------|-------------------------------------|
| System text                                            | `prompts/*.vN.md`                   |
| Instruction after the cache marker                     | `prompts/*.vN.md`                   |
| Input format (numbered lines, filtered rows, XML tags) | Mode field + prompt version         |
| Output schema (`IncidentSummary` fields, descriptions) | Schema name in the log; git         |
| Model and effort                                       | Separate fields in the same log row |

Together these identify exactly what produced each result.

### 4.4 Uses over time

| Day | Event                                      | How stored versions help                                                                        |
|-----|--------------------------------------------|-------------------------------------------------------------------------------------------------|
| 1   | v1 ships; eval 13/15                       | **Baseline**: every later change is judged against it                                           |
| 8   | v2 written to fix a citation issue         | **A/B**: v1 vs v2 on the same incidents → 14/15 but +20% tokens; a data-backed decision         |
| 12  | "Tuesday's report blamed the wrong commit" | **Reproduce**: the row names v2, model, effort; rerun the exact inputs                          |
| 15  | v2 misses infra causes                     | **Rollback**: one argument back to v1 while fixing                                              |
| 20  | v3 ready                                   | **Regression gate**: CI compares v3 to the baseline; worse → blocked (week 9)                   |
| 30  | Model migration (Haiku 5.5 → Sonnet 5.5)   | **Migration check**: rerun v1-v3 on the new model; prompts tuned for one model drift on another |
| Any | "Why did the agent say X?"                 | **Audit**: the exact text that produced X still exists                                          |

Long term, `v1 → v2 → v3` with scores is a written record of which wording fixed which failure: the failure log and the strongest interview material ("v2 added X, accuracy 0.73 → 0.87, cost +20%").

### 4.5 Why a file and not a string in a `.py` file

| Reason                    | Explanation                                                                              |
|---------------------------|------------------------------------------------------------------------------------------|
| Two versions side by side | git shows one version per checkout; A/B needs v1 and v2 runnable in one process          |
| Immutability is checkable | The logged hash catches in-place edits; a string in code changes silently in refactors   |
| Diffs read as prose       | A PR changing `summarize.v2.md` is reviewable by people who do not read Python           |
| Runtime swap              | A service can choose the version from config or a registry without redeploying (week 11) |

Honest trade-off: for a solo learning project, a string in code is acceptable **if** its hash and the git commit are logged on every row. The file convention costs almost nothing and makes week 9 direct.

Industry equivalent: prompt registries in LangSmith and Langfuse (week 9) store prompts as versioned objects fetched at runtime and linked to traces.

### 4.6 How many prompts to keep

One prompt per **distinct LLM task** × its versions. Prompts in this project by week 12:

| Prompt          | Job                               | Week |
|-----------------|-----------------------------------|------|
| `gen_scenario`  | Design a fake incident            | 1    |
| `summarize`     | Logs → `IncidentSummary`          | 1-2  |
| `map_extract`   | Per-chunk extraction (map-reduce) | 2    |
| `reduce`        | Merge extractions (map-reduce)    | 2    |
| `investigate`   | Agent system prompt               | 3-4  |
| `chunk_context` | Contextual prefix for RAG chunks  | 6    |
| `judge`         | Score an explanation 1-5          | 9    |

| Location      | What to keep                                                                        |
|---------------|-------------------------------------------------------------------------------------|
| Active folder | Current version, the previous one (rollback), any version an eval baseline uses     |
| git           | All versions, forever; a version referenced by a log row or report is never deleted |

In practice: 2-3 live versions per task; a real product has tens to a few hundred prompts.

### 4.7 How prompts help in tests

**Layer 1: deterministic tests on the prompt itself** (pytest; free, except `count_tokens` which is also free). Each guards a silent failure from earlier sections.

```python
# tests/test_prompts.py
import re
from triage.prompts import load_prompt
from triage.summarize import render_incident, prompt_tokens

def test_released_prompts_are_immutable():
    # Section 4: v1 must always mean the same bytes
    _, _, sha = load_prompt("summarize.filtered", "v1")
    assert sha == "3f9a2c1e"

def test_prompt_renders_fully():
    # no unfilled {placeholder} reaches the model
    text, _, _ = load_prompt("summarize.filtered", "v2")
    assert "{" not in text

def test_no_volatile_content_in_prefix():
    # Section 2: timestamps or run ids in the prefix kill the cache
    text, _, _ = load_prompt("summarize.filtered", "v2")
    assert not re.search(r"\d{4}-\d{2}-\d{2}T|run_id", text)

def test_filtered_prompt_fits_budget():
    # Section 1: the token gate holds even for the 50k-line incident
    assert prompt_tokens(render_incident(Path("data/incidents/INC-101"), "filtered")) < 150_000
```

**Layer 2: evals**: the versioned prompt is the **thing under test**; `truth.json` is the expected answer.

```
for each incident in the golden set:
    output = run(prompt="summarize.filtered.v2", model, effort, incident)
    correct = output.error_signature == truth.error_signature and citations valid
accuracy(v2) = 14/15
```

| Eval use        | What it gives                                                                       |
|-----------------|-------------------------------------------------------------------------------------|
| Regression test | v3 must score ≥ v2's baseline minus a tolerance, or CI fails (week 9 GitHub Action) |
| Variance        | Each version run 3×, mean and spread: real improvement vs noise                     |
| Cost            | Tokens and $ per version: "better but 20% more expensive" is visible                |

Unit tests guard the **plumbing around** the prompt and run on every commit for free. Evals guard **what the prompt makes the model do**; they cost money and run on prompt changes.

### 4.8 Why it matters this week

This week you change the prompt yourself at least twice:

1. Section 1 changes the input format: filtered mode needs "cite the last tab field"; raw mode keeps the old wording. Two prompts: `summarize.raw.v1`, `summarize.filtered.v1`.
2. Section 3 adds the validation-retry message: new prompt text that appears only on attempt 2.
3. While testing, wording gets tweaked when a citation fails: v2.

The week 2 deliverable is a raw vs filtered comparison table. `runs.jsonl` will hold rows from all these variants. Without `prompt_version`, the table silently averages a broken v1 with a fixed v2, and "filtered is better" might really mean "the newer prompt is better". **The table is only valid if every row says which prompt produced it.** It also explains log anomalies: a jump in `cache_creation_input_tokens` lines up with the row where `prompt_sha` changed (new bytes, cold cache).

---

## 5. Batches API

### 5.1 Why it exists: sync vs async

Every call so far was **synchronous**: send, wait seconds, get the answer. You pay full price for that immediacy. Much LLM work has nobody waiting:

- running all 30 incidents × 3 runs for an eval (week 9),
- regenerating scenarios,
- summarizing yesterday's 2,000 tickets overnight.

For that work speed is worth nothing and price is everything. The Batches API runs a list of normal Messages requests asynchronously at **50% of the normal price on every token**.

| Someone waiting on the answer?                         | Use                             |
|--------------------------------------------------------|---------------------------------|
| Yes: on-call engineer, CLI, chat, agent loop           | Synchronous `create` / `stream` |
| No: evals, backfills, reprocessing, dataset generation | Batches                         |

Agents cannot use batches: each step depends on the previous answer, and a turnaround of up to an hour per step kills the loop.

### 5.2 Who does what

| Actor     | Responsibility                                                                                        |
|-----------|-------------------------------------------------------------------------------------------------------|
| You       | Build the request list, give each a `custom_id`, upload, store the batch id, poll, download, validate |
| Anthropic | Queue the work, run each request like a normal `messages.create`, store results for 29 days           |
| Nobody    | Streams anything or answers mid-way: fire and collect                                                 |

### 5.3 Endpoints, lifecycle, limits, pricing

| Action  | HTTP                                    | Python SDK                                       |
|---------|-----------------------------------------|--------------------------------------------------|
| Create  | `POST /v1/messages/batches`             | `client.messages.batches.create(requests=[...])` |
| Status  | `GET /v1/messages/batches/{id}`         | `client.messages.batches.retrieve(id)`           |
| Results | `GET /v1/messages/batches/{id}/results` | `client.messages.batches.results(id)`            |
| List    | `GET /v1/messages/batches?limit=20`     | `client.messages.batches.list(limit=20)`         |
| Cancel  | `POST /v1/messages/batches/{id}/cancel` | `client.messages.batches.cancel(id)`             |

Lifecycle:

```
in_progress ──────────────────────────► ended
     │                                    ▲
     └── cancel() ──► canceling ──────────┘   (may contain partial results)
```

A submitted batch cannot be modified, only canceled.

| Limit / property           | Value                                                              |
|----------------------------|--------------------------------------------------------------------|
| Size                       | 100,000 requests or 256 MB per batch, whichever comes first        |
| Typical completion         | Under 1 hour                                                       |
| Expiry                     | Requests not finished within 24 hours expire                       |
| Result retention           | 29 days after creation                                             |
| `max_tokens`               | At least 1 per request (`max_tokens: 0` pre-warming not supported) |
| Scope                      | Workspace                                                          |
| Billing of failed requests | Errored, canceled and expired requests are not billed              |

| Model (prompts ≤ 100k tokens) | Batch input  | Batch output |
|-------------------------------|--------------|--------------|
| Claude Haiku 5.5              | $0.05 / MTok | $0.25 / MTok |

### 5.4 Making the request

Each request is `{custom_id, params}`; `params` is exactly a normal Messages request body.

**`custom_id` rules:** 1-64 characters, only letters, digits, `-` and `_` (`^[a-zA-Z0-9_-]{1,64}$`). An id like `INC-001|summarize.filtered.v1` is **invalid** (`|` and `.` are not allowed). Use `INC-001__filtered-v1`, or keep a local map from id to metadata.

**Wire format**

```json
POST /v1/messages/batches
{
  "requests": [
    {
      "custom_id": "INC-001__filtered-v1",
      "params": {
        "model": "claude-haiku-5-5",
        "max_tokens": 16000,
        "system": "You are an SRE triaging...",
        "messages": [{"role": "user", "content": [
          {"type": "text", "text": "<incident id=\"INC-001\">...",
           "cache_control": {"type": "ephemeral", "ttl": "1h"}},
          {"type": "text", "text": "Summarize this incident."}
        ]}],
        "output_config": {
          "effort": "low",
          "format": {"type": "json_schema", "schema": {"...": "IncidentSummary JSON schema"}}
        }
      }
    },
    {"custom_id": "INC-002__filtered-v1", "params": {"...": "..."}}
  ]
}
```

**Python**

```python
# scripts/run_batch.py
from pathlib import Path
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from triage.llm import client
from triage.summarize import build_messages
from triage.prompts import load_prompt

SYSTEM, PV, SHA = load_prompt("summarize.filtered", "v1")
INCIDENTS = ["INC-001", "INC-002", "INC-003", "INC-004", "INC-005"]

reqs = [
    Request(
        custom_id=f"{inc}__filtered-v1",                   # routing info lives in the id
        params=MessageCreateParamsNonStreaming(
            model="claude-haiku-5-5",
            max_tokens=16000,
            system=SYSTEM,
            messages=build_messages(Path(f"data/incidents/{inc}"), "filtered"),
            output_config={
                "effort": "low",
                "format": {"type": "json_schema",           # no parse() helper in batches:
                           "schema": SUMMARY_SCHEMA},       # pass the JSON schema yourself
            },
        ),
    )
    for inc in INCIDENTS
]

batch = client.messages.batches.create(requests=reqs)
Path("runs/batches.txt").open("a").write(batch.id + "\n")  # the id is your only handle
print(batch.id, batch.processing_status)                   # msgbatch_01..., in_progress
```

`SUMMARY_SCHEMA` is the JSON schema that `parse()` builds from `IncidentSummary` (week 1, section 3); batches take raw params, so it is passed explicitly.

**Immediate response: a Message Batch object, not answers**

```json
{
  "id": "msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d",
  "type": "message_batch",
  "processing_status": "in_progress",
  "request_counts": {"processing": 5, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0},
  "ended_at": null,
  "created_at": "2026-11-05T09:00:00Z",
  "expires_at": "2026-11-06T09:00:00Z",
  "cancel_initiated_at": null,
  "results_url": null
}
```

### 5.5 Waiting

```python
import time

while (b := client.messages.batches.retrieve(batch.id)).processing_status != "ended":
    print(b.request_counts)          # processing / succeeded / errored / canceled / expired
    time.sleep(60)                   # minutes-scale job: poll slowly
print("ended:", b.request_counts, b.results_url)
```

When it ends, `results_url` is set and the counts are final. The Console (Workspace → Batches) shows the same.

### 5.6 Collecting results: format

Results are a **JSONL file**: one JSON object per line, one line per request, **in any order**. Match by `custom_id`, never by position.

Succeeded line (`message` is a complete, normal Message):

```json
{"custom_id":"INC-002__filtered-v1","result":{"type":"succeeded","message":{"id":"msg_01...","type":"message","role":"assistant","model":"claude-haiku-5-5","content":[{"type":"text","text":"{\"service\":\"search\",...}"}],"stop_reason":"end_turn","usage":{"input_tokens":12,"cache_read_input_tokens":1480,"output_tokens":690}}}}
```

Errored line (`error` uses the standard API error envelope):

```json
{"custom_id":"INC-004__filtered-v1","result":{"type":"errored","error":{"type":"error","error":{"type":"invalid_request_error","message":"..."}}}}
```

| Result type | Meaning                                       | Billed | Action                                               |
|-------------|-----------------------------------------------|--------|------------------------------------------------------|
| `succeeded` | Message created                               | Yes    | Validate like a sync result                          |
| `errored`   | Invalid request or server error               | No     | `invalid_request_error`: fix; server error: resubmit |
| `canceled`  | Batch canceled before this request ran        | No     | Resubmit if still needed                             |
| `expired`   | 24-hour limit reached before this request ran | No     | Resubmit                                             |

**Raw download (archive)**

```bash
curl -s "https://api.anthropic.com/v1/messages/batches/$BATCH_ID/results" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2026-10-21" > runs/batch_$BATCH_ID.jsonl
```

**SDK (streams and parses each line into typed objects)**

```python
from triage.schemas import IncidentSummary
from triage.summarize import check_citations
from triage.llm import text_of, log_run

resubmit, fix = [], []
for res in client.messages.batches.results(batch.id):        # streamed, any order
    inc = res.custom_id.split("__")[0]                        # route by id
    folder = Path(f"data/incidents/{inc}")
    match res.result.type:
        case "succeeded":
            msg = res.result.message                          # same shape as messages.create()
            s = IncidentSummary.model_validate_json(text_of(msg))
            problems = check_citations(s, folder)
            log_run(msg, tag="w02.batch", prompt=(PV, SHA),
                    batch=True,                               # cost_usd halves for batch rows
                    ok=not problems)
            if problems:
                fix.append((inc, msg, problems))              # goes into a second batch
        case "errored":
            print(inc, res.result.error.error.type)           # invalid_request_error vs api_error
            resubmit.append(inc)
        case "canceled" | "expired":
            resubmit.append(inc)
```

The batch produces no summary report of its own. **The report is what you build** from these lines: each succeeded line becomes a `runs.jsonl` row (tokens, cost at 50%, `batch: true`, prompt version, validation outcome), and those rows feed the Section 6 table.

### 5.7 Rules that follow from the mechanics

| Rule                                      | Reason                                                                                                |
|-------------------------------------------|-------------------------------------------------------------------------------------------------------|
| Route by `custom_id`                      | Results arrive in any order                                                                           |
| Each request stands alone                 | One bad request does not sink the batch                                                               |
| Validation-retry = a second batch         | The corrective round trip needs the first answer; collect failures, resubmit with feedback            |
| SDK `max_retries` does not apply inside   | Anthropic runs the requests; your retries cover only upload and poll calls                            |
| Caching is best-effort (30-98% hit rates) | Order and concurrency are not yours to control; use `"ttl": "1h"` on shared prefixes; discounts stack |
| Log `batch: true` and halve the cost      | Otherwise `runs.jsonl` overstates spend 2x                                                            |
| Store the batch id durably                | It is the only way to retrieve results later                                                          |

### 5.8 Money (illustrative, filtered mode, 5 incidents, Haiku 5.5)

| Mode        | Calculation                                 | Total     |
|-------------|---------------------------------------------|-----------|
| Synchronous | 5 × (1.5k in × $0.10/M + 700 out × $0.50/M) | ≈ $0.0025 |
| Batch       | Same tokens at 50%                          | ≈ $0.0012 |

Pennies here; the same ratio decides real budgets for week 9's 30 incidents × 3 runs × several prompt versions and for nightly production jobs.

---

## 6. Measurement and deliverable

### 6.1 Why

Sections 1-5 each make a claim: filtering is cheaper and as accurate, caching cuts cost, retries make the CLI robust. Claims are beliefs until measured. The week ends with one table that proves or disproves them on your own incidents. Every later week ends the same way, in `notes/wNN.md`.

### 6.2 Experiment design

| Kept fixed                                                 | Varied                                |
|------------------------------------------------------------|---------------------------------------|
| Incidents INC-001…005 (3k lines) + INC-101/103 (50k lines) | `--mode raw` vs `--mode filtered`     |
| Model `claude-haiku-5-5`, effort `low`                     | Prompt version per mode (Section 4)   |
| Schema `IncidentSummary`, validator `check_citations`      | Run number (1 vs 2, within 5 minutes) |

Run each configuration twice within 5 minutes; run 2 shows the cache effect.

### 6.3 Where each column comes from

Nothing is measured by hand.

| Column             | Source                                                                                     |
|--------------------|--------------------------------------------------------------------------------------------|
| Prompt tokens      | `input_tokens + cache_write + cache_read` (full prompt size)                               |
| Cache read (run 2) | `cache_read` on the second run                                                             |
| Cost $             | `cost_usd` from `call()`; halved for batch rows                                            |
| Latency s          | `latency_s`                                                                                |
| Correct signature  | `summary.error_signature == truth.json["error_signature"]` (code, not the model's opinion) |
| Citations OK       | `check_citations()` returned no problems                                                   |
| Retries            | Number of attempt rows per incident (`tag` ends `.a2`)                                     |

### 6.4 Aggregation

```python
# scripts/w02_table.py
import pandas as pd

df = pd.read_json("runs.jsonl", lines=True)                 # JSONL → one row per call
df = df[df.tag.str.startswith("w02")]                       # this week's runs only
df["prompt_tokens"] = df.input_tokens + df.cache_write + df.cache_read

table = df.groupby(["mode", "prompt_version"]).agg(
    runs=("run_id", "count"),
    tokens=("prompt_tokens", "median"),
    cost=("cost_usd", "sum"),
    latency=("latency_s", "median"),
    correct=("correct", "mean"),                            # added after scoring vs truth.json
    cache_read=("cache_read", "max"),
)
print(table.to_markdown())                                  # paste into notes/w02.md
```

### 6.5 What `notes/w02.md` looks like

Illustrative numbers showing the shape, not measured results:

| Mode                | Prompt                | Median prompt tokens | Cost (5 inc) | Median latency | Correct          | Cache read run 2 |
|---------------------|-----------------------|----------------------|--------------|----------------|------------------|------------------|
| raw                 | summarize.raw.v1      | 90,000               | $0.045       | 14 s           | 4/5              | 89,900           |
| filtered            | summarize.filtered.v1 | 1,500                | $0.002       | 3 s            | 5/5              | 1,480            |
| raw, 50k lines      | —                     | ~1.5M                | —            | —              | rejected: no fit | —                |
| filtered, 50k lines | summarize.filtered.v1 | 1,700                | $0.0004      | 3 s            | 2/2              | —                |

Below the table:

- **Failure tests**: bad key → exit 2, no retries; fake 529 → 5 hits, then exit 3.
- **Batch run**: 5 incidents, cost vs the sync run (≈ 50%), time to `ended`.
- **One-sentence conclusion** (required by the plan), for example: *"Raw stuffing is worse when the cause is one line among thousands of repeated ones: filtering cut cost ~20x and latency ~4x with equal or better accuracy; raw only makes sense when the input is small or the cause is spread across many unique lines the filter would drop."*

### 6.6 Done check (from the plan)

- [ ] The table shows tokens, cost, latency and correct signature for raw vs filtered
- [ ] Run 2 shows `cache_read_input_tokens > 0`
- [ ] A forced failure (bad key, mocked 529) retries as expected and exits cleanly
- [ ] You can state in one sentence when stuffing raw logs is worse than filtering

### 6.7 What this week amounts to

`triage summarize` v2 is a component you can put numbers on: bounded input, known cost per incident, cached, robust to API failures, every result traceable to a prompt version. Week 3 builds the agent loop on top: every step resends the history (caching), calls tools that can fail (retries and `is_error`), and is judged by the same kind of table.

---

## 7. Code changes summary

| File                         | Change                                                                                                                          | Section |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------|---------|
| `src/triage/prefilter.py`    | New: `signature()`, `prefilter()` (WARN/ERROR + rare signatures, original line numbers)                                         | 1       |
| `src/triage/summarize.py`    | `render_incident(mode)`, `build_messages()` with cache marker, `summarize()` validation-retry                                   | 1, 2, 3 |
| `src/triage/llm.py`          | Client `timeout=60, max_retries=4`; `call()` logs `prompt_version`, `prompt_sha`, `mode`, `batch`, `correct`; batch cost halved | 2-5     |
| `src/triage/prompts.py`      | New: `load_prompt(name, version)` → text, label, sha8                                                                           | 4       |
| `prompts/*.vN.md`            | New: `summarize.raw.v1`, `summarize.filtered.v1`, `retry_feedback.v1`                                                           | 4       |
| `src/triage/cli.py`          | `--mode raw\|filtered`, error chain with exit codes 2/3/4/5                                                                     | 1, 3    |
| `scripts/fake_529.py`        | New: local always-529 server for the forced-failure test                                                                        | 3       |
| `scripts/run_batch.py`       | New: submit, poll, collect, validate, log                                                                                       | 5       |
| `scripts/w02_table.py`       | New: aggregate `runs.jsonl` into the week table                                                                                 | 6       |
| `tests/test_prompts.py`      | New: immutability, render, no volatile content, token budget                                                                    | 4       |
| `notes/w02.md`               | New: table, failure tests, batch result, one-sentence conclusion                                                                | 6       |
| `data/incidents/INC-101,103` | New: 50k-line inflated incidents from saved scenarios                                                                           | 1       |

---

## 8. Glossary

| Term                | Meaning                                                                                                 |
|---------------------|---------------------------------------------------------------------------------------------------------|
| Context window      | Maximum tokens (input + output) a model can handle in one request; 1M on the 5.5 models                 |
| `count_tokens`      | Free endpoint returning the input-token count of a request without running the model                    |
| Signature           | A log line with its variable parts (numbers, ids) replaced by placeholders; identifies the template     |
| Map-reduce          | Chunk the input, extract per chunk (map), merge the extractions in one call (reduce)                    |
| Prefill             | The model's pass over all input tokens before the first output token; the cost behind input pricing     |
| KV cache            | Key and value vectors produced per token per layer during prefill; the processed state of the prompt    |
| Prefix              | The prompt from its first token up to a given position; caching reuses only identical prefixes          |
| Prompt caching      | Server-side reuse of a prefix's processed state across requests                                         |
| Breakpoint / marker | A `cache_control` field on a content block: "cache everything up to here"; max 4 per request            |
| TTL                 | Time-to-live of a cache entry: 5 minutes (default) or 1 hour; reset on every hit                        |
| Cache write / read  | `cache_creation_input_tokens` (billed 1.25x/2x) / `cache_read_input_tokens` (billed ~0.1x)              |
| Silent invalidator  | Anything that changes prefix bytes between requests (timestamps, unsorted JSON) and zeroes the hit rate |
| Response cache      | Application-side store of final outputs keyed by everything that affects them                           |
| Semantic cache      | Serving the answer of a *similar* past query; unsafe where similar inputs need different answers        |
| Backoff             | Increasing wait between retries (0.5 s, 1 s, 2 s, 4 s...)                                               |
| Jitter              | Random spread added to backoff so clients do not retry in lockstep                                      |
| Thundering herd     | Many clients retrying at the same instant and overloading a recovering service                          |
| Validation-retry    | Sending the model its own invalid answer plus the exact errors, once, to get a corrected answer         |
| Exit code           | Process return value telling scripts and CI what kind of failure happened                               |
| Prompt version      | Immutable label (`summarize.filtered.v1`) plus content hash identifying the exact prompt of a run       |
| Eval                | Running a prompt/model configuration over a fixed dataset and scoring against ground truth              |
| Batch               | An async job of up to 100k Messages requests at 50% price, results within 24 hours                      |
| `custom_id`         | Your id for one request in a batch (`^[a-zA-Z0-9_-]{1,64}$`); the only way to match results             |
| JSON                | Text format for one structured document; the API's wire format                                          |
| JSONL               | JSON Lines: one JSON object per line; for logs and bulk results (`runs.jsonl`, batch results)           |

---

## 9. Links to the rest of the plan

| Week | Topic                         | What it reuses from week 2                                                                                  |
|------|-------------------------------|-------------------------------------------------------------------------------------------------------------|
| 3    | Tools and a hand-written loop | Caching (the loop resends history), retries, tool errors as `is_error`, truncating tool results (Section 1) |
| 4    | Tool design, context, MCP     | Context limits → compaction; token budgets measured from `runs.jsonl`                                       |
| 6    | Hybrid search, reranking      | Contextual chunk prefixes generated with caching on the full document                                       |
| 9    | Evals, tracing, CI            | Prompt versions, batches for eval runs, variance, regression gates                                          |
| 10   | Guardrails                    | Validation (evidence verifier), retry-then-fail, injection defense on log content                           |
| 12   | Docker, limits, monitoring    | Rate limits, backoff, per-incident token and cost budgets at service scale                                  |

Docs to read (Claude): Prompt caching, Token counting, Batch processing, Long context tips, Errors, Rate limits.

---

## 10. Q&A from the sessions

**Q1. The long-input strategy changes with the problem, doesn't it?**
Yes. The specific filter (signature collapse) is domain-specific. What carries over is the four-step pattern: measure, reduce in code what code can reduce exactly, keep pointers back to the source, escalate only when needed. Only step 2 changes per domain (logs, contracts, code, tickets, metrics; table in §1.8). The universal failure check: can the reducer delete the answer? Test it against ground truth.

**Q2. Where would this prefilter hide or drop the real cause?** (Section 1 task)
- The cause is a **frequent** INFO line: for example, after a bad config push the service logs `pool size=5` every minute. Count > 3 and level INFO, so it is dropped.
- A **high-cardinality** field the normalizer misses (hostnames, hex ids, quoted strings): every line becomes unique, "rare" explodes, and the signal is buried again.
- The cause is an **absence or a rate change** (a heartbeat stops, throughput halves): counting collapses timing, so the change is invisible.
- The cause sits in **multi-line stack-trace continuation lines**, which the line regex skips.

**Q3. What is prompt caching, why is it required, who performs it, and how does it work?**
The API is stateless and re-reads the whole prompt every call; prefill on a 90k-token incident is repeated work. Anthropic's servers store the processed state (KV cache) of a prefix and reuse it when the next request starts with the same bytes. The server does storage, lookup, expiry and billing; the client marks the reusable part and keeps it byte-identical. Full mechanics: §2.1-2.7.

**Q4. How does the client application tell the server to cache?**
One JSON field on a content block: `"cache_control": {"type": "ephemeral"}` (optionally `"ttl": "1h"`), or the top-level automatic form. No separate endpoint, no header. The SDK passes the field through unchanged. Proof comes back only in `usage`. See §2.4.

**Q5. What exactly does the server do on seeing the marker? What are `cache_creation_input_tokens` and `cache_read_input_tokens`?**
Render tools → system → messages, fingerprint the prefix up to the marker, look it up (with a 20-block lookback), prefill only the uncached remainder, store the new prefix if ≥ 512 tokens, start or refresh the TTL, generate, report. `cache_creation_input_tokens` = tokens processed now and saved (1.25x/2x); `cache_read_input_tokens` = tokens loaded from a stored entry (~0.1x); `input_tokens` = the uncached tail. The three sum to the full prompt. See §2.5-2.7.

**Q6. Predict write/read for: A first call; B same request 2 minutes later; C one character of SYSTEM edited; D same as C, 10 minutes later.** (Section 2 task)

| Call | `cache_creation_input_tokens` | `cache_read_input_tokens` | Why                                              |
|------|-------------------------------|---------------------------|--------------------------------------------------|
| A    | ≈ full prefix                 | 0                         | Nothing stored yet                               |
| B    | 0                             | ≈ full prefix             | Identical bytes within the TTL                   |
| C    | ≈ full prefix                 | 0                         | Byte change at position 1 invalidates everything |
| D    | ≈ full prefix                 | 0                         | C's entry expired after 5 minutes                |

**Q7. If I build an agentic system that needs caching, does the server do it all for me?**
No, not on the Claude API. Caching is opt-in. You add markers, keep the prefix byte-identical, order stable content first, and verify `cache_read_input_tokens > 0`. In an agent: one marker after tools + system, automatic caching for the growing tail, append-only history, no tool reordering, model and effort pinned. Products like Claude Code do this internally.

**Q8. What is the logic for computing the cache hash?**
Not published. The key depends on the exact bytes up to the marker (tools → system → messages), the model, the workspace, and some settings by tier (§2.8 table). Mental model: `H(model, workspace, settings, tokens[1..marker])`. Make the request deterministic and the hash takes care of itself.

**Q9. What optimizations can I do on top of caching? Should I also store responses to serve my own clients?**
On caching: measure hit rate, append-only history, pin model/effort, two markers in loops, pick TTL by call gap, fan-out ordering, pre-warm (§2.12). Response caching is a different layer that skips the call entirely; use it only exact-match, keyed on everything that affects output, storing only validated results, scoped per tenant, disabled in evals. Avoid semantic caching for triage (§2.13).

**Q10. Is this week about leveraging LLMs effectively and serving clients?**
About leveraging the LLM effectively: treating it as a bounded, metered, unreliable, changeable dependency (§0.1). Serving many clients (API, webhooks, queues, concurrency) is weeks 11-12, which reuse these ideas at scale.

**Q11. With `timeout=60, max_retries=4` and one validation-retry, what is the maximum number of HTTP requests and the worst-case time?** (Section 3 task)
10 requests (2 logical calls × 5 attempts); about 10.5 minutes (10 × 60 s + backoff). Retry layers multiply; budget each layer (§3.7).

**Q12. Why keep prompts as versioned files, exactly?**
Prompts change behavior without a compiler or tests, and outputs vary run to run, so prompts are judged by measurement; measurements need to know which prompt produced them. Files allow side-by-side versions, a checkable immutability rule, prose diffs and runtime swaps (§4.1, §4.5).

**Q13. What purpose do stored prompts serve? How do they help us?**
Each old version is a known, measured, reproducible state: baseline, A/B, reproduction of a bad report, rollback, regression gate, model migration check, audit, and a record of which wording fixed which failure (§4.4).

**Q14. How many prompts must be kept? How do they help in tests?**
One per distinct LLM task × 2-3 live versions; all versions stay in git (§4.6). Tests: deterministic pytest checks on the prompt (immutability, rendering, no volatile content, token budget) and evals where the versioned prompt is the thing under test against `truth.json` (§4.7).

**Q15. Why does prompt versioning matter in week 2 specifically?**
This week you create at least three prompt variants (raw, filtered, retry feedback, plus tweaks), and the deliverable compares raw vs filtered. Without `prompt_version` on each row, the table mixes prompts and its conclusion is invalid (§4.8).

**Q16. Describe the Batches API in detail: how is a request made, how are results collected, in what format?**
Endpoints, lifecycle, limits and pricing: §5.3. Request: `POST /v1/messages/batches` with `{"requests": [{"custom_id", "params"}]}`, `params` being a normal Messages body; the response is a Message Batch object with an id (§5.4). Poll until `ended` (§5.5). Results: JSONL, one line per request, any order, with `succeeded` / `errored` / `canceled` / `expired`; stream via the SDK or download from `results_url` (§5.6). Correction from the session: `custom_id` allows only `[a-zA-Z0-9_-]`, max 64 characters.

**Q17. Why is JSON used so much?**
Three reasons. JSON is the API's wire format. `.json` holds single documents (`truth.json`, scenarios, schemas) that Pydantic reads and writes directly. `.jsonl` holds streams of records (`runs.jsonl`, batch results) because it appends one line at a time, survives crashes, streams large files, works with `grep`/`tail`, and loads into pandas with `lines=True`. Human-facing files use other formats: `.md` for prompts and notes, `.log`, `.csv`.

| Need                   | JSON array `[{...},{...}]`       | JSONL `{...}\n{...}\n`                        |
|------------------------|----------------------------------|-----------------------------------------------|
| Append a new run       | Rewrite the whole file           | Write one line                                |
| Crash mid-write        | Whole file corrupt (missing `]`) | Only the last line lost                       |
| Read 2 GB of results   | Load everything into memory      | Process line by line, as a stream             |
| Inspect from the shell | Hard                             | `grep INC-003 runs.jsonl`, `tail -f`, `wc -l` |
| Analyze                | `json.load`                      | `pandas.read_json(path, lines=True)`          |

**Q18. What did week 2 cover?**
Long inputs, prompt caching (plus response caching), failure handling, prompt versioning, batches, and the measurement that ties them together.
