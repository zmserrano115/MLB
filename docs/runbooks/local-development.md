# Local development

1. Copy `.env.example` to `.env` and adjust only local values.
2. Run `docker compose up --build` for PostgreSQL, Redis, the migration baseline, API, worker, and web shell.
3. Run `docker compose --profile legacy up --build` to include the existing Streamlit application.

The root `app.py`, legacy `src/`, and `components/` remain available as the
rollback target through the Phase 9 canary and Phase 10 retirement approval.
