# Parameterized GCP foundations

This root provisions the Phase 9.1 foundation only. It does not deploy images,
run migrations, write secret versions, switch source ownership, or move traffic.

It creates:

- required project APIs;
- a custom VPC, a Direct VPC egress subnet, flow logs, and private services access;
- private Cloud SQL for PostgreSQL with automated backups and PITR;
- private Memorystore for Redis with AUTH and in-transit encryption;
- a private, versioned GCS artifact bucket;
- separate API, web, worker, job, migration, and Scheduler service accounts;
- empty Secret Manager containers and least-privilege access bindings;
- log-based metrics, uptime checks when hosts are supplied, alert policies, and an
  optional project budget.

Secret payloads are intentionally out of Terraform so passwords and connection
URLs do not enter state. Add secret versions through the approved release secret
workflow before Phase 9.2.

## State bootstrap

Create the remote-state bucket separately, enable object versioning and uniform
bucket-level access, then copy `backend.hcl.example` outside the repository and
fill in its values. The state bucket must not be the application artifact bucket.

## Plan

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=/secure/path/backend.hcl
terraform fmt -check -recursive
terraform validate
terraform test
terraform plan -out=phase9-foundations.tfplan
terraform show phase9-foundations.tfplan
```

Apply requires an explicit infrastructure approval and a reviewed saved plan:

```bash
terraform apply phase9-foundations.tfplan
```

Keep `deletion_protection = true`. Production uses regional Cloud SQL and Standard
HA Redis; staging defaults can be cost-reduced only through reviewed variables.

## Required follow-up outside Terraform

1. Create the least-privilege application database user through the approved
   credential workflow, then add versions for the three runtime secrets.
2. Retrieve the Redis AUTH string through the approved credential workflow,
   record the server CA, and use `rediss://` URLs.
3. Configure the Cloud Run resources from Phase 9.2 with the output network,
   subnet, service accounts, secrets, SQL connection name, and artifact bucket.
4. Supply the API/web hosts to enable public uptime checks.
5. Exercise backup/PITR restore in Phase 9.3 before any canary.

Current Google guidance used by this foundation:

- [Cloud Run Direct VPC](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Cloud SQL private IP](https://docs.cloud.google.com/sql/docs/postgres/configure-private-ip)
- [Cloud SQL PITR](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/configure-pitr)
- [Memorystore networking](https://docs.cloud.google.com/memorystore/docs/redis/networking)
- [Terraform alert policies](https://docs.cloud.google.com/monitoring/alerts/terraform)
- [Uniform bucket access](https://docs.cloud.google.com/storage/docs/uniform-bucket-level-access)
