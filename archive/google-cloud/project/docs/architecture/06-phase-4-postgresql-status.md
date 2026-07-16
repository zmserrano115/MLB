# Phase 4 PostgreSQL shadow-migration status

Status: complete.

## Schema and migration boundary

- Alembic revision `0002_normalized_shadow_schema` creates 14 normalized tables for teams, players, canonical games, BvP and pitcher facts/summaries, live contacts, bullpen generations, refresh history, checkpoints, source status, and source artifacts.
- Provider IDs use `BIGINT`; public game identity remains a canonical string. The legacy signed 63-bit game key is retained only as an audited migration key.
- Dates use `DATE`, operational timestamps use timezone-aware timestamps, residual live payloads use bounded JSONB, and fact constraints/indexes match the documented access patterns.
- Alembic metadata now comes from the SQLAlchemy declarative model.
- Production readiness expects schema revision `0002_normalized_shadow_schema`.

## Immutable snapshot loader

- The loader opens SQLite with `mode=ro`, `immutable=1`, and `query_only=ON`.
- It rejects a missing snapshot, a non-empty WAL, failed `quick_check`, missing required tables, noncanonical game IDs, and authoritative game/player orphans.
- SHA-256, byte size, table/index inventory, source/date ranges, row counts, aggregate fact totals, quarantine counts, and source identity are recorded in `source_artifacts`.
- Facts stream through bounded SQLite `fetchmany()` and PostgreSQL `COPY`; the complete load and reconciliation commit atomically.
- Derived BvP and pitcher summaries are rebuilt from normalized facts rather than copied from legacy summary tables.
- A non-empty target is rejected, preventing destructive reloads.

## Snapshot evidence

- Snapshot size: 900,177,920 bytes.
- Snapshot SHA-256: `446fad4603b5885cdaa27e34208fead0e49fddd0c035f305dc6070dfa6cd5142`.
- SQLite `quick_check`: `ok`.
- Date range: 2005-04-03 through 2026-06-22.
- Sources: 1,169 StatsAPI games and 49,486 Retrosheet games.
- Authoritative source orphans and noncanonical IDs: zero.
- Quarantined ephemeral records: 506 live-contact rows across 11 games and 9 bullpen rows for one game. Their game records are absent from the snapshot, so the migration records them in artifact inventory instead of inventing normalized games.

## Reconciliation evidence

| Dataset | PostgreSQL rows |
|---|---:|
| Games | 50,655 |
| Players | 6,304 |
| BvP game facts | 2,313,456 |
| Rebuilt BvP summaries | 1,011,578 |
| Pitcher game facts | 415,220 |
| Rebuilt pitcher-season summaries | 16,225 |
| Refresh runs | 51 |

- Independent validation matched all row counts, 12 aggregate fact totals, source counts, date/season ranges, and zero target orphans.
- Deterministic samples matched 25 BvP summaries and 25 pitcher-season summaries exactly on integer totals.
- BvP and pitcher access-pattern probes used their intended indexes with measured execution times of 0.065 ms and 0.139 ms in the local shadow database.

## Recovery and serving evidence

- Blank-to-head migration passed.
- Downgrade to `0001_scaffold` removed all 14 shadow tables; re-upgrade restored head.
- A compressed `pg_dump` was restored into a temporary database. Schema revision, 50,655 games, 2,313,456 BvP facts, 415,220 pitcher facts, and the source SHA-256 matched; the temporary database was then removed.
- The rebuilt API reported PostgreSQL and Redis ready at `0002_normalized_shadow_schema`.
- `/api/v1/data-status` returned `legacy-sqlite`, watermark `2026-06-22`, and freshness `snapshot`.

The PostgreSQL database remains shadow-only. Streamlit still serves users from the unchanged legacy SQLite path; no serving cutover occurred.
