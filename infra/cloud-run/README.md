# Cloud Run infrastructure

Phase 6 adds checked-in templates for the Dramatiq worker pool and finite Cloud Run Jobs.
They retain environment placeholders so project IDs, images, service accounts, Cloud SQL
instances, and artifact buckets are supplied by the deployment environment rather than source.

The templates deliberately use `JOB_SOURCE_OWNERSHIP=shadow`. Cloud Scheduler should invoke
the finite jobs through an authenticated Run API call. Platform retries are disabled for data
jobs because retry/dead-letter state is bounded and recorded in PostgreSQL; the stale-recovery
job is the only manifest with one platform retry.

Do not change ownership to `active` until the corresponding provider adapter is registered and
shadow output has repeatedly matched the legacy workflow. The runtime fails closed if active
ownership is requested without an adapter.
