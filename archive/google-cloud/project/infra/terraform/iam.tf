resource "google_service_account" "api" {
  account_id   = substr("${local.name_prefix}-api", 0, 30)
  display_name = "All Rise ${var.environment} API"
}

resource "google_service_account" "web" {
  account_id   = substr("${local.name_prefix}-web", 0, 30)
  display_name = "All Rise ${var.environment} web"
}

resource "google_service_account" "worker" {
  account_id   = substr("${local.name_prefix}-worker", 0, 30)
  display_name = "All Rise ${var.environment} worker"
}

resource "google_service_account" "job" {
  account_id   = substr("${local.name_prefix}-job", 0, 30)
  display_name = "All Rise ${var.environment} jobs"
}

resource "google_service_account" "migration" {
  account_id   = substr("${local.name_prefix}-migration", 0, 30)
  display_name = "All Rise ${var.environment} migrations"
}

resource "google_service_account" "scheduler" {
  account_id   = substr("${local.name_prefix}-scheduler", 0, 30)
  display_name = "All Rise ${var.environment} Scheduler invoker"
}

locals {
  project_role_bindings = flatten([
    for workload, email in local.runtime_service_accounts : [
      for role in concat(
        contains(["api", "worker", "job", "migration"], workload) ? ["roles/cloudsql.client"] : [],
        workload == "scheduler" ? ["roles/run.invoker"] : []
        ) : {
        key    = "${workload}:${role}"
        member = "serviceAccount:${email}"
        role   = role
      }
    ]
  ])
}

resource "google_project_iam_member" "runtime" {
  for_each = { for binding in local.project_role_bindings : binding.key => binding }

  project = var.project_id
  role    = each.value.role
  member  = each.value.member
}

resource "google_storage_bucket_iam_member" "artifact_writers" {
  for_each = {
    worker = google_service_account.worker.email
    job    = google_service_account.job.email
  }

  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${each.value}"
}
