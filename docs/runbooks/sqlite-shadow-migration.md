# SQLite-to-PostgreSQL shadow migration

This procedure is non-destructive to the SQLite source and refuses to load a non-empty PostgreSQL target.

## Preconditions

1. Stop legacy writers or copy the database after a WAL checkpoint.
2. Confirm the snapshot has no non-empty `mlb.db-wal` sibling.
3. Start PostgreSQL and apply Alembic head.

```powershell
docker compose up -d postgres
docker compose run --rm migrate
```

## Audit only

```powershell
docker compose run --rm --volume "${PWD}\data:/snapshot:ro" migrate `
  python -m all_rise.migration.sqlite_snapshot /snapshot/mlb.db `
  --database-url postgresql://unused --audit-only
```

Review `quick_check`, SHA-256, authoritative orphan counts, canonical IDs, row counts, ranges, and explicit ephemeral quarantine counts before loading.

## Load and reconcile

```powershell
docker compose run --rm --volume "${PWD}\data:/snapshot:ro" migrate `
  python -m all_rise.migration.sqlite_snapshot /snapshot/mlb.db `
  --database-url postgresql://all_rise:all_rise@postgres:5432/all_rise `
  --chunk-size 20000
```

The loader commits only after row-count, aggregate-total, range, source, and orphan validation succeeds. Any exception rolls back the generation.

## Independent validation

```powershell
docker compose run --rm --volume "${PWD}\data:/snapshot:ro" migrate `
  python -m all_rise.migration.sqlite_snapshot /snapshot/mlb.db `
  --database-url postgresql://all_rise:all_rise@postgres:5432/all_rise `
  --validate-only
```

Do not point production traffic at the shadow database until later phase gates approve an endpoint-by-endpoint cutover.
