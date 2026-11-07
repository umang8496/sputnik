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

```code
filtered r1 INC-001: sig='PoolTimeout'          truth='PoolTimeout'        correct=True  attempts=1 tokens=  2,540 read=      0 $0.00080 4.6s
filtered r1 INC-002: sig='PoolTimeout'          truth='CacheMissStorm'     correct=False attempts=1 tokens=  2,687 read=      0 $0.00101 5.6s
filtered r1 INC-003: sig='TLS_CERT_EXPIRED'     truth='TLS_CERT_EXPIRED'   correct=True  attempts=1 tokens=  2,646 read=      0 $0.00091 4.9s
filtered r1 INC-004: sig='OOMKilled'            truth='OOMKilled'          correct=True  attempts=1 tokens=  2,656 read=      0 $0.00085 4.6s
filtered r1 INC-005: sig='RateLimitExceeded'    truth='RateLimitExceeded'  correct=True  attempts=1 tokens=  2,569 read=      0 $0.00084 4.4s
filtered r2 INC-001: sig='PoolTimeout'          truth='PoolTimeout'        correct=True  attempts=1 tokens=  2,540 read=  2,528 $0.00057 4.5s
filtered r2 INC-002: sig='CacheMissStorm'       truth='CacheMissStorm'     correct=True  attempts=1 tokens=  2,687 read=  2,675 $0.00070 5.7s
filtered r2 INC-003: sig='TLS_CERT_EXPIRED'     truth='TLS_CERT_EXPIRED'   correct=True  attempts=1 tokens=  2,646 read=  2,634 $0.00061 4.7s
filtered r2 INC-004: sig='OOMKilled'            truth='OOMKilled'          correct=True  attempts=1 tokens=  2,656 read=  2,644 $0.00058 4.2s
filtered r2 INC-005: sig='RateLimitExceeded'    truth='RateLimitExceeded'  correct=True  attempts=1 tokens=  2,569 read=  2,557 $0.00043 3.9s
raw      r1 INC-001: sig='db-pool PoolTimeout: failed to acquire connection within 3000ms (active=4/4) surfacing as order-service 503 upstream PoolTimeout while creating order' truth='PoolTimeout'        correct=False attempts=1 tokens=147
raw      r1 INC-002: sig='db-pool PoolTimeout: connection acquire queue depth exceeds limit, rejecting new requests (with CacheMissStorm on db-primary pool)' truth='CacheMissStorm'     correct=False attempts=1 tokens=142,325 read=      0 $
raw      r1 INC-003: sig='TLS_CERT_EXPIRED: handshake failed host=gw.acquirer.example.net notAfter=2024-06-17T00:00:00Z' truth='TLS_CERT_EXPIRED'   correct=False attempts=1 tokens=136,350 read=      0 $0.08676 4.3s
raw      r1 INC-004: sig='OOMKilled: heap usage 1973MB exceeded container limit during session lookup, process terminated (preceded by session-cache heap pressure critical with eviction_count=0)' truth='OOMKilled'          correct=False at
raw      r1 INC-005: sig='RateLimitExceeded: provider response 429 on email send (retry_after=60s), surfaced as 503 upstream RateLimitExceeded' truth='RateLimitExceeded'  correct=False attempts=1 tokens=141,992 read=      0 $0.09158 6.6s
raw      r2 INC-001: sig='db-pool PoolTimeout: failed to acquire connection within 3000ms (active=4/4) upstream to order-service POST /v1/orders 503' truth='PoolTimeout'        correct=False attempts=1 tokens=147,036 read=147,024 $0.00857 
raw      r2 INC-002: sig='db-pool PoolTimeout: connection acquire queue depth exceeds limit, rejecting new requests (with CacheMissStorm: timed out waiting for connection from db-primary pool)' truth='CacheMissStorm'     correct=False atte
raw      r2 INC-003: sig='TLS_CERT_EXPIRED: handshake failed host=gw.acquirer.example.net notAfter=2024-06-17T00:00:00Z' truth='TLS_CERT_EXPIRED'   correct=False attempts=1 tokens=136,350 read=136,338 $0.00845 3.2s
raw      r2 INC-004: sig='OOMKilled: heap usage 1973MB exceeded container limit during session lookup, process terminated; session-cache UnboundedMap eviction_count=0 heap pressure critical' truth='OOMKilled'          correct=False attempt
raw      r2 INC-005: sig='RateLimitExceeded: provider response 429 / POST /v1/notifications/email returned 503 upstream RateLimitExceeded' truth='RateLimitExceeded'  correct=False attempts=1 tokens=141,992 read=141,980 $0.00990 6.0s
```
