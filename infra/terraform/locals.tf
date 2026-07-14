locals {
  name_prefix = "all-rise-${var.environment}"
  labels = merge(var.labels, {
    application = "all-rise"
    environment = var.environment
    managed_by  = "terraform"
  })

  artifact_bucket_name = coalesce(
    var.artifact_bucket_name,
    "${var.project_id}-${var.environment}-all-rise-artifacts"
  )

  runtime_service_accounts = {
    api       = google_service_account.api.email
    web       = google_service_account.web.email
    worker    = google_service_account.worker.email
    job       = google_service_account.job.email
    migration = google_service_account.migration.email
    scheduler = google_service_account.scheduler.email
  }

  notification_channels = var.notification_email == null ? [] : [
    google_monitoring_notification_channel.email[0].name
  ]
}
