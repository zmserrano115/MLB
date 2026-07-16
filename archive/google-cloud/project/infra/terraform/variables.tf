variable "project_id" {
  description = "GCP project ID."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID."
  }
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "staging"
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "primary_zone" {
  type    = string
  default = "us-central1-a"
}

variable "secondary_zone" {
  type    = string
  default = "us-central1-b"
}

variable "network_cidr" {
  description = "Direct VPC egress subnet; keep /26 or larger for Cloud Run scaling."
  type        = string
  default     = "10.40.0.0/24"
  validation {
    condition = (
      can(cidrhost(var.network_cidr, 1)) &&
      try(tonumber(split("/", var.network_cidr)[1]) <= 26, false)
    )
    error_message = "network_cidr must be valid IPv4 CIDR with a /26 or larger address range."
  }
}

variable "private_service_prefix_length" {
  type    = number
  default = 16
  validation {
    condition     = var.private_service_prefix_length >= 16 && var.private_service_prefix_length <= 24
    error_message = "private_service_prefix_length must be between /16 and /24."
  }
}

variable "database_name" {
  type    = string
  default = "all_rise"
}

variable "database_version" {
  type    = string
  default = "POSTGRES_16"
}

variable "database_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "database_availability_type" {
  type    = string
  default = "REGIONAL"
  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.database_availability_type)
    error_message = "database_availability_type must be ZONAL or REGIONAL."
  }
}

variable "database_disk_size_gb" {
  type    = number
  default = 50
  validation {
    condition     = var.database_disk_size_gb >= 10
    error_message = "database_disk_size_gb must be at least 10."
  }
}

variable "database_backup_retention_count" {
  type    = number
  default = 14
}

variable "database_transaction_log_retention_days" {
  type    = number
  default = 7
}

variable "redis_tier" {
  type    = string
  default = "STANDARD_HA"
  validation {
    condition     = contains(["BASIC", "STANDARD_HA"], var.redis_tier)
    error_message = "redis_tier must be BASIC or STANDARD_HA."
  }
}

variable "redis_memory_size_gb" {
  type    = number
  default = 1
  validation {
    condition     = var.redis_memory_size_gb >= 1
    error_message = "redis_memory_size_gb must be at least 1."
  }
}

variable "artifact_bucket_name" {
  description = "Globally unique artifact bucket; null derives one from project and environment."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition = (
      var.artifact_bucket_name == null ||
      can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.artifact_bucket_name))
    )
    error_message = "artifact_bucket_name must be null or a valid GCS bucket name."
  }
}

variable "artifact_retention_days" {
  type    = number
  default = 30
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "notification_email" {
  description = "Optional verified Monitoring email channel."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.notification_email == null || can(regex("^[^@]+@[^@]+\\.[^@]+$", var.notification_email))
    error_message = "notification_email must be null or a valid email address."
  }
}

variable "staging_api_host" {
  description = "Optional API hostname without scheme; enables /healthz uptime check."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition = (
      var.staging_api_host == null ||
      can(regex("^[A-Za-z0-9.-]+$", var.staging_api_host))
    )
    error_message = "staging_api_host must be a hostname without a scheme or path."
  }
}

variable "staging_web_host" {
  description = "Optional web hostname without scheme; enables /healthz uptime check."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition = (
      var.staging_web_host == null ||
      can(regex("^[A-Za-z0-9.-]+$", var.staging_web_host))
    )
    error_message = "staging_web_host must be a hostname without a scheme or path."
  }
}

variable "billing_account_id" {
  description = "Optional billing account ID; enables a project budget."
  type        = string
  default     = null
  nullable    = true
}

variable "monthly_budget_usd" {
  type    = number
  default = 250
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}

variable "labels" {
  type    = map(string)
  default = {}
}
