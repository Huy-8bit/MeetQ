locals {
  # Deterministic: Wrangler deploys to exactly this project on every run.
  pages_project_name = "${var.project_name}-${var.environment}"

  domain_name = lower(trimsuffix(var.domain_name, "."))
  zone_name   = lower(data.cloudflare_zone.this.name)

  domain_in_zone = local.domain_name == local.zone_name || endswith(local.domain_name, ".${local.zone_name}")
  is_apex        = local.domain_name == local.zone_name

  www_domain_name = "www.${local.domain_name}"
  manage_www      = var.www_alias && local.is_apex
}
