# Phase 1 scaffold status

Status: implementation complete; Docker exit-gate verification pending.

## Objective and preservation boundary

Phase 1 adds the non-disruptive monorepo, packaging, dependency locks, local-service topology, and independently testable API/web/worker shells. Root `app.py`, `src/`, `components/`, data paths, and the current Streamlit launch command remain authoritative and were not moved.

## Implemented files

- Root Python and pnpm workspace configuration with `uv.lock` and `pnpm-lock.yaml`.
- FastAPI operations shell under `apps/api`.
- Next.js App Router shell under `apps/web`.
- Shared Python backend package under `packages/backend` with an empty Alembic baseline.
- Dramatiq worker shell under `services/worker`.
- Optional legacy Streamlit image, service Dockerfiles, `compose.yaml`, safe local environment example, infrastructure placeholders, and local runbook.

## Verification on 2026-07-11

- Legacy test suite: 85 passed.
- Phase 1 Python scaffold tests: 2 passed.
- Python compilation: passed.
- Ruff: passed.
- mypy strict mode: passed across 22 source files.
- Frontend ESLint: passed.
- Frontend TypeScript check: passed.
- Frontend Vitest: 1 passed.
- Next.js optimized production build: passed.
- Compose YAML and expected-service topology validation: passed.
- Legacy browser smoke: passed; the dashboard rendered with all eight navigation views and the games slate.
- Python and Node dependency locks: generated and verified.

## Pending exit gate

Docker is not installed on the audit workstation, so image builds and `docker compose up --build` have not been executed. Phase 2 must not begin until Docker is available and the API, web, worker, migration, PostgreSQL, Redis, and optional legacy services pass their container health checks.

