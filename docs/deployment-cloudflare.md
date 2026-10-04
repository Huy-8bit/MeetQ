# Frontend deployment on Cloudflare

The MeetQ SPA (`FE/`) is hosted on **Cloudflare Pages**, served by the **Cloudflare CDN**, on a **custom domain** whose **DNS** is in Cloudflare, with **TLS** issued and renewed by Cloudflare. Infrastructure is **Terraform** (`infra/terraform/frontend`, official `cloudflare/cloudflare` provider v5); the build is uploaded with **Wrangler**. The backend is deployed separately and is only an input (`VITE_API_BASE_URL`).

```bash
make deploy-prod
```

That one command does the first deploy and every later deploy.

```text
Internet → custom domain → Cloudflare DNS (proxied CNAME) → Cloudflare edge/CDN (TLS)
        → Cloudflare Pages project meetq-<env> → MeetQ SPA → backend API (separate)
```

No S3, CloudFront, Route53 or ACM is involved.

---

## First-time prerequisites (once)

1. **Cloudflare account.**
2. **The domain's zone is in Cloudflare and Active**: add the zone in Cloudflare and point the domain's **nameservers at Cloudflare** at your registrar. Terraform checks this and stops with the nameservers to use if the zone isn't active yet.
3. **Cloudflare API token** (below), exported as `CLOUDFLARE_API_TOKEN` or saved in `.env.deploy`.
4. **Google OAuth Web client ID** with `https://<domain>` as an Authorized JavaScript origin ([google-login-setup.md](google-login-setup.md)).
5. **Tools**: Terraform ≥ 1.6, Node.js ≥ 22 (Wrangler 4), npm, curl. Wrangler itself is fetched by `npx` at a pinned version.
6. **Two config files** per environment (git-ignored):

   ```bash
   cp infra/terraform/frontend/env/prod.tfvars.example infra/terraform/frontend/env/prod.tfvars
   cp config/frontend/prod.env.example config/frontend/prod.env
   # edit both: account ID, zone ID, domain; backend URLs, Google client ID
   ```

After that there are **no dashboard steps**: the Pages project, the custom-domain binding, the DNS record, the HTTPS redirect and every deployment are created by `make deploy-prod`.

## Cloudflare API token

Cloudflare dashboard → My Profile → API Tokens → **Create Token** → *Create Custom Token*. Don't use the Global API Key.

| Scope | Permission | Used for |
| --- | --- | --- |
| Account → **Cloudflare Pages** | **Edit** | Create the Pages project and custom domain (Terraform), upload deployments (Wrangler), read the domain status |
| Zone → **Zone** | **Read** | Terraform reads the zone (name, status, nameservers) |
| Zone → **DNS** | **Edit** | Terraform manages the CNAME record |
| Zone → **Zone Settings** | **Edit** | Optional, only if `manage_always_use_https = true`. Not needed for MeetQ: Pages already redirects `http://` to `https://` on custom domains (verified on meetqapp.com) |

Resources: *Account Resources* → include your account; *Zone Resources* → include only the specific zone. Optionally restrict by client IP and set an expiry.

```bash
export CLOUDFLARE_API_TOKEN="…"     # or put it in .env.deploy (see .env.deploy.example)
```

Account and zone IDs are not secret: they live in `env/<env>.tfvars`. Never commit the token.

## Configuration reference

### `infra/terraform/frontend/env/<env>.tfvars`

| Variable | Example | Notes |
| --- | --- | --- |
| `cloudflare_account_id` | `0123…cdef` | Account home → Account ID |
| `cloudflare_zone_id` | `fedc…3210` | Zone overview → Zone ID |
| `project_name` | `meetq` | Pages project = `<project_name>-<environment>` |
| `environment` | `prod` / `dev` | Also the Terraform workspace |
| `domain_name` | `meetq.example.com` or `example.com` | Must be inside the zone; apex supported |
| `production_branch` | `main` | Wrangler deploys to this branch = production deployment |
| `manage_always_use_https` | `false` | Zone-wide HTTP→HTTPS redirect. Pages already redirects its custom domains, so only needed for other hostnames in the zone |
| `www_alias` | `true` for an apex domain | Also serve `www.<apex>`; the SPA redirects www to the apex |

### `config/frontend/<env>.env` (compiled into the public bundle; no secrets)

| Variable | Required | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | yes | `https://api.meetq.example.com`, must be `https://` |
| `VITE_WS_BASE_URL` | no | Defaults to the API URL with `wss://` |
| `VITE_LIVEKIT_WS_URL` | yes | `wss://rtc.meetq.example.com` |
| `VITE_GOOGLE_CLIENT_ID` | yes | Public Google Web client ID |

`VITE_APP_ORIGIN` is set by the script from Terraform's `frontend_url`.

### Credentials / options (environment)

| Variable | Default | Notes |
| --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | — | Required; also read from `.env.deploy` |
| `SKIP_TESTS` | `0` | `1` skips typecheck + tests |
| `DOMAIN_WAIT_ATTEMPTS` | `30` | Custom-domain checks, 10 s apart (≈5 min max) |
| `WRANGLER_VERSION` | `4.147.0` | Pinned |

## What `make deploy-prod` does

```text
1. Validate environment: token, tfvars, frontend config (no example values, https API)
2. Verify CLIs: terraform, node ≥ 22, npm, npx, curl
3. npm ci → typecheck → tests                       (fails before touching Cloudflare)
4. terraform init, workspace prod, validate
5. terraform plan  → "no infrastructure changes"     (every later deploy)
                   → apply                           (first deploy / config change):
                       Pages project meetq-prod
                       custom domain binding meetq.example.com
                       proxied CNAME meetq.example.com → meetq-prod.pages.dev
                       Always Use HTTPS (optional)
   (ALLOW_MISSING_GOOGLE_CLIENT_ID=1 deploys without a Google client ID; sign-in is then disabled)
6. Read Terraform outputs (project, branch, pages.dev domain, custom domain, URL)
7. vite build with VITE_APP_ORIGIN = frontend_url; refuse if dist/404.html exists
8. wrangler pages deploy dist --project-name meetq-prod --branch main
     --commit-hash <git sha> --commit-message <subject> [--commit-dirty=true]
9. Poll the Pages custom-domain status (bounded)
10. curl via DNS-over-HTTPS (a stale local DNS cache can't hide a working site): /, /login,
    /rooms/spa-route-check, /admin/login → 200 + SPA shell; http → https; www alias status
11. Print the summary and the URL
```

Final output:

```text
✓ Terraform applied            (or: ✓ Terraform: no infrastructure changes)
✓ Cloudflare Pages configured
✓ DNS configured
✓ Frontend deployed
✓ Custom domain attached
✓ HTTPS available

Deployment Summary
Environment:   prod
Pages project: meetq-prod
Pages URL:     https://meetq-prod.pages.dev
Custom domain: https://meetq.example.com
Backend:       https://api.meetq.example.com
Version:       <git sha>

MeetQ:
  https://meetq.example.com
```

If the domain is still activating (new zone, certificate issuance), the script still exits `0` once the artifact is deployed and says:

```text
! Infrastructure deployed successfully, but the custom domain is still pending Cloudflare activation (status: pending).
```

Run the same command later to re-check; nothing is re-created.

## Idempotency

- Names are deterministic (`meetq-dev`, `meetq-prod`); Wrangler always targets the Terraform output.
- Terraform state is per workspace (`dev`, `prod`), so environments never touch each other.
- A repeated `make deploy-prod` with unchanged config plans **no changes** and only uploads a new Pages deployment.

## SPA routing, caching, HTTPS

- **SPA routes** (`/rooms/rm_123`, `/admin/live-rooms`, …): Cloudflare Pages serves `index.html` for unknown paths when the build has **no top-level `404.html`** (Pages' single-page-app mode). The script refuses to deploy a build that has one. No `_redirects` rule is used: Pages flags `/* /index.html 200` as an infinite loop.
- **Caching** (`FE/public/_headers`): `/assets/*` (content-hashed by Vite) gets `Cache-Control: public, max-age=31536000, immutable`. `index.html` keeps Pages' default revalidation, so a new deploy is live immediately. Pages purges its cache on each deployment.
- **HTTPS**: Cloudflare issues the custom-domain certificate automatically (Google Trust Services) and Pages answers `http://` with `301 → https://`. `manage_always_use_https` (zone-wide) is optional.
- Basic headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` (Google sign-in needs the origin in the referrer), `X-Frame-Options: DENY`.

## Backend requirements for a deployed frontend

The backend is not deployed by this script, but it must:

- Allow the frontend origin with credentials: `CORS_ALLOWED_ORIGINS=https://meetq.example.com` (never `*`). See [auth-backend-contract.md#5-cors](auth-backend-contract.md#5-cors).
- Live on the **same registrable domain** as the frontend (e.g. `api.meetq.example.com`) so session cookies stay first-party.
- Implement the auth endpoints in [auth-backend-contract.md](auth-backend-contract.md).

## Other commands

```bash
make deploy-dev                         # dev environment (dev.tfvars / dev.env)
make infra-check                        # terraform fmt -check + validate (+ shellcheck if installed)
CONFIRM_DESTROY=dev  make destroy-dev   # remove dev Pages project, domain binding, DNS record
CONFIRM_DESTROY=prod make destroy-prod  # same for prod; refuses without the exact confirmation
```

## Troubleshooting

### Zone not active

`Cloudflare zone example.com is "pending", not active. Point the domain's nameservers at Cloudflare (…)`: update the nameservers at your registrar, wait until Cloudflare shows the zone as Active, run the deploy again.

### Existing DNS record

If the domain already has an `A`/`AAAA`/`CNAME` record created outside Terraform (for example, the old server), `terraform apply` fails with "An A, AAAA, or CNAME record with that host already exists". Either delete that record, or adopt it so Terraform replaces it with the Pages CNAME:

```bash
cd infra/terraform/frontend
terraform workspace select prod
# record ID: Cloudflare API GET /zones/<zone_id>/dns_records?name=<domain>
terraform import -var-file=env/prod.tfvars cloudflare_dns_record.frontend '<zone_id>/<record_id>'
cd - && make deploy-prod
```

### Custom domain stays pending

Check that the CNAME is proxied (orange cloud) and that no CAA record blocks Cloudflare's certificate authorities. Status is visible via `GET /accounts/<account>/pages/projects/<project>/domains/<domain>`.

### Wrangler fails

The infrastructure is already in place; fix the error (token permissions, Node version) and run the same command again.

## Terraform state

Local state per workspace in `infra/terraform/frontend/terraform.tfstate.d/` (git-ignored). That is enough for a single operator. To share state later, add a `backend` block, e.g. Terraform Cloud/HCP, or an S3-compatible backend on Cloudflare R2, and run `terraform init -migrate-state`. There is no dedicated AWS state bucket.
