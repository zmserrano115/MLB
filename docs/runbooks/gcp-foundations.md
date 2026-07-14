# GCP foundation plan and apply runbook

This runbook covers Phase 9.1 only. It creates cost-bearing foundation resources
but does not deploy Cloud Run, execute jobs, migrate data, write secret payloads,
or move traffic/source ownership.

## Required approval inputs

- GCP project ID and attached billing account.
- Staging region plus primary/secondary zones.
- Reviewed Cloud SQL availability/tier/disk/retention.
- Reviewed Redis tier/memory and private CIDR allocation.
- Globally unique artifact bucket name or approval of the derived name.
- Operations email and monthly budget, if enabled.
- Terraform remote-state bucket and prefix.
- Named approver for the saved plan.

Do not place credentials, database passwords, Redis AUTH strings, connection URLs,
or secret values in `terraform.tfvars`, shell arguments, CI logs, or Terraform state.

## Deployment-principal permissions

Use a dedicated short-lived deployment principal. Grant only the resource-admin
roles required by the reviewed plan: Service Usage Admin, Compute Network Admin,
Cloud SQL Admin, Redis Admin, Storage Admin, Secret Manager Admin, Service Account
Admin, Project IAM Admin, Monitoring Editor, and Logs Configuration Writer. Budget
creation additionally requires Billing Account Costs Manager on the selected
billing account. Do not grant Owner or Editor.

## Preflight and saved plan

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Fill non-secret values locally.
terraform init -backend-config=/secure/path/backend.hcl
terraform fmt -check -recursive
terraform validate
terraform test
terraform plan -out=phase9-foundations.tfplan
terraform show -no-color phase9-foundations.tfplan > /secure/path/phase9-foundations.plan.txt
```

The reviewer confirms:

- no public Cloud SQL address;
- private services access is shared by SQL and Redis;
- Redis AUTH and server authentication are enabled;
- Cloud SQL backup/PITR and deletion protection are enabled;
- the artifact bucket blocks public access and `force_destroy` is false;
- secret containers have no versions and only listed workload identities can read;
- no broad Owner/Editor or `allUsers` binding exists;
- expected alert, uptime, and optional budget resources are present;
- no Cloud Run service, job, Scheduler trigger, migration, or traffic change exists.

## Apply gate

Only the exact reviewed plan may be applied:

```bash
terraform apply phase9-foundations.tfplan
```

Capture `terraform output -json` in an access-controlled deployment evidence
location. The Redis output is sensitive and must not be placed in tickets or logs.

## Post-apply verification

```bash
gcloud sql instances describe INSTANCE --project PROJECT
gcloud redis instances describe INSTANCE --region REGION --project PROJECT
gcloud storage buckets describe gs://ARTIFACT_BUCKET --project PROJECT
gcloud secrets list --project PROJECT --filter='name:all-rise-staging'
gcloud monitoring policies list --project PROJECT
gcloud projects get-iam-policy PROJECT
```

Confirm the SQL instance has only private IP, backups/PITR are active, Redis reports
private service access plus AUTH/TLS, the bucket is private/versioned, secrets have
zero versions, and IAM matches the saved plan.

## Credential handoff for Phase 9.2

Create the application database user using an approved interactive credential
workflow. Retrieve the Redis AUTH string and server CA through controlled tooling.
Add secret versions from standard input, never from a command argument:

```bash
gcloud secrets versions add SECRET_NAME --data-file=- --project PROJECT
```

The three secrets contain the database URL, Redis cache URL, and Redis broker URL.
Redis URLs use `rediss://` and the Phase 9.2 runtime must trust the reported server CA.

## Rollback

Before apply, rollback means reject the plan. After apply, no user traffic reaches
these foundations because workloads are not deployed until Phase 9.2. Do not run a
blanket `terraform destroy`. Preserve Cloud SQL, Redis, secret containers, state,
and artifacts; prepare a reviewed targeted change for any faulty optional resource.
Deletion of protected/stateful resources requires a separate backup and approval.
