mock_provider "google" {}

run "staging_foundation_plan" {
  command = plan

  variables {
    project_id  = "all-rise-staging-12345"
    environment = "staging"
  }

  assert {
    condition     = google_sql_database_instance.postgres.deletion_protection
    error_message = "Cloud SQL deletion protection must remain enabled."
  }

  assert {
    condition     = google_sql_database_instance.postgres.settings[0].deletion_protection_enabled
    error_message = "Cloud SQL API-level deletion protection must remain enabled."
  }

  assert {
    condition     = google_sql_database_instance.postgres.settings[0].edition == "ENTERPRISE"
    error_message = "The custom Cloud SQL tier requires an explicit Enterprise edition."
  }

  assert {
    condition     = google_sql_database_instance.postgres.settings[0].ip_configuration[0].ipv4_enabled == false
    error_message = "Cloud SQL must not receive a public IPv4 address."
  }

  assert {
    condition     = google_sql_database_instance.postgres.settings[0].backup_configuration[0].point_in_time_recovery_enabled
    error_message = "Cloud SQL PITR must remain enabled."
  }

  assert {
    condition     = google_redis_instance.runtime.auth_enabled
    error_message = "Redis AUTH must remain enabled."
  }

  assert {
    condition     = google_redis_instance.runtime.transit_encryption_mode == "SERVER_AUTHENTICATION"
    error_message = "Redis TLS server authentication must remain enabled."
  }

  assert {
    condition     = google_storage_bucket.artifacts.public_access_prevention == "enforced"
    error_message = "The artifact bucket must prevent public access."
  }

  assert {
    condition     = length(google_secret_manager_secret.runtime) == 3
    error_message = "Exactly three empty runtime secret containers are expected."
  }

  assert {
    condition = (
      length(google_monitoring_uptime_check_config.api) == 0 &&
      length(google_monitoring_uptime_check_config.web) == 0
    )
    error_message = "Uptime checks must wait for Phase 9.2 hostnames."
  }

  assert {
    condition     = length(google_billing_budget.project) == 0
    error_message = "The optional budget must wait for a billing account input."
  }
}
