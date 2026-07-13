# Background jobs runbook

## Safety model

PostgreSQL is the status authority. Redis only delivers actor messages. GCS/local artifacts are
immutable, and a generation becomes visible only after its quality gate and database transaction
succeed. Schedule rows, weather snapshots, their checkpoint, and their serving watermark commit
atomically. Leave `JOB_SOURCE_OWNERSHIP=shadow`; activate a proven adapter with the narrow
`JOB_ACTIVE_TASKS` allowlist only after source ownership is explicitly approved.

## Run a finite shadow task locally

Start dependencies and migrate first:

```powershell
docker compose up -d postgres redis
docker compose run --rm migrate
```

Pass JSON through the environment to avoid Windows shell quote rewriting:

```powershell
$env:TASK_PAYLOAD='{"date":"2026-07-13","source_version":"manual-v1"}'
docker compose run --rm -e TASK_PAYLOAD worker python -m all_rise_worker.commands.run_task refresh_schedule --scope 2026-07-13
```

The command prints `succeeded`, `duplicate`, `in_progress`, `retry`, or `dead_letter`. Repeating
the same task/payload derives the same idempotency key and must not execute it again.

## Run a controlled active schedule/weather rehearsal

The two provider adapters are registered but remain dormant by default. Activate only the task
being rehearsed; do not set global ownership to `active`:

```powershell
$env:TASK_PAYLOAD='{"date":"2026-07-17","source_version":"schedule-20260717-v1"}'
docker compose run --rm -e JOB_ACTIVE_TASKS=refresh_schedule -e TASK_PAYLOAD worker python -m all_rise_worker.commands.run_task refresh_schedule --scope 2026-07-17

$env:TASK_PAYLOAD='{"start":"2026-07-17","end":"2026-07-17","source_version":"weather-20260717-v1"}'
docker compose run --rm -e JOB_ACTIVE_TASKS=refresh_weather -e TASK_PAYLOAD worker python -m all_rise_worker.commands.run_task refresh_weather --scope 2026-07-17
```

Run schedule first because weather resolves only persisted games and venues. Weather windows are
bounded to eight days. Use a new source version only for a genuinely new provider observation;
an identical payload must return `duplicate`.

## Inspect status

```sql
SELECT id, task_name, source, scope, status, attempt, max_attempts,
       heartbeat_at, next_retry_at, completed_at, dead_lettered_at, published_at,
       error_code, message
FROM refresh_runs
ORDER BY id DESC
LIMIT 50;

SELECT run_id, item_key, status, attempt, error_code, message
FROM refresh_run_items
WHERE run_id = :run_id
ORDER BY id;
```

For shadow work, `published_at` must remain null. Check `source_artifacts` for URI, SHA-256,
size, generation, and inventory.

## Recover stale work

Run the recovery command on a five-minute Cloud Scheduler cadence (or manually):

```powershell
docker compose run --rm worker python -m all_rise_worker.commands.recover_stale
```

It marks expired running leases as retryable or dead-lettered after their last allowed attempt.
It does not execute the task itself; the scheduler/actor redelivery performs the next claim.

## Dead letters

1. Inspect the run and all item errors.
2. Verify the upstream version/artifact and fix the provider or normalization fault.
3. Use a new idempotency key only when the source version, scope, or implementation genuinely
   changed. Never edit a successful key or delete history merely to force a replay.
4. Confirm the new run passes validation before changing source freshness or cache versions.

## Production cutover checklist

- Register and test the real adapter for the specific task. Schedule and weather are registered.
- Compare several shadow generations with the legacy owner, including late corrections.
- Validate row counts, identities, ranges, checksums, per-item errors, and derived aggregates.
- Confirm IAM: scheduler invoker only, worker Cloud SQL client, bucket object creator/viewer as
  needed, Secret Manager accessor only for named secrets.
- Assign exactly one writer for the source and record rollback ownership.
- Add only that task to `JOB_ACTIVE_TASKS`; do not globally disable legacy workflows. The Cloud
  Run templates expose separate schedule and weather allowlist placeholders.
- Observe freshness, dead letters, provider throttling, database load, and artifact growth.
