output "cloudflare_account_id" {
  description = "Account that owns the Pages project (Wrangler reads it as CLOUDFLARE_ACCOUNT_ID)."
  value       = var.cloudflare_account_id
}

output "environment" {
  value = var.environment
}

output "pages_project_name" {
  description = "Pages project Wrangler deploys to."
  value       = cloudflare_pages_project.frontend.name
}

output "production_branch" {
  description = "Branch Wrangler deploys as the production deployment."
  value       = cloudflare_pages_project.frontend.production_branch
}

output "pages_dev_domain" {
  description = "Project hostname on pages.dev, e.g. meetq-prod.pages.dev."
  value       = cloudflare_pages_project.frontend.subdomain
}

output "custom_domain" {
  value = cloudflare_pages_domain.frontend.name
}

output "custom_domain_is_apex" {
  value = local.is_apex
}

output "frontend_url" {
  description = "Public URL of the frontend."
  value       = "https://${cloudflare_pages_domain.frontend.name}"
}

output "www_domain" {
  description = "www alias served by the project (redirects to frontend_url in the browser), or null."
  value       = local.manage_www ? local.www_domain_name : null
}
