# Streamlit and Turso deployment

Deploy `app.py` as the Streamlit entry point and install `requirements.txt`.
Configure `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `TURSO_READ_ONLY=true`, and
optionally `TURSO_DATA_VERSION` as server-side secrets. Do not render or forward
these values to browser components.

The active application does not require Google Cloud credentials, PostgreSQL,
Redis, a worker process, Node.js, or Terraform.
