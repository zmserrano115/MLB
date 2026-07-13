# Architecture migration dossier

Status: audit and Phases 1-6 complete; Phase 7 is in progress. The shared
Next.js shell, Methodology, and persisted Games/Weather preview are complete.
Legacy routes remain available for full live/current provider-backed coverage
and for analytical pages not yet migrated.

This directory is the approval gate for the All Rise Analytics strangler migration. The current Streamlit application remains the working product and is intentionally unchanged.

## Deliverables

| Required deliverable | Location |
|---|---|
| Repository audit and current file structure | [01-current-state-audit.md](01-current-state-audit.md) |
| Current architecture diagram | [01-current-state-audit.md](01-current-state-audit.md#current-architecture) |
| Security, performance, deployment, and scalability risks | [01-current-state-audit.md](01-current-state-audit.md#prioritized-risk-register) |
| Target architecture diagram | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#target-architecture) |
| Proposed monorepo structure | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#proposed-folder-structure) |
| Migration phases and approval gates | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#phased-strangler-plan) |
| Files to move, retain, and deprecate | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#file-disposition-plan) |
| PostgreSQL migration and retention plan | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#postgresql-migration-plan) |
| FastAPI endpoint plan | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#fastapi-contract-plan) |
| Redis cache plan | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#redis-plan) |
| Background job plan | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#background-work-plan) |
| Next.js migration plan | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#nextjs-migration-plan) |
| Live-game architecture | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#live-game-plan) |
| Local development and Cloud Run deployment | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#local-development-plan) |
| Test and acceptance plan | [02-target-architecture-and-migration-plan.md](02-target-architecture-and-migration-plan.md#test-plan) |
| Phase 1 implementation status | [03-phase-1-scaffold-status.md](03-phase-1-scaffold-status.md) |
| Phase 2 implementation status | [04-phase-2-domain-status.md](04-phase-2-domain-status.md) |
| Phase 3 implementation status | [05-phase-3-api-status.md](05-phase-3-api-status.md) |
| Phase 4 implementation status | [06-phase-4-postgresql-status.md](06-phase-4-postgresql-status.md) |
| Phase 5 implementation status | [07-phase-5-redis-status.md](07-phase-5-redis-status.md) |
| Phase 6 implementation status | [08-phase-6-workers-status.md](08-phase-6-workers-status.md) |
| Phase 7 implementation status | [09-phase-7-nextjs-status.md](09-phase-7-nextjs-status.md) |

## Audit-stage verification

- `python -m compileall` equivalent using the repository virtual environment: passed.
- `pytest -q`: 85 passed in 15.28 seconds.
- Local browser smoke check: the eight legacy views rendered; navigating to Matchups produced `?view=Matchups&matchup_table=Hitter+vs+Pitcher`.
- SQLite `PRAGMA quick_check`: `ok`.
- Git worktree before documentation: clean on `main`.
- Lint and static type checks: not available because the repository has no linter, type-checker, or configuration for either.
- Docker build: not available because the repository has no Dockerfile or Compose configuration yet.

No refresh, Statcast download, backfill, database rebuild, deployment, commit, push, merge, or pull request was performed during the audit.
