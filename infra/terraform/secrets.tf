locals {
  secret_consumers = {
    database-url = toset([
      "api",
      "worker",
      "job",
      "migration",
    ])
    redis-cache-url = toset([
      "api",
      "worker",
    ])
    redis-broker-url = toset([
      "worker",
      "job",
    ])
  }

  secret_bindings = flatten([
    for secret, consumers in local.secret_consumers : [
      for workload in consumers : {
        key      = "${secret}:${workload}"
        secret   = secret
        workload = workload
      }
    ]
  ])
}

resource "google_secret_manager_secret" "runtime" {
  for_each = local.secret_consumers

  secret_id = "${local.name_prefix}-${each.key}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required["secretmanager.googleapis.com"]]
}

resource "google_secret_manager_secret_iam_member" "runtime_access" {
  for_each = { for binding in local.secret_bindings : binding.key => binding }

  secret_id = google_secret_manager_secret.runtime[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.runtime_service_accounts[each.value.workload]}"
}
