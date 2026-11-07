<!-- markdownlint-disable MD001 -->
<!-- markdownlint-disable MD024 -->
<!-- markdownlint-disable MD025 -->
<!-- markdownlint-disable MD026 -->
<!-- markdownlint-disable MD029 -->
<!-- markdownlint-disable MD033 -->
<!-- markdownlint-disable MD036 -->
<!-- markdownlint-disable MD040 -->
<!-- markdownlint-disable MD041 -->
<!-- markdownlint-disable MD056 -->
<!-- markdownlint-disable MD060 -->

**Built (8 steps, on your machine)**

- **Project skeleton:** `week-01/triage`, an installable package with a `triage` CLI, the API key in `.env`, and a smoke test that passed.
- **`call()` gateway:** every request goes through one function. It logs model, effort, tokens, cost, latency, TTFT and failures to `runs.jsonl`, and raises on truncation or refusal.
- **API pokes (notebook):** the response anatomy, `max_tokens` truncation, effort low vs high, `count_tokens` vs actual, and multi-turn resend cost.
- **Synthetic incidents:** Haiku wrote 5 small scenarios as structured output, and Python expanded each into 3,000 log lines plus alert, metrics and `truth.json`, using a fixed seed.
- **Data review:** caught the shared signature (`PoolTimeout` in both INC-001 and INC-002), fixed it with no model call, and got every flag to none.
- **`triage summarize`:** a numbered log in XML tags, schema-enforced output (`IncidentSummary`), and a code check that every cited line exists verbatim. 5 of 5 passed.
- **Streaming:** the same command with `--stream`, live tokens, and the measured TTFT.
- **Cost audit:** a pandas breakdown of `runs.jsonl`.
- **Notes and tag:** `notes/w01.md`, a root `.gitignore`, commit, tag `w01`, pushed.

**Demonstrated**

- **The guarantees are layered.** The schema gives shape, Pydantic gives bounds, and only your code gives truth.  
  Every summary was schema-valid, and some were still wrong.
- **Split the work between model and code.** The model writes about 1K tokens of scenario; code writes the 3,000 lines.  
  That is cheap, deterministic and repeatable, and the answer key is correct by construction.
- **A loose grader hides a bad model.** INC-002 scored "OK" while naming the symptom (`PoolTimeout`) instead of the cause.
- **Anything code can compute exactly should not come from the model.**  
  Timestamps lost their milliseconds on 3 of 5 incidents, even though the model cited the right lines.
- **Outputs vary run to run.** The same input gave 5 citations once and 3 the next time, so grade against truth, not against a previous run.
- **Streaming buys time to first token only** (2.9s). Total latency and cost stay the same.
- **Effort costs real tokens:** high vs low was +59% output tokens and +55% latency on the same task.
- **Measure tokens; don't estimate them.** Logs run 2.0 characters per token, so the summarize prompt is about 144K tokens.

**Found and fixed**

- **The cost logger ignored Haiku's price tier above 100K-token prompts** and under-reported by 5x.  
  Real spend was $0.453, not $0.096: about $0.074 per incident, or about $223 a month at 100 incidents a day.
- **The biggest cost lever is staying under 100K tokens per prompt,** not changing models.

**Open, carried to week 2**

- an exact-match signature grader and a short signature id
- the timestamp derived from the cited line
- cutting prompt size with a prefilter and retrieval

---
