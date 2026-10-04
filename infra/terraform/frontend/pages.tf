# Direct Upload Pages project: no Git integration, Wrangler uploads the built SPA.
resource "cloudflare_pages_project" "frontend" {
  account_id        = var.cloudflare_account_id
  name              = local.pages_project_name
  production_branch = var.production_branch

  lifecycle {
    # Build and runtime settings are not used by a Direct Upload static SPA; the API
    # fills in defaults that would otherwise show up as drift on every plan.
    ignore_changes = [build_config, deployment_configs, source]
  }
}

# Binds the custom domain to the project. Cloudflare issues and renews its TLS certificate.
resource "cloudflare_pages_domain" "frontend" {
  account_id   = var.cloudflare_account_id
  project_name = cloudflare_pages_project.frontend.name
  name         = local.domain_name

  lifecycle {
    precondition {
      condition     = local.domain_in_zone
      error_message = "domain_name \"${local.domain_name}\" is not inside the zone \"${local.zone_name}\" (cloudflare_zone_id). Use a hostname in that zone or the zone ID of its own zone."
    }
  }
}

resource "cloudflare_pages_domain" "www" {
  count = local.manage_www ? 1 : 0

  account_id   = var.cloudflare_account_id
  project_name = cloudflare_pages_project.frontend.name
  name         = local.www_domain_name
}
