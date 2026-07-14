from __future__ import annotations

from pathlib import Path

ROOT = Path("infra/terraform")


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def all_terraform() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("*.tf")))


def test_foundation_is_complete_parameterized_and_locked() -> None:
    expected = {
        "apis.tf",
        "database.tf",
        "iam.tf",
        "locals.tf",
        "monitoring.tf",
        "network.tf",
        "outputs.tf",
        "redis.tf",
        "secrets.tf",
        "storage.tf",
        "variables.tf",
        "versions.tf",
    }
    assert expected <= {path.name for path in ROOT.glob("*.tf")}
    assert (ROOT / ".terraform.lock.hcl").is_file()
    assert (ROOT / "foundation.tftest.hcl").is_file()
    assert 'backend "gcs" {}' in source("versions.tf")
    assert "var.project_id" in source("versions.tf")
    assert "replace-with-staging-project" not in all_terraform()


def test_required_apis_and_private_service_network_are_declared() -> None:
    apis = source("apis.tf")
    for service in (
        "run.googleapis.com",
        "sqladmin.googleapis.com",
        "redis.googleapis.com",
        "servicenetworking.googleapis.com",
        "secretmanager.googleapis.com",
        "monitoring.googleapis.com",
        "logging.googleapis.com",
    ):
        assert service in apis
    network = source("network.tf")
    assert "auto_create_subnetworks = false" in network
    assert "private_ip_google_access = true" in network
    assert 'purpose       = "VPC_PEERING"' in network
    assert "google_service_networking_connection" in network
    assert "log_config" in network
    assert "/26 or larger" in source("variables.tf")


def test_cloud_sql_is_private_encrypted_protected_and_recoverable() -> None:
    database = source("database.tf")
    assert "ipv4_enabled                                  = false" in database
    assert 'ssl_mode                                      = "ENCRYPTED_ONLY"' in database
    assert "deletion_protection = var.deletion_protection" in database
    assert "deletion_protection_enabled = var.deletion_protection" in database
    assert 'edition                     = "ENTERPRISE"' in database
    assert "point_in_time_recovery_enabled = true" in database
    assert "transaction_log_retention_days" in database
    assert "backup_retention_settings" in database
    assert "query_insights_enabled" in database


def test_redis_uses_private_service_access_auth_and_tls() -> None:
    redis = source("redis.tf")
    assert 'connect_mode            = "PRIVATE_SERVICE_ACCESS"' in redis
    assert "authorized_network      = google_compute_network.runtime.id" in redis
    assert "auth_enabled            = true" in redis
    assert 'transit_encryption_mode = "SERVER_AUTHENTICATION"' in redis
    assert 'redis_version           = "REDIS_7_2"' in redis


def test_artifact_bucket_is_private_versioned_and_bounded() -> None:
    storage = source("storage.tf")
    assert "uniform_bucket_level_access = true" in storage
    assert 'public_access_prevention    = "enforced"' in storage
    assert "force_destroy               = false" in storage
    assert "versioning" in storage and "enabled = true" in storage
    assert "artifact_retention_days" in storage


def test_runtime_identities_and_secret_access_are_least_privilege() -> None:
    iam = source("iam.tf")
    for workload in ("api", "web", "worker", "job", "migration", "scheduler"):
        assert f'google_service_account" "{workload}' in iam
    assert "roles/owner" not in iam
    assert "roles/editor" not in iam
    assert "roles/cloudsql.client" in iam
    assert "roles/storage.objectAdmin" in iam

    secrets = source("secrets.tf")
    assert "database-url" in secrets
    assert "redis-cache-url" in secrets
    assert "redis-broker-url" in secrets
    assert "roles/secretmanager.secretAccessor" in secrets
    assert "google_secret_manager_secret_version" not in all_terraform()
    assert "password" not in all_terraform().lower()


def test_monitoring_includes_logs_probes_alerts_and_optional_budget() -> None:
    monitoring = source("monitoring.tf")
    assert monitoring.count('resource "google_logging_metric"') == 2
    assert monitoring.count('resource "google_monitoring_uptime_check_config"') == 2
    assert monitoring.count('resource "google_monitoring_alert_policy"') >= 5
    assert 'path         = "/healthz"' in monitoring
    assert "validate_ssl = true" in monitoring
    assert "cloudsql.googleapis.com/database/cpu/utilization" in monitoring
    assert 'resource "google_billing_budget"' in monitoring


def test_foundation_does_not_apply_or_cut_over_runtime_resources() -> None:
    terraform = all_terraform()
    assert "google_cloud_run_v2_service" not in terraform
    assert "google_cloud_run_v2_job" not in terraform
    assert "google_cloud_scheduler_job" not in terraform
    assert "JOB_SOURCE_OWNERSHIP" not in terraform
    readme = source("README.md")
    assert "does not deploy images" in readme
    assert "explicit infrastructure approval" in readme
    assert "Secret payloads are intentionally out of Terraform" in readme
