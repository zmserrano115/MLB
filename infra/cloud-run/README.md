# Cloud Run infrastructure

Deployment manifests are intentionally deferred until service behavior and local images pass their phase gates. Future manifests are grouped under `services/`, `worker-pool/`, and `jobs/`; they must use environment placeholders and least-privilege service accounts.

