output "network" {
  value = {
    id     = google_compute_network.runtime.id
    name   = google_compute_network.runtime.name
    subnet = google_compute_subnetwork.runtime.name
    region = var.region
    cidr   = google_compute_subnetwork.runtime.ip_cidr_range
  }
}

output "cloud_sql" {
  value = {
    connection_name = google_sql_database_instance.postgres.connection_name
    private_ip      = google_sql_database_instance.postgres.private_ip_address
    database        = google_sql_database.application.name
  }
}

output "redis" {
  value = {
    host            = google_redis_instance.runtime.host
    port            = google_redis_instance.runtime.port
    server_ca_certs = google_redis_instance.runtime.server_ca_certs
  }
  sensitive = true
}

output "artifact_bucket" {
  value = google_storage_bucket.artifacts.name
}

output "service_accounts" {
  value = local.runtime_service_accounts
}

output "runtime_secret_names" {
  value = { for name, secret in google_secret_manager_secret.runtime : name => secret.secret_id }
}
