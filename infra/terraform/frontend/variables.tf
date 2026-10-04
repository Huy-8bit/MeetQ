variable "cloudflare_account_id" {
  description = "Cloudflare account ID that owns the Pages project."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_account_id))
    error_message = "cloudflare_account_id must be the 32-character hex account ID (Cloudflare dashboard → Account home → Account ID)."
  }
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID of the DNS zone that contains domain_name. The zone must be active (nameservers point to Cloudflare)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_zone_id))
    error_message = "cloudflare_zone_id must be the 32-character hex zone ID (Cloudflare dashboard → your domain → Overview → Zone ID)."
  }
}

variable "project_name" {
  description = "Product name used in resource names, e.g. \"meetq\"."
  type        = string
  default     = "meetq"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$", var.project_name))
    error_message = "project_name must be lowercase letters, digits and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment. The Pages project is named \"<project_name>-<environment>\"."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "domain_name" {
  description = "Custom domain that serves the frontend, e.g. \"meetq.example.com\" or the zone apex \"example.com\"."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,}$", lower(trimsuffix(var.domain_name, "."))))
    error_message = "domain_name must be a hostname such as meetq.example.com (no scheme, no path)."
  }
}

variable "production_branch" {
  description = "Branch name that Wrangler deploys to as the Pages production deployment."
  type        = string
  default     = "main"
}

variable "manage_always_use_https" {
  description = <<-EOT
    Turn on the zone-wide "Always Use HTTPS" setting so http:// requests are redirected to https://.
    It applies to every hostname in the zone; enable it in one environment only (prod).
  EOT
  type        = bool
  default     = false
}

variable "www_alias" {
  description = <<-EOT
    Also serve www.<domain_name> from the Pages project (only when domain_name is the zone apex).
    The SPA redirects www to the bare domain in the browser.
  EOT
  type        = bool
  default     = false
}
