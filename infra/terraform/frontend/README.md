# Terraform: MeetQ frontend on Cloudflare

Provisions, per environment:

| Resource | Purpose |
| --- | --- |
| `data.cloudflare_zone.this` | Reads the zone; **fails if it isn't Active** (nameservers not on Cloudflare) |
| `cloudflare_pages_project.frontend` | Direct Upload Pages project `<project_name>-<environment>` |
| `cloudflare_pages_domain.frontend` | Binds `domain_name` to the project (Cloudflare-managed TLS) |
| `cloudflare_dns_record.frontend` | Proxied `CNAME domain_name → <project>.pages.dev` (apex via CNAME flattening) |
| `cloudflare_pages_domain.www`, `cloudflare_dns_record.www` | Optional `www.<apex>` alias (`www_alias`) |
| `cloudflare_zone_setting.always_use_https` | Optional zone-wide HTTP→HTTPS redirect (`manage_always_use_https`); Pages already redirects its own domains |

Provider: `cloudflare/cloudflare` `~> 5.26` (v5 schema; `.terraform.lock.hcl` is committed). Credentials: `CLOUDFLARE_API_TOKEN` from the environment only.

Don't run this by hand for deploys; use the one command, which also builds and uploads the site:

```bash
make deploy-prod          # ./scripts/deploy.sh prod
```

Manual use (inspection, imports):

```bash
cd infra/terraform/frontend
terraform init
terraform workspace select -or-create prod
terraform plan -var-file=env/prod.tfvars
terraform output
```

Files:

| File | Content |
| --- | --- |
| `versions.tf`, `providers.tf` | Terraform/provider pins; provider reads `CLOUDFLARE_API_TOKEN` |
| `variables.tf` | Inputs with validation |
| `locals.tf` | Deterministic names, zone membership |
| `pages.tf`, `dns.tf` | Resources |
| `outputs.tf` | `pages_project_name`, `pages_dev_domain`, `custom_domain`, `frontend_url`, … (read by `scripts/deploy.sh`) |
| `env/<env>.tfvars.example` | Copy to `env/<env>.tfvars` (git-ignored) |
| `terraform.tfvars.example` | Annotated example of every variable |

State: local, one workspace per environment (`terraform.tfstate.d/<env>/`, git-ignored). See [docs/deployment-cloudflare.md](../../../docs/deployment-cloudflare.md) for the token permissions, prerequisites and remote-state options.

Note: `cloudflare_zone_setting` cannot be deleted through the API, so `destroy` leaves "Always Use HTTPS" as it is.
