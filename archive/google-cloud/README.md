# Inactive Google Cloud migration archive

This directory preserves the stopped Phase 1–9 migration toward FastAPI,
Next.js, PostgreSQL, Redis, workers, Cloud Run, and Terraform. It is retained
only for possible future review.

The active Streamlit application does not import this directory, dependency
files do not install it, and active workflows do not execute it. Do not run its
deployment instructions or infrastructure commands without a separate,
explicit decision to resume the migration.

- `project/` preserves repository files at their former relative paths.
- `tooling/` preserves local SDKs, virtual environments, and Node tooling that
  were installed for the migration.
