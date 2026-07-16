# Phase 2 shared-domain status

Status: complete.

## Preservation boundary

The existing Streamlit application and all public `src.*` import paths remain authoritative compatibility surfaces. Pure calculations now live under `packages/backend/src/all_rise/domain`; provider calls, SQLite access, and HTML rendering remain in their legacy adapters.

## Extracted calculation families

- hitter matchup grading;
- pitcher matchup scoring;
- pitch-type and BvP calculations;
- projected bullpen availability and matchup weighting;
- weather normalization and run-environment adjustments;
- live-feed pitch/result normalization;
- historical and live streak calculations;
- recent-form series calculations;
- general stat numeric normalization.

## Compatibility evidence

- Full legacy and domain suite: 91 passed.
- Phase 1 scaffold suite: 2 passed.
- Golden characterization fixture suite: 6 passed.
- Ruff: passed.
- mypy: passed across 31 source files.
- Python compilation: passed.
- Legacy compatibility import smoke: passed when the backend workspace source path is present.
- Domain import-boundary test: passed; domain modules import no Streamlit, legacy `src`, provider HTTP, SQLAlchemy, or Alembic modules.

## Dependency and container exit gate

- `uv.lock` was refreshed and resolves NumPy and pandas for the backend workspace.
- API, worker, migration, and legacy Streamlit images rebuilt cleanly.
- PostgreSQL, Redis, API, and web health checks passed; Alembic exited successfully.
- Shared-domain imports passed inside the API and worker images.
- Existing `src.*` compatibility imports passed inside the legacy Streamlit image.
- API, web, and legacy HTTP smoke checks passed.
- The test stack was removed cleanly after verification with named volumes retained.
