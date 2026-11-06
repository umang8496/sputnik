# Review Scenarios Result

```code
=== INC-001  checkout  sev2
alert      : PAGE: checkout-api p99_latency_ms > 2500 for 5m (SLO breach), error rate 14% on POST /v1/orders, region us-east-1
root_cause : A config deploy at 14:02 UTC changed checkout DB pool max_connections from 40 to 4, starving request threads of connections and causing PoolTimeout errors under normal traffic.
trigger    : line 1069: [INFO] Applied config rev 7f3a91c: db.pool.max_connections changed 40 -> 4 (source=deploy-pipeline, actor=ci-bot)
signature  : PoolTimeout
  error  ok  [ERROR] [db-pool] PoolTimeout: failed to acquire connection within 3000ms (waiters={n}, active=4/4)
  error  ok  [ERROR] [order-service] POST /v1/orders failed with 503: upstream PoolTimeout while creating order cart_id={n}
  error  ok  [ERROR] [checkout-api] request aborted after PoolTimeout on payment-intent lookup, trace_id={n}
  error  ok  [ERROR] [db-pool] PoolTimeout count in last 60s={n} exceeds threshold 50
  error  MISSING-SIG [WARN] [db-pool] pool saturation 100% active=4/4 waiters={n}
  herring     [WARN] [tls-monitor] certificate for internal-gateway expires in 41 days (renewal scheduled)
  herring     [WARN] [fraud-scorer] model latency p95 elevated to 210ms (threshold 250ms), within bounds
  herring     [WARN] [logging-pipeline] log buffer 80% full, flushing
metric     : p99_latency_ms 320.0 -> 4800.0
FLAGS      : signature shared with another incident

=== INC-002  search  sev2
alert      : [SEV2] search-api p99_latency_ms > 2000 for 5m; db-primary connections saturated (pool util 100%). On-call: search-oncall
root_cause : A config deploy to search-api set SEARCH_RESULT_CACHE_TTL_SECONDS from 300 to 0, so every search result cache entry expired immediately and all queries fell through to the database, causing a cache stampede on db-primary.
trigger    : line 1490: [INFO] config reloaded from deploy rev 7f3a9c2: SEARCH_RESULT_CACHE_TTL_SECONDS 300 -> 0
signature  : PoolTimeout
  error  ok  [ERROR] [db-pool] PoolTimeout: timed out waiting {n}ms for connection from db-primary pool (active=50/50, waiting=212)
  error  ok  [ERROR] [search-handler] request failed: PoolTimeout acquiring db connection for query_hash=search:q:{n}
  error  MISSING-SIG [WARN] [cache-client] cache miss ratio 99.{n}% over last 60s; ttl_seconds=0 on result cache
  error  ok  [ERROR] [search-handler] PoolTimeout after retry budget exhausted, returning HTTP 503 to client
  error  ok  [ERROR] [db-pool] PoolTimeout: connection acquire queue depth {n} exceeds limit, rejecting new requests
  herring     [WARN] [tls-monitor] certificate for search-admin.internal expires in 41 days
  herring     [WARN] [db-replica] replication lag 4{n}ms on replica-2, within threshold
  herring     [WARN] [disk-monitor] log volume /var/log 78% used on search-indexer-{n}
  herring     [WARN] [rate-limiter] client burst above soft limit for api key {n}, throttling applied
  herring     [WARN] [gc-monitor] GC pause {n}ms on search-api-{n}, heap 71% after collection
metric     : p99_latency_ms 180.0 -> 4200.0
FLAGS      : signature shared with another incident

=== INC-003  payments  sev1
alert      : CRITICAL: payments-api card authorization success rate below 90% for 5m (acquirer-gw upstream errors)
root_cause : Deploy payments-api 2024.06.17-2 pinned the acquirer-gw truststore to acquirer-ca-2023.pem, whose leaf certificate expired on 2024-06-17, so every TLS handshake to the acquirer fails.
trigger    : line 1122: [INFO] truststore reloaded: upstream=acquirer-gw path=/etc/payments/trust/acquirer-ca-2023.pem pinned=true release=2024.06.17-2
signature  : TLS_CERT_EXPIRED
  error  ok  [ERROR] [acquirer-gw-client] TLS_CERT_EXPIRED: handshake failed host=gw.acquirer.example.net notAfter=2024-06-17T00:00:00Z
  error  ok  [ERROR] [auth-worker] authorization failed txn_id=tx-{n} reason=upstream TLS_CERT_EXPIRED
  error  ok  [ERROR] [acquirer-gw-client] TLS_CERT_EXPIRED: retry {n}/3 exhausted host=gw.acquirer.example.net
  error  ok  [ERROR] [checkout-api] payment declined to client code=503 cause=TLS_CERT_EXPIRED upstream=acquirer-gw
  error  ok  [ERROR] [auth-worker] circuit breaker OPEN upstream=acquirer-gw after TLS_CERT_EXPIRED failures={n}
  herring     [WARN] [redis-cache] slow command GET took {n}ms
  herring     [WARN] [ledger-writer] disk usage 81% on /var/lib/ledger
  herring     [WARN] [payments-api] deprecated header X-Legacy-Client used by {n} requests
  herring     [WARN] [acquirer-gw-client] slow response from gw.backup.example.net latency_ms={n}
metric     : authorization_success_rate_pct 99.2 -> 41.7
FLAGS      : none

=== INC-004  auth  sev1
alert      : CRITICAL: auth-service pods restarting repeatedly (OOMKilled), p99 latency elevated, login success rate dropping in prod-us-east-1
root_cause : Release 3.14.0 changed the session cache from a bounded LRU with a 15-minute TTL to an unbounded HashMap keyed by token, so session entries are never evicted and heap grows until the container hits its memory limit and is OOMK
trigger    : line 1121: [INFO] deploy applied: session-cache backend switched to UnboundedMap (eviction_policy=none, max_entries=unlimited) in release 3.14.0
signature  : OOMKilled
  error  ok  [ERROR] [kubelet] Container auth-api in pod auth-api-7d9f6c5b8-{n} terminated: reason=OOMKilled exitCode=137 memoryLimit=2Gi
  error  ok  [ERROR] [auth-api] OOMKilled: heap usage 1973MB exceeded container limit during session lookup, process terminated
  error  MISSING-SIG [ERROR] [session-cache] cache size 48213{n} entries, eviction_count=0 since process start, heap pressure critical
  error  ok  [ERROR] [liveness-probe] Liveness probe failed for auth-api-7d9f6c5b8-{n}, restarting container after OOMKilled event
  error  ok  [ERROR] [auth-api] OOMKilled restart count 5 within 30m for deployment auth-api, crashloop backoff engaged
  herring     [WARN] [db-pool] connection acquire took 310ms on replica-2, above soft threshold 250ms
  herring     [WARN] [tls-certs] certificate for auth.internal.example.com expires in 27 days, renewal job scheduled
  herring     [WARN] [log-shipper] buffer 80 percent full, flushing to collector
  herring     [WARN] [node-exporter] disk usage on /var/lib/containers at 71 percent
metric     : p99_latency_ms 120.0 -> 2400.0
FLAGS      : none

=== INC-005  notifications  sev2
alert      : CRITICAL: notifications-svc email delivery failure rate > 25% for 10m (provider HTTP 429 RateLimitExceeded)
root_cause : Config change CFG-7741 lowered the outbound rate limit for the email provider from 600 to 60 requests per minute, so requests exceed the provider quota and receive 429 responses.
trigger    : line 1319: [INFO] applied config change CFG-7741: email_provider.rate_limit_rpm 600 -> 60
signature  : RateLimitExceeded
  error  ok  [ERROR] [email-sender] provider response 429 RateLimitExceeded for message_id=msg_{n}, retry_after=60s
  error  ok  [ERROR] [email-sender] delivery failed for message_id=msg_{n} after 3 attempts: RateLimitExceeded
  error  ok  [WARN] [retry-queue] retry queue depth {n} exceeds threshold 5000, RateLimitExceeded backlog growing
  error  ok  [ERROR] [email-sender] batch digest job aborted: RateLimitExceeded from upstream provider
  error  ok  [ERROR] [api-gateway] POST /v1/notifications/email returned 503 upstream RateLimitExceeded
  herring     [WARN] [db-pool] connection pool utilization at 78% for notifications_primary
  herring     [WARN] [tls-monitor] certificate for sms-webhook.internal expires in 29 days
  herring     [WARN] [api-gateway] slow response GET /v1/preferences took {n}ms
  herring     [WARN] [queue-consumer] consumer lag on topic notif-events partition {n} is {n} messages
metric     : email_delivery_success_rate 99.2 -> 41.5
FLAGS      : none
```
