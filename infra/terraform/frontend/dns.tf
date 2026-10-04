# The zone must already be on Cloudflare and active (registrar nameservers point to Cloudflare).
data "cloudflare_zone" "this" {
  zone_id = var.cloudflare_zone_id

  lifecycle {
    postcondition {
      condition     = self.status == "active"
      error_message = "Cloudflare zone ${self.name} is \"${self.status}\", not active. Point the domain's nameservers at Cloudflare (${join(", ", self.name_servers)}) at your registrar, wait until the zone shows Active, then run the deploy again."
    }
  }
}

# Proxied CNAME to the project's pages.dev hostname. Created after the domain is bound
# to the project, as Pages requires. A CNAME on the zone apex works through
# Cloudflare CNAME flattening.
resource "cloudflare_dns_record" "frontend" {
  zone_id = var.cloudflare_zone_id
  name    = local.domain_name
  type    = "CNAME"
  content = cloudflare_pages_project.frontend.subdomain
  proxied = true
  ttl     = 1 # automatic (required for proxied records)
  comment = "Managed by Terraform: ${local.pages_project_name} frontend"

  depends_on = [cloudflare_pages_domain.frontend]
}

resource "cloudflare_dns_record" "www" {
  count = local.manage_www ? 1 : 0

  zone_id = var.cloudflare_zone_id
  name    = local.www_domain_name
  type    = "CNAME"
  content = cloudflare_pages_project.frontend.subdomain
  proxied = true
  ttl     = 1
  comment = "Managed by Terraform: ${local.pages_project_name} frontend (www alias)"

  depends_on = [cloudflare_pages_domain.www]
}

# Optional: redirect http:// to https:// at the edge (zone-wide setting).
resource "cloudflare_zone_setting" "always_use_https" {
  count = var.manage_always_use_https ? 1 : 0

  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}
