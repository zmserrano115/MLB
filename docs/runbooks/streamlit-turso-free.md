# Streamlit + Turso $0 runbook

## Decision and hard cost boundary

Use Streamlit Community Cloud for the existing app and the Turso Free plan for
the SQLite-compatible database. Do not deploy the GCP Terraform plan, Cloud
Run, Cloud SQL, Memorystore, or a continuously running worker.

Expected platform cost is **$0/month** while both accounts remain on their free
plans. Turso currently includes 5 GB storage, 500 million rows read per month,
and 10 million rows written per month with no card required. Queries are blocked
when a quota is exhausted instead of automatically becoming billable. Keep
overages disabled and do not select a paid plan. See the current
[Turso pricing](https://turso.tech/pricing) and
[usage behavior](https://docs.turso.tech/help/usage-and-billing) before any
future production change.

The current `data/mlb.db` is about 0.9 GB, so the initial database fits the
current 5 GB limit. Streamlit Community Cloud is free, but it still sleeps after
12 hours without traffic. Moving the database removes the roughly 0.9 GB
startup download and database memory pressure; it does not eliminate
Streamlit's hibernation screen. See Streamlit's current
[resource and hibernation limits](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).

## One-time Turso setup

These steps create external resources and must be run manually after reviewing
the free plan. The Turso CLI installation on Windows uses WSL.

1. Create a Turso Free account without adding a payment card or enabling
   overages.
2. Authenticate the CLI with `turso auth signup` or `turso auth login`.
3. Confirm the free plan, disable overages, and create the account's one free
   database group. If `turso group list` already shows a group, reuse its name
   instead of creating another one:

   ```bash
   turso plan show
   turso plan overages disable
   turso group list
   turso group create default --wait
   turso group list
   ```

   The Free plan supports one group. Creating a second group requires a paid
   plan, so the application database must use this existing `default` group.

4. Checkpoint the local SQLite database so the main file contains every WAL
   change:

   ```powershell
   python -c "import sqlite3; c=sqlite3.connect('data/mlb.db'); print(c.execute('PRAGMA journal_mode=WAL').fetchone()[0]); print(c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()); c.close()"
   ```

5. Import the existing file. Turso's `--from-file` path supports SQLite files
   up to 2 GB, so the current file is within the documented limit:

   ```bash
   turso db create all-rise --group default --from-file ./data/mlb.db --wait
   ```

6. Retrieve the database URL and create separate serving and refresh tokens:

   ```bash
   turso db show --url all-rise
   turso db tokens create all-rise --read-only --expiration never
   turso db tokens create all-rise --expiration never
   ```

The first token goes only to Streamlit. The second full-access token goes only
to the GitHub Actions refresh workflow. Turso documents the import command in
its [migration guide](https://docs.turso.tech/cloud/migrate-to-turso) and the
read-only flag in its
[token reference](https://docs.turso.tech/cli/db/tokens/create).

## Streamlit Community Cloud secrets

Set these in the app's Advanced settings. Do not commit either token.

```toml
TURSO_DATABASE_URL = "libsql://all-rise-ACCOUNT.turso.io"
TURSO_AUTH_TOKEN = "READ_ONLY_TOKEN"
TURSO_READ_ONLY = "1"
TURSO_DATA_VERSION = "initial-2026-07-15"
```

Remove `MLB_DB_URL` from the Streamlit secrets after the Turso smoke test. When
`TURSO_DATABASE_URL` is present, the app skips the local SQLite release
download. If Turso variables are absent, local SQLite remains the fallback.

The serving connection is read-only by default in code. Live contact history
still remains in the user's Streamlit session, but serving requests do not
write contact or bullpen cache rows to Turso.

## Nightly refresh secrets

Add these GitHub Actions repository secrets:

- `TURSO_DATABASE_URL`: the same database URL.
- `TURSO_WRITE_AUTH_TOKEN`: the full-access token, never the Streamlit token.

When `TURSO_DATABASE_URL` exists, `refresh-data.yml` updates Turso directly and
skips the large SQLite release download and upload. Completed games update only
the summary rows they touch. Full summary rebuilds and full-table count probes
are deliberately skipped because they would waste the free row-read and
row-write quotas.

## Acceptance and quota checks

Before changing the public app, verify:

1. Home, Games, Matchups, Players, Streaks, and one live or recorded game load.
2. The Streamlit logs contain no SQL-over-HTTP, missing-table, or authorization
   errors.
3. A manual `test_only` workflow succeeds, followed by one normal refresh.
4. Turso storage remains below 4 GB, monthly reads below 400 million, and
   monthly writes below 8 million. These are stop/review thresholds, not
   upgrade triggers.
5. Turso overages remain disabled and no payment method is added.

If a threshold is crossed, keep the free plan and investigate query scans or
cache behavior. Do not automatically upgrade. If a hard quota is reached, the
database may reject queries, but the guardrail keeps the bill at $0.

## Rollback

Remove the four `TURSO_*` Streamlit secrets and restore the existing
`MLB_DB_URL` release secret. The code will immediately return to the local
SQLite bootstrap path. Do not delete the SQLite release or the Turso database
until the free deployment has completed an observation period.
