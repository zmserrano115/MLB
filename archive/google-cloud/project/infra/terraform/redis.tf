resource "google_redis_instance" "runtime" {
  name                    = "${local.name_prefix}-redis"
  display_name            = "All Rise ${var.environment} runtime cache and broker"
  region                  = var.region
  tier                    = var.redis_tier
  memory_size_gb          = var.redis_memory_size_gb
  redis_version           = "REDIS_7_2"
  authorized_network      = google_compute_network.runtime.id
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  labels                  = local.labels

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 10
        minutes = 0
        seconds = 0
        nanos   = 0
      }
    }
  }

  depends_on = [
    google_project_service.required["redis.googleapis.com"],
    google_service_networking_connection.private_services,
  ]
}
