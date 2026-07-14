# Phase 9.1 GCP foundation status

Prepared: 2026-07-13

## Implemented and locally verified

- Added a parameterized, remote-state Terraform root for all required project APIs,
  Direct VPC networking, private service access, Cloud SQL, Memorystore, GCS,
  workload identities, Secret Manager containers, log metrics, probes, alerts, and
  an optional budget.
- Cloud SQL is private-only, encrypted, deletion-protected, backed up, PITR-enabled,
  and query-insights enabled.
- Redis uses private service access, AUTH, TLS server authentication, and an HA tier
  by default.
- GCS blocks public access, uses uniform IAM and versioning, and cannot be force
  destroyed.
- Runtime identities are separated. Secret access is per workload, and Terraform
  creates no secret versions or database credentials.
- Added a reviewed-plan/apply/verification/rollback runbook and non-secret variable
  and backend templates.
- Terraform 1.14 formatting passed. `terraform init -backend=false` and
  `terraform validate` passed against Google provider 7.39.0 on 2026-07-13.
- A mock-provider Terraform plan test passed nine infrastructure safety assertions.
- Eight Phase 9.1 Python contract/security tests passed.

## External apply gate still required

Slice 9.1 is not marked complete until a real staging project and billing account
are supplied, the saved Terraform plan is reviewed, explicit cost-bearing apply
approval is given, and post-apply evidence confirms the resources and IAM policy.
No resources were created and no credentials, migrations, jobs, source ownership,
or traffic were changed in this checkpoint.

## Remaining roadmap count

The fixed count remains **6 slices** until the Phase 9.1 external apply gate passes:

- Phase 9: 4 slices, including the pending apply gate for 9.1.
- Phase 10: 2 slices.

After the approved 9.1 plan/apply verification, exactly 5 slices will remain and
the next slice will be Phase 9.2 staging deployment and reconciliation.
