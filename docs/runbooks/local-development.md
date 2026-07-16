# Local development

1. Create and activate a Python virtual environment.
2. Install `requirements-dev.txt`.
3. Run `streamlit run app.py`.
4. Run `pytest` before committing changes.

The local database defaults to `data/mlb.db`. Turso can be enabled with
`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. The serving process should keep
`TURSO_READ_ONLY=true`.
