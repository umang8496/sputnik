<!-- markdownlint-disable MD001 -->
<!-- markdownlint-disable MD024 -->
<!-- markdownlint-disable MD025 -->
<!-- markdownlint-disable MD026 -->
<!-- markdownlint-disable MD029 -->
<!-- markdownlint-disable MD033 -->
<!-- markdownlint-disable MD040 -->
<!-- markdownlint-disable MD056 -->
<!-- markdownlint-disable MD060 -->

# Result

> python scripts/e7_batch.py submit

```code
{
  "id": "msgbatch_011R9qjRReihfyZpkhPnrrSN",
  "processing_status": "in_progress",
  "request_counts": {
    "canceled": 0,
    "errored": 0,
    "expired": 0,
    "processing": 5,
    "succeeded": 0
  }
}
```

> python scripts/e7_batch.py collect msgbatch_011R9qjRReihfyZpkhPnrrSN

```code
     0s  in_progress  {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 5, 'succeeded': 0}
    31s  in_progress  {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 5, 'succeeded': 0}
    61s  in_progress  {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 5, 'succeeded': 0}
    92s  in_progress  {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 5, 'succeeded': 0}
   122s  in_progress  {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 5, 'succeeded': 0}
   153s  in_progress  {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 5, 'succeeded': 0}
ended: {'canceled': 0, 'errored': 0, 'expired': 0, 'processing': 0, 'succeeded': 5}  created=2026-11-07 08:38:24.139971+00:00  ended=2026-11-07 08:41:51.942947+00:00

INC-001: sig='PoolTimeout'      truth='PoolTimeout'      correct=True  citations=OK  in=2541 out=496 $0.000251
INC-005: sig='RateLimitExceeded' truth='RateLimitExceeded' correct=True  citations=OK  in=2570 out=965 $0.000370
INC-002: sig='PoolTimeout'      truth='CacheMissStorm'   correct=False citations=OK  in=2688 out=1470 $0.000502
INC-003: sig='TLS_CERT_EXPIRED' truth='TLS_CERT_EXPIRED' correct=True  citations=OK  in=2647 out=1448 $0.000494
INC-004: sig='OOMKilled'        truth='OOMKilled'        correct=True  citations=OK  in=2657 out=1295 $0.000457

batch total: $0.002074  (sync would be ~$0.004147)
```
