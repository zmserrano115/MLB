# Redis cache and rate-limit operations

## Configuration

| Variable | Purpose | Local default |
|---|---|---|
| `REDIS_CACHE_URL` | Shared cache and rate-limit endpoint | `redis://redis:6379/0` |
| `CACHE_ENABLED` | Bypass shared cache when false | `true` |
| `CACHE_DEFAULT_TTL_SECONDS` | Default positive TTL | `30` |
| `CACHE_NEGATIVE_TTL_SECONDS` | Missing-result TTL | `5` |
| `CACHE_LEASE_TTL_MS` | Stampede lease | `5000` |
| `REDIS_TIMEOUT_MS` | Fail-open connect/read timeout with retries disabled | `250` |
| `RATE_LIMIT_ENABLED` | Enable public API limiting | `true` |
| `RATE_LIMIT_REQUESTS` | Requests per fixed window | `120` |
| `RATE_LIMIT_WINDOW_SECONDS` | Window length | `60` |

Production should use a dedicated Memorystore cache endpoint rather than sharing the queue/broker instance. Prefer Direct VPC egress when deploying Cloud Run.

## Expected behavior

- `X-Cache-Status: hit` means the response data came from the shared versioned cache.
- `miss` means this instance loaded PostgreSQL and populated Redis.
- `degraded` means Redis was unavailable or cached data failed validation; PostgreSQL served the request.
- `X-Rate-Limit-Status: degraded` means rate enforcement failed open because Redis was unavailable.
- `429` responses include `Retry-After` and a stable safe error body.
- After the first Redis connection failure, a shared five-second circuit immediately bypasses repeated cache/rate attempts and lets PostgreSQL serve ordinary reads.

## Outage check

Temporarily stopping local Redis must not make the API unavailable:

```powershell
docker compose stop redis
curl.exe -i http://localhost:8000/api/v1/data-status
curl.exe -i http://localhost:8000/ready
docker compose start redis
```

Expected: data status is `200` with degraded cache/rate headers; readiness is `200` with `cache_status=degraded`.

Never use Redis key deletion as authoritative data invalidation. Publish a new data version after a successful PostgreSQL commit and allow old versioned keys to expire.
