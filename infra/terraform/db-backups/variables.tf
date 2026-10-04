variable "aws_region" {
  type    = string
  default = "ap-southeast-1"
}

variable "project_name" {
  type    = string
  default = "meetq"
}

variable "bucket_name" {
  description = "Empty = \"<project>-db-backups-<account id>\". One bucket holds every environment under separate prefixes."
  type        = string
  default     = ""
}

variable "backup_prefix" {
  description = "Must match DB_BACKUP_S3_PREFIX."
  type        = string
  default     = "database-backups"
}

variable "environments" {
  description = "Environments that write backups; each gets its own prefix, lifecycle rule and IAM scope."
  type        = list(string)
  default     = ["dev", "staging", "prod"]
}

variable "retention_days" {
  description = <<-EOT
    Days after which S3 deletes backups, per environment (0 = no lifecycle expiry; use `prune` instead).
    Lifecycle cannot keep a minimum number of backups: if backups stop for longer than this period,
    the last ones expire too. Use the CLI `prune` (MIN_BACKUPS_TO_KEEP) when that matters.
  EOT
  type        = map(number)
  default     = { dev = 14, staging = 14, prod = 30 }
}

variable "create_iam_users" {
  description = "Create a writer user (backup) and a reader user (restore) for hosts outside AWS. No access keys are created by Terraform."
  type        = bool
  default     = true
}

variable "writer_role_names" {
  description = "Existing IAM roles (EC2/ECS) that run scheduled backups."
  type        = list(string)
  default     = []
}

variable "allow_prune" {
  description = "Give the writer s3:DeleteObject (needed only for `meetq-db prune`)."
  type        = bool
  default     = false
}
