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
raw lines     : 50,000  chars: 4,527,010
filtered rows : 9  chars: 1,363
reduction     : 3321x
trigger line 19857 kept     : True
first error 19863 kept  : True
--- filtered view ---
6    2564x    last=2026-11-01T15:33:17.600    2026-11-01T10:00:02.000 WARN  [fraud-scorer] model latency p95 elevated to 210ms (threshold 250ms), within bounds
7    2539x    last=2026-11-01T15:33:18.000    2026-11-01T10:00:02.400 WARN  [tls-monitor] certificate for internal-gateway expires in 41 days (renewal scheduled)
17    2516x    last=2026-11-01T15:33:16.000    2026-11-01T10:00:06.400 WARN  [logging-pipeline] log buffer 80% full, flushing
19857    1x    last=2026-11-01T12:12:22.400    2026-11-01T12:12:22.400 INFO  [config-loader] Applied config rev 7f3a91c: db.pool.max_connections changed 40 -> 4 (source=deploy-pipeline, actor=ci-bot)
19863    903x    last=2026-11-01T15:33:16.800    2026-11-01T12:12:24.800 ERROR [checkout-api] request aborted after PoolTimeout on payment-intent lookup, trace_id=189
19865    923x    last=2026-11-01T15:33:17.200    2026-11-01T12:12:25.600 ERROR [order-service] POST /v1/orders failed with 503: upstream PoolTimeout while creating order cart_id=380
19868    918x    last=2026-11-01T15:33:12.400    2026-11-01T12:12:26.800 ERROR [db-pool] PoolTimeout: failed to acquire connection within 3000ms (waiters=448, active=4/4)
19919    876x    last=2026-11-01T15:33:09.200    2026-11-01T12:12:47.200 ERROR [db-pool] PoolTimeout count in last 60s=806 exceeds threshold 50
19950    917x    last=2026-11-01T15:33:04.800    2026-11-01T12:12:59.600 WARN  [db-pool] pool saturation 100% active=4/4 waiters=740
```
