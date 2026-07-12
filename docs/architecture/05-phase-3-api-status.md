# Phase 3 FastAPI and repository-contract status

Status: complete.

## Runtime boundary

- FastAPI now uses validated environment settings and a lifespan-managed operations service.
- Production configuration rejects SQLite and wildcard CORS origins.
- PostgreSQL and Redis clients are created at startup and disposed at shutdown; startup never runs migrations or refresh work.
- The SQLite operations adapter is development-only and opens its database in read-only mode.
- Repository protocols keep the HTTP layer independent from PostgreSQL and SQLite implementations.

## Operational API

- `GET /health` is dependency-free liveness.
- `GET /ready` verifies PostgreSQL reachability and the expected Alembic revision; Redis failure is reported as degraded without failing readiness.
- `GET /version` exposes only API version, build SHA, and schema revision.
- `GET /api/v1/data-status` is a typed, bounded read with a maximum limit of 100.
- `/healthz` and `/readyz` remain hidden compatibility aliases for local container health checks.

All public responses use typed `{data, meta}` envelopes. Failures use a stable `{error}` envelope without raw exception details. Middleware validates request IDs, emits structured request timing, limits declared body size, sets secure response headers, and enforces an environment-specific CORS allowlist. A rate-limit protocol is present for Redis enforcement in Phase 5.

## Contract and failure evidence

- API/config/repository tests: 10 passed.
- OpenAPI snapshot covers the four public paths, response codes, schemas, and the data-status limit bounds.
- Failure coverage includes unavailable PostgreSQL, degraded Redis, validation errors, unexpected repository errors, oversized requests, denied CORS origins, production SQLite rejection, wildcard CORS rejection, and read-only SQLite compatibility.
- Ruff passed for all Phase 3 and backend source files.
- Strict mypy passed across 36 API/backend source files.
- Full legacy regression suite passed separately: 91 passed.

## Container exit gate

- The API Docker image built successfully with the backend workspace package and Redis client.
- Compose started PostgreSQL, Redis, the Alembic migration job, and the API from the built image.
- Container health was healthy; `/health`, `/ready`, `/version`, and `/api/v1/data-status` all returned successfully.
- Readiness reported PostgreSQL `ready`, Redis `ready`, and schema revision `0001_scaffold`.
- The stack was removed cleanly after verification with named volumes retained.

The existing Streamlit application remains the user-serving product. These endpoints are shadow-only until later migration phases complete.
