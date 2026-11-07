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

> python scripts/e5_validation_retry.py INC-001

```code
attempt 1: cache_write=2318 cache_read=0 input=12 -> 3 problem(s)
   line 1069: text mismatch
     cited:  '1x\tlast=2026-11-01T10:07:07.200\t2026-11-01T10:07:07.200 INFO  [config-loader] Applied config rev 7f3a91c: db.pool.max_connections changed 40 -> 4 (source=deploy-pipeline, actor=ci-bot)'
     actual: '2026-11-01T10:07:07.200 INFO  [config-loader] Applied config rev 7f3a91c: db.pool.max_connections changed 40 -> 4 (source=deploy-pipeline, actor=ci-bot)'
   line 1081: text mismatch
     cited:  '54x\tlast=2026-11-01T10:19:52.000\t2026-11-01T10:07:12.000 ERROR [order-service] POST /v1/orders failed with 503: upstream PoolTimeout while creating order cart_id=998'
     actual: '2026-11-01T10:07:12.000 ERROR [order-service] POST /v1/orders failed with 503: upstream PoolTimeout while creating order cart_id=998'
   line 1084: text mismatch
     cited:  '53x\tlast=2026-11-01T10:19:50.400\t2026-11-01T10:07:13.200 ERROR [db-pool] PoolTimeout count in last 60s=343 exceeds threshold 50'
     actual: '2026-11-01T10:07:13.200 ERROR [db-pool] PoolTimeout count in last 60s=343 exceeds threshold 50'
attempt 2: cache_write=0 cache_read=2318 input=1041 -> OK

final: signature='PoolTimeout: failed to acquire connection within 3000ms (db-pool, active=4/4, waiters high)' component='db-pool' severity=sev1 confidence=0.9
  line 1069: 2026-11-01T10:07:07.200 INFO  [config-loader] Applied config rev 7f3a91c: db.pool.max_conn
  line 1081: 2026-11-01T10:07:12.000 ERROR [order-service] POST /v1/orders failed with 503: upstream Po
  line 1084: 2026-11-01T10:07:13.200 ERROR [db-pool] PoolTimeout count in last 60s=343 exceeds threshol
```

> python scripts/e5_validation_retry.py INC-001 --fault

```code
attempt 1: cache_write=0 cache_read=2318 input=12 -> 4 problem(s)
   line 1070: text mismatch
     cited:  '1x\tlast=2026-11-01T10:07:07.200\t2026-11-01T10:07:07.200 INFO  [config-loader] Applied config rev 7f3a91c: db.pool.max_connections changed 40 -> 4 (source=deploy-pipeline, actor=ci-bot)'
     actual: '2026-11-01T10:07:07.600 WARN  [tls-monitor] certificate for internal-gateway expires in 41 days (renewal scheduled)'
   line 1081: text mismatch
     cited:  '54x\tlast=2026-11-01T10:19:52.000\t2026-11-01T10:07:12.000 ERROR [order-service] POST /v1/orders failed with 503: upstream PoolTimeout while creating order cart_id=998'
     actual: '2026-11-01T10:07:12.000 ERROR [order-service] POST /v1/orders failed with 503: upstream PoolTimeout while creating order cart_id=998'
   line 1084: text mismatch
     cited:  '53x\tlast=2026-11-01T10:19:50.400\t2026-11-01T10:07:13.200 ERROR [db-pool] PoolTimeout count in last 60s=343 exceeds threshold 50'
     actual: '2026-11-01T10:07:13.200 ERROR [db-pool] PoolTimeout count in last 60s=343 exceeds threshold 50'
   line 1089: text mismatch
     cited:  '50x\tlast=2026-11-01T10:19:43.200\t2026-11-01T10:07:15.200 ERROR [db-pool] PoolTimeout: failed to acquire connection within 3000ms (waiters=537, active=4/4)'
     actual: '2026-11-01T10:07:15.200 ERROR [db-pool] PoolTimeout: failed to acquire connection within 3000ms (waiters=537, active=4/4)'
attempt 2: cache_write=0 cache_read=2318 input=1287 -> OK

final: signature='PoolTimeout: failed to acquire connection within 3000ms (db-pool, active=4/4, waiters high)' component='db-pool' severity=sev1 confidence=0.9
  line 1069: 2026-11-01T10:07:07.200 INFO  [config-loader] Applied config rev 7f3a91c: db.pool.max_conn
  line 1081: 2026-11-01T10:07:12.000 ERROR [order-service] POST /v1/orders failed with 503: upstream Po
  line 1084: 2026-11-01T10:07:13.200 ERROR [db-pool] PoolTimeout count in last 60s=343 exceeds threshol
  line 1089: 2026-11-01T10:07:15.200 ERROR [db-pool] PoolTimeout: failed to acquire connection within 3
```
