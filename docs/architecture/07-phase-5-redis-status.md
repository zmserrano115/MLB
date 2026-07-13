# Phase 5 Redis cache and resilience status

Status: complete.

## Shared cache contract

- Redis cache traffic uses `REDIS_CACHE_URL`, independently configurable from the broker/fallback Redis URL.
- Keys are composed from validated namespaces, resource identifiers, and a data version derived from `data_source_status`; file modification time is never used.
- JSON envelopes carry an explicit serialization schema, storage time, negative-entry marker, and bounded TTL.
- Negative results use a separate short TTL so they cannot hide upstream recovery.
- A token-owned `SET NX PX` lease and compare/delete Lua release prevent cache stampedes.
- Cache corruption and serialization drift fall back safely to PostgreSQL.
- Redis connection, read, write, and lease-release failures fail open for ordinary reads.
- A shared five-second circuit breaker prevents the cache and rate limiter from repeating connection delays during an outage.
- Process-local metrics record hits, misses, negative hits, writes, observed age, serialization failures, lock waits/timeouts, degraded fallbacks, and lease-release failures. They are ready for a Cloud Monitoring exporter in the deployment phase.

## Rate limiting

- Public `/api/` routes use a Redis-backed fixed-window limiter with hashed client/route keys.
- Limits and windows are environment configuration.
- Denials return a stable `429` error envelope, `Retry-After`, and remaining-budget header.
- Redis failure fails open and marks the response `X-Rate-Limit-Status: degraded`; it never turns a cache outage into an API outage.
- Liveness, readiness, and version routes remain outside public API rate limits.

## Automated evidence

- Focused cache/API suite covers version separation, TTL expiry, short negative TTL, hit/miss metrics, corrupt JSON, structural schema drift, Redis-down fallback, stampede concurrency, two service instances sharing a cache, rate decisions, safe 429 middleware, dedicated endpoint configuration, and invalid boolean configuration.
- Strict mypy and Ruff pass across the API/backend cache implementation.
- Existing OpenAPI and safe-error contracts remain unchanged apart from non-sensitive cache/rate response headers.

## Container evidence

- The Phase 5 API image built successfully against the retained Phase 4 PostgreSQL volume.
- After deleting only the test cache key, API instance one returned `X-Cache-Status: miss`; a separate API container's immediate first request returned `X-Cache-Status: hit` from the same Redis key.
- With Redis stopped, data status returned `200` from PostgreSQL with `X-Cache-Status: degraded` and `X-Rate-Limit-Status: degraded`; readiness reported PostgreSQL ready, Redis degraded, and overall ready.
- With Redis DNS unavailable locally, the first request detected the outage in 4.025 seconds and the shared open circuit reduced the next request to 0.024 seconds. Production uses a stable Memorystore address plus a 250 ms socket timeout and zero client retries.
- With Redis restored and a two-request test policy, the API returned `200`, `200`, then `429` with `Retry-After: 60`.

Redis remains an optimization and coordination layer, never the source of truth. The Streamlit application and its SQLite read path remain unchanged.
