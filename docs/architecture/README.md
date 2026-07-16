# Active architecture

All Rise Analytics runs as one Streamlit application. UI code calls the helpers
under `src/`, which read through the parameterized database layer in
`src/database.py`. Hosted reads use Turso's SQLite-compatible HTTP API; local
development uses `data/mlb.db`. Provider calls and expensive transforms retain
the existing Streamlit caches and shared helpers.

No active module imports the archived FastAPI, Next.js, PostgreSQL, Redis,
worker, Cloud Run, or Terraform implementation. That inactive design history is
retained in `archive/google-cloud/project/docs/architecture/`.
