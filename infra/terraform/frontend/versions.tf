terraform {
  # `terraform workspace select -or-create` (used by scripts/deploy.sh) needs >= 1.4.
  required_version = ">= 1.6.0"

  required_providers {
    cloudflare = {
      source = "cloudflare/cloudflare"
      # Written against the v5 schema (cloudflare_dns_record, cloudflare_pages_domain.name).
      version = "~> 5.26"
    }
  }
}
