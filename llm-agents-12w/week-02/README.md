<!-- markdownlint-disable MD001 -->
<!-- markdownlint-disable MD024 -->
<!-- markdownlint-disable MD025 -->
<!-- markdownlint-disable MD026 -->
<!-- markdownlint-disable MD029 -->
<!-- markdownlint-disable MD033 -->
<!-- markdownlint-disable MD040 -->
<!-- markdownlint-disable MD056 -->
<!-- markdownlint-disable MD060 -->

# Week 2 notes: measured results

Model `claude-haiku-5-5`, effort `low`, incidents INC-001…005 (3k lines) + INC-101 (50k lines).
Prompts: `summarize.raw.v1`, `summarize.filtered.v1` (sha 03eb96b8).

## Raw vs filtered (E8)

<!-- paste the contents of week-02/e8_table.md here -->

## Input size (E2, count_tokens)

| Incident | Mode     | Tokens    | Verdict              |
|----------|----------|-----------|----------------------|
| INC-001  | filtered | 1,399     | ok                   |
| INC-001  | raw      | 146,105   | over 100k price tier |
| INC-101  | filtered | 6,911     | ok (metrics.csv dominates) |
| INC-101  | raw      | 2,447,231 | does not fit 1M window |

Structured-output schema adds ~920 input tokens per call (E3: 2,318 cached vs 1,399 counted).

## Caching (E3)

First call `write=2318 read=0`; same request `write=0 read=2318`; system prefixed "Note: " → `write=2321 read=0`.

## Failure tests (E4)

| Test          | Result                                         | Exit |
|---------------|------------------------------------------------|------|
| Bad key       | AuthenticationError 401, 1 request, 0.4 s       | 2    |
| Fake 529      | OverloadedError, 5 attempts, 6.6 s              | 3    |

## Batch (E7)

msgbatch_011R9qjRReihfyZpkhPnrrSN: 5/5 succeeded in 3.5 min, $0.0021 (sync ≈ $0.0041), correct 4/5.

## Failure log

| Date       | Incident | Agent said   | Truth          | Cause                                              | Fix candidate                                     |
|------------|----------|--------------|----------------|----------------------------------------------------|---------------------------------------------------|
| 2026-11-07 | INC-001  | cited `count\tlast\ttext` | line text only | week-1 prompt describes raw format, used in filtered mode | separate `summarize.filtered.v1` (done, E6)       |
| 2026-11-07 | INC-002  | PoolTimeout  | CacheMissStorm | picked the most frequent (downstream) error, not the first in the causal chain | v2: "signature of the earliest error in the causal chain" |

## Conclusion

<!-- one sentence: when is stuffing raw logs worse than filtering? -->
