resource "google_monitoring_notification_channel" "email" {
  count = var.notification_email == null ? 0 : 1

  display_name = "All Rise ${var.environment} operations"
  type         = "email"
  labels = {
    email_address = var.notification_email
  }
  enabled = true
}

resource "google_logging_metric" "api_errors" {
  name        = "${local.name_prefix}-api-errors"
  description = "Error-severity logs from All Rise Cloud Run revisions."
  filter      = "resource.type=\"cloud_run_revision\" severity>=ERROR resource.labels.service_name=~\"all-rise-.*\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "dead_letters" {
  name        = "${local.name_prefix}-dead-letters"
  description = "Durable jobs entering dead-letter state."
  filter      = "resource.type=(\"cloud_run_job\" OR \"cloud_run_worker_pool\") (textPayload:\"dead_letter\" OR jsonPayload.status=\"dead_letter\")"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_uptime_check_config" "api" {
  count = var.staging_api_host == null ? 0 : 1

  display_name = "All Rise ${var.environment} API health"
  timeout      = "5s"
  period       = "60s"

  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = coalesce(var.staging_api_host, "invalid.example")
    }
  }
}

resource "google_monitoring_uptime_check_config" "web" {
  count = var.staging_web_host == null ? 0 : 1

  display_name = "All Rise ${var.environment} web health"
  timeout      = "5s"
  period       = "60s"

  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = coalesce(var.staging_web_host, "invalid.example")
    }
  }
}

resource "google_monitoring_alert_policy" "api_errors" {
  display_name          = "All Rise ${var.environment}: API errors"
  combiner              = "OR"
  notification_channels = local.notification_channels

  conditions {
    display_name = "API error log count"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.api_errors.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "dead_letters" {
  display_name          = "All Rise ${var.environment}: dead-letter task"
  combiner              = "OR"
  notification_channels = local.notification_channels

  conditions {
    display_name = "Any durable task dead letter"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.dead_letters.name}\" AND resource.type=(\"cloud_run_job\" OR \"cloud_run_worker_pool\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "database_cpu" {
  display_name          = "All Rise ${var.environment}: Cloud SQL CPU"
  combiner              = "OR"
  notification_channels = local.notification_channels

  conditions {
    display_name = "Cloud SQL CPU above 80%"
    condition_threshold {
      filter          = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "api_uptime" {
  count = var.staging_api_host == null ? 0 : 1

  display_name          = "All Rise ${var.environment}: API unavailable"
  combiner              = "OR"
  notification_channels = local.notification_channels

  conditions {
    display_name = "API health check failing"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.api[0].uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "web_uptime" {
  count = var.staging_web_host == null ? 0 : 1

  display_name          = "All Rise ${var.environment}: web unavailable"
  combiner              = "OR"
  notification_channels = local.notification_channels

  conditions {
    display_name = "Web health check failing"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.web[0].uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
      }
    }
  }
}

resource "google_billing_budget" "project" {
  count = var.billing_account_id == null ? 0 : 1

  billing_account = var.billing_account_id
  display_name    = "All Rise ${var.environment} monthly budget"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(floor(var.monthly_budget_usd))
    }
  }

  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }

}
