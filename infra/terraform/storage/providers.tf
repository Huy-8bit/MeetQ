# Credentials come from the standard AWS chain (AWS_PROFILE, SSO, env vars, instance role).
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Component   = "meeting-archive"
    }
  }
}
