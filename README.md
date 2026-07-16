# All Rise Analytics

All Rise Analytics is a Streamlit MLB research application backed by Turso in
hosted environments and the compatible local SQLite snapshot during development.

## Active architecture

- `app.py` renders the Streamlit application.
- `src/` contains data access, MLB provider clients, calculations, and UI helpers.
- Turso is configured only through server-side environment variables.
- `.github/workflows/refresh-data.yml` and `refresh-weather.yml` maintain the
  application data artifacts.

The inactive Google Cloud migration work is preserved under
`archive/google-cloud/`. Nothing in that directory is imported, installed, or
executed by the active application.

## Local development

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
streamlit run app.py
```

Without Turso variables, the application reads `data/mlb.db`. To use Turso, set
`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`; keep `TURSO_READ_ONLY=true` for the
serving application.

Run checks with:

```powershell
pytest
ruff check app.py src tests
```
