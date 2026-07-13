# Phase 6 worker and job status

Status: implementation complete; production source ownership remains in shadow observation.

## Durable execution authority

- Alembic revision `0003_durable_job_execution` adds idempotency keys, task identity,
  attempts, heartbeats, retry/dead-letter timestamps, input/result payloads, and publication
  state to `refresh_runs`.
- `refresh_run_items` records bounded per-game/team/key outcomes without allowing one bad item
  to erase peer results.
- PostgreSQL claims are serialized by the unique idempotency key and row locks. A fresh running
  lease rejects concurrent duplicate work; stale work can be recovered; successful work is a
  permanent duplicate hit.
- Attempts use bounded exponential backoff with deterministic jitter. Retry exhaustion and
  non-retryable/quality failures enter `dead_letter`.
- A serving watermark and source status are updated in the same transaction as successful task
  completion. Failed quality gates never publish.

## Worker, command, and artifact boundary

- Dramatiq actors are thin delivery adapters over the shared executor. Redis is not queried for
  durable status and result middleware is intentionally unnecessary.
- The same executor is available through `python -m all_rise_worker.commands.run_task` for
  finite Cloud Run Jobs. `recover_stale` provides scheduled crash recovery.
- Local/Compose artifacts use immutable create-only files on a named volume. GCS uploads use
  `if_generation_match=0`, CRC32C transport verification, and SHA-256 metadata. An identical
  replay is accepted; conflicting content at the same object name is rejected.
- The 17-task architecture inventory is represented in the worker catalog. Provider-specific
  adapters can be registered by task name.

## Source ownership safety

`JOB_SOURCE_OWNERSHIP` defaults to `shadow`. Shadow tasks validate their required scope, write
an immutable execution receipt, and never advance a serving watermark. Requesting `active`
ownership without a registered provider adapter fails the task's quality gate. The existing
GitHub refresh workflows therefore remain the source owners until repeated shadow equivalence
is approved; Phase 6 does not introduce a dual writer.

`JOB_ACTIVE_TASKS` is a per-task allowlist for staged ownership. This avoids turning every
worker task active when only one source adapter has completed its cutover gate.

The Statcast support library now has explicit inclusive window planning, rolling correction
windows, stable pitch identity validation, and latest-observation correction merging. Results
are deterministic across one large window or multiple chunks. Generic source-record validation
reports missing required fields and duplicate provider identities before publication.

## Cloud Run templates

The infrastructure directory contains environment-neutral templates for:

- the Dramatiq worker pool;
- nightly schedule refresh;
- Statcast correction-window refresh; and
- stale-task recovery.

Data jobs set platform retries to zero because PostgreSQL owns bounded attempts. Templates use
least-privilege service-account placeholders, Secret Manager references, Cloud SQL attachment,
GCS, and shadow ownership.

## Verification on 2026-07-13

- Targeted Ruff: passed.
- Strict mypy for the Phase 6 backend/worker source: passed.
- Full locked-environment suite: 129 passed. Phase 4-6 focused tests: 28 passed.
- Duplicate, crash recovery, retry exhaustion, partial quality failure, immutable overwrite,
  source validation, canonical key, and multi-window Statcast equivalence tests: passed.
- Migration `0002 -> 0003 -> 0002 -> 0003`: passed against the retained PostgreSQL volume.
- Existing normalized games after migration cycle: 50,655; legacy refresh rows: 51.
- Worker and API images: built successfully.
- Direct container delivery: first execution `succeeded`, second execution `duplicate`, one
  item record, no shadow publication.
- Redis-delivered Dramatiq execution: `succeeded` at attempt 1 while API `/ready` returned 200
  with PostgreSQL, Redis, and schema `0003_durable_job_execution` ready.

Phase 7 subsequently registered real schedule and weather adapters, while retaining this phase's
shadow default and per-task allowlist gate. The provider ownership flip remains an operational
cutover decision, not an implementation default. No Google Cloud resource was created and no
legacy workflow was disabled.
