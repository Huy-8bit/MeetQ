variable "aws_region" {
  description = "Region of the archive bucket (keep it close to the backend and LiveKit Egress)."
  type        = string
  default     = "ap-southeast-1"
}

variable "project_name" {
  type    = string
  default = "meetq"
}

variable "environment" {
  type = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "bucket_name" {
  description = "Bucket name. Empty = \"<project>-<environment>-meeting-archive-<account id>\" (globally unique)."
  type        = string
  default     = ""
}

variable "archive_prefix" {
  description = "Key prefix the application writes under; IAM permissions are scoped to it."
  type        = string
  default     = "meetings"
}

variable "create_iam_user" {
  description = <<-EOT
    Create an IAM user for a backend that does not run on AWS (e.g. a VPS running docker compose).
    No access key is created by Terraform: create one out of band (see README) so it never lands in state.
  EOT
  type        = bool
  default     = true
}

variable "attach_to_role_names" {
  description = "Existing IAM role names (ECS task role, EC2 instance role, ...) that also get the archive policy."
  type        = list(string)
  default     = []
}

variable "abort_incomplete_multipart_days" {
  description = "Safety net: abort multipart uploads (e.g. an interrupted recording upload) after this many days."
  type        = number
  default     = 1
}

variable "force_destroy" {
  description = "Allow `terraform destroy` to delete a non-empty bucket. Keep false in production."
  type        = bool
  default     = false
}
