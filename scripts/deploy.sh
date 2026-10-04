#!/usr/bin/env bash
# One-command frontend deployment to Cloudflare (Pages + CDN + DNS + custom domain).
#
#   ./scripts/deploy.sh prod        (or: make deploy-prod)
#
# Same command for the first deploy and every update: Terraform creates or
# confirms the Pages project, custom domain and DNS record (no-op when nothing
# changed), the SPA is built, and Wrangler uploads it as a new Pages deployment.
#
# Inputs (see docs/deployment-cloudflare.md):
#   CLOUDFLARE_API_TOKEN                       environment, or .env.deploy (git-ignored)
#   infra/terraform/frontend/env/<env>.tfvars  account/zone IDs, domain, branch
#   config/frontend/<env>.env                  backend URLs + Google client ID for the build
#
# Options (environment):
#   SKIP_TESTS=1              skip frontend typecheck/tests before deploying
#   ALLOW_MISSING_GOOGLE_CLIENT_ID=1  deploy without a Google client ID (sign-in disabled)
#   DOMAIN_WAIT_ATTEMPTS=30   checks of the custom domain, 10s apart
#   WRANGLER_VERSION=4.147.0  pinned Wrangler version
#
# The backend is not deployed by this script.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform/frontend"
FE_DIR="$ROOT_DIR/FE"
WRANGLER_VERSION="${WRANGLER_VERSION:-4.147.0}"
DOMAIN_WAIT_ATTEMPTS="${DOMAIN_WAIT_ATTEMPTS:-30}"
DOMAIN_WAIT_SECONDS="${DOMAIN_WAIT_SECONDS:-10}"
MIN_NODE_MAJOR=22 # required by Wrangler 4

if [ -t 1 ]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
ok() { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$1" >&2; }
fail() {
  printf '%s✗ %s%s\n' "$RED" "$1" "$RESET" >&2
  shift || true
  for line in "$@"; do printf '  %s\n' "$line" >&2; done
  exit 1
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <environment>

Deploys the MeetQ frontend to Cloudflare Pages for <environment> (dev or prod).
EOF
}

# ─── 1. Validate environment ────────────────────────────────────────────────

ENVIRONMENT="${1:-}"
case "$ENVIRONMENT" in
  dev | staging | prod) ;;
  -h | --help) usage; exit 0 ;;
  "") usage >&2; fail "Missing environment." ;;
  *) usage >&2; fail "Unknown environment \"$ENVIRONMENT\"." ;;
esac

TFVARS_FILE="$TF_DIR/env/$ENVIRONMENT.tfvars"
FE_ENV_FILE="$ROOT_DIR/config/frontend/$ENVIRONMENT.env"
DEPLOY_SECRETS_FILE="${DEPLOY_SECRETS_FILE:-$ROOT_DIR/.env.deploy}"

step "Checking configuration for $ENVIRONMENT"

if [ -f "$DEPLOY_SECRETS_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$DEPLOY_SECRETS_FILE"
  set +a
fi

[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || fail "CLOUDFLARE_API_TOKEN is not set." \
  "Create a Cloudflare API token (docs/deployment-cloudflare.md#cloudflare-api-token)," \
  "then: export CLOUDFLARE_API_TOKEN=...   or put it in .env.deploy (git-ignored)."
[ -f "$TFVARS_FILE" ] || fail "Missing $TFVARS_FILE." \
  "cp $TF_DIR/env/$ENVIRONMENT.tfvars.example $TFVARS_FILE  and fill in your account ID, zone ID and domain."
[ -f "$FE_ENV_FILE" ] || fail "Missing $FE_ENV_FILE." \
  "cp $ROOT_DIR/config/frontend/$ENVIRONMENT.env.example $FE_ENV_FILE  and fill in the backend URLs and Google client ID."
ok "Configuration files found"

# ─── 2. Required CLIs ───────────────────────────────────────────────────────

require_cli() {
  command -v "$1" >/dev/null 2>&1 || fail "$2 is required." "$3"
}
require_cli terraform "Terraform" "Install Terraform >= 1.6 before deploying: https://developer.hashicorp.com/terraform/install"
require_cli node "Node.js" "Install Node.js >= $MIN_NODE_MAJOR before deploying: https://nodejs.org"
require_cli npm "npm" "npm ships with Node.js; reinstall Node.js >= $MIN_NODE_MAJOR."
require_cli npx "npx" "npx ships with npm; reinstall Node.js >= $MIN_NODE_MAJOR."
require_cli curl "curl" "Install curl before deploying."

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge "$MIN_NODE_MAJOR" ] || fail "Node.js $MIN_NODE_MAJOR or newer is required (found $(node -v))." \
  "Wrangler $WRANGLER_VERSION does not run on older Node.js."
ok "terraform $(terraform version -json 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{console.log(JSON.parse(s).terraform_version)}catch{console.log("?")}})'), node $(node -v), npm $(npm -v)"

# Frontend build settings (public values only: they end up in the JS bundle).
set -a
# shellcheck disable=SC1090
. "$FE_ENV_FILE"
set +a
[ -n "${VITE_API_BASE_URL:-}" ] || fail "VITE_API_BASE_URL is empty in $FE_ENV_FILE."
if [ -z "${VITE_GOOGLE_CLIENT_ID:-}" ]; then
  if [ "${ALLOW_MISSING_GOOGLE_CLIENT_ID:-0}" = "1" ]; then
    warn "VITE_GOOGLE_CLIENT_ID is empty: the site deploys, but /login shows \"Google sign-in isn't configured\"."
  else
    fail "VITE_GOOGLE_CLIENT_ID is empty in $FE_ENV_FILE." "See docs/google-login-setup.md." \
      "To deploy anyway (sign-in disabled), run with ALLOW_MISSING_GOOGLE_CLIENT_ID=1."
  fi
fi
[ -n "${VITE_LIVEKIT_WS_URL:-}" ] || fail "VITE_LIVEKIT_WS_URL is empty in $FE_ENV_FILE."
case "$VITE_API_BASE_URL" in
  https://*) ;;
  *) fail "VITE_API_BASE_URL must use https:// (got $VITE_API_BASE_URL)." ;;
esac
if [ -z "${VITE_WS_BASE_URL:-}" ]; then
  VITE_WS_BASE_URL="wss://${VITE_API_BASE_URL#https://}"
  export VITE_WS_BASE_URL
fi
case "$VITE_GOOGLE_CLIENT_ID $VITE_API_BASE_URL" in
  *1234567890-abcdefghijklmnop* | *example.com*)
    fail "$FE_ENV_FILE still contains example values." "Replace the example API URL and Google client ID." ;;
esac
ok "Frontend build settings loaded (backend: $VITE_API_BASE_URL)"

# ─── 3. Install, check and test the frontend ────────────────────────────────

step "Installing frontend dependencies (npm ci)"
(cd "$FE_DIR" && npm ci --no-audit --no-fund)
ok "Dependencies installed"

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  step "Typechecking and testing the frontend"
  (cd "$FE_DIR" && npm run typecheck && npm test)
  ok "Typecheck and tests passed"
else
  warn "SKIP_TESTS=1: frontend typecheck and tests skipped"
fi

# ─── 4–6. Terraform: Pages project, custom domain, DNS ──────────────────────

tf() { terraform -chdir="$TF_DIR" "$@"; }

step "Provisioning Cloudflare with Terraform (workspace: $ENVIRONMENT)"
tf init -input=false >/dev/null
tf workspace select -or-create=true "$ENVIRONMENT" >/dev/null
tf validate -no-color >/dev/null
ok "Terraform initialized and valid"

PLAN_FILE="$TF_DIR/$ENVIRONMENT.tfplan"
trap 'rm -f "$PLAN_FILE"' EXIT
set +e
tf plan -input=false -no-color -detailed-exitcode -var-file="$TFVARS_FILE" -out="$PLAN_FILE" >"$TF_DIR/.last-plan.log" 2>&1
PLAN_STATUS=$?
set -e
case "$PLAN_STATUS" in
  0)
    ok "Terraform: no infrastructure changes"
    ;;
  2)
    grep -E '^\s+[#~+-]|Plan:' "$TF_DIR/.last-plan.log" || true
    tf apply -input=false -no-color "$PLAN_FILE" || fail "terraform apply failed." \
      "If Cloudflare reports that a DNS record for the domain already exists, it was created outside Terraform." \
      "Adopt it (see docs/deployment-cloudflare.md#existing-dns-record) or remove it, then run the deploy again."
    ok "Terraform applied"
    ;;
  *)
    cat "$TF_DIR/.last-plan.log" >&2
    fail "terraform plan failed (see output above)."
    ;;
esac
rm -f "$TF_DIR/.last-plan.log"

# ─── 7. Terraform outputs are the source of truth for names ─────────────────

tf_out() { tf output -raw "$1"; }
CLOUDFLARE_ACCOUNT_ID="$(tf_out cloudflare_account_id)"
PAGES_PROJECT="$(tf_out pages_project_name)"
PAGES_BRANCH="$(tf_out production_branch)"
PAGES_DEV_DOMAIN="$(tf_out pages_dev_domain)"
CUSTOM_DOMAIN="$(tf_out custom_domain)"
FRONTEND_URL="$(tf_out frontend_url)"
WWW_DOMAIN="$(tf output -json www_domain 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{const v=JSON.parse(s);console.log(v||"")}catch{console.log("")}})')"
export CLOUDFLARE_ACCOUNT_ID
ok "Cloudflare Pages configured ($PAGES_PROJECT → $PAGES_DEV_DOMAIN)"
ok "DNS configured ($CUSTOM_DOMAIN → $PAGES_DEV_DOMAIN, proxied)"

# ─── 8. Build with the final public origin ──────────────────────────────────

step "Building the frontend for $FRONTEND_URL"
export VITE_APP_ORIGIN="$FRONTEND_URL"
(cd "$FE_DIR" && npm run build)
DIST_DIR="$FE_DIR/dist"
[ -f "$DIST_DIR/index.html" ] || fail "Build did not produce $DIST_DIR/index.html."
# Pages serves index.html for unknown paths (SPA mode) only when there is no top-level 404.html.
[ ! -f "$DIST_DIR/404.html" ] || fail "$DIST_DIR/404.html exists; it would turn off Pages SPA routing."
ok "Frontend built ($DIST_DIR)"

# ─── 9. Deploy the artifact with Wrangler ───────────────────────────────────

step "Deploying to Cloudflare Pages ($PAGES_PROJECT, branch $PAGES_BRANCH)"
GIT_SHA=""
WRANGLER_GIT_ARGS=()
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_SHA="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || true)"
  if [ -n "$GIT_SHA" ]; then
    GIT_MESSAGE="$(git -C "$ROOT_DIR" log -1 --format=%s 2>/dev/null | cut -c1-200 || true)"
    WRANGLER_GIT_ARGS=(--commit-hash "$GIT_SHA" --commit-message "${GIT_MESSAGE:-deploy}")
    if [ -n "$(git -C "$ROOT_DIR" status --porcelain 2>/dev/null)" ]; then
      WRANGLER_GIT_ARGS+=(--commit-dirty=true)
    fi
  fi
fi

WRANGLER_LOG="$(mktemp)"
trap 'rm -f "$PLAN_FILE" "$WRANGLER_LOG"' EXIT
if ! WRANGLER_SEND_METRICS=false npx --yes "wrangler@$WRANGLER_VERSION" pages deploy "$DIST_DIR" \
  --project-name "$PAGES_PROJECT" \
  --branch "$PAGES_BRANCH" \
  ${WRANGLER_GIT_ARGS[@]+"${WRANGLER_GIT_ARGS[@]}"} 2>&1 | tee "$WRANGLER_LOG"; then
  fail "Wrangler deploy failed (see output above)." \
    "Infrastructure is in place; fix the error and run the same command again."
fi
DEPLOYMENT_URL="$(grep -Eo 'https://[a-z0-9.-]+\.pages\.dev' "$WRANGLER_LOG" | tail -1 || true)"
ok "Frontend deployed${DEPLOYMENT_URL:+ ($DEPLOYMENT_URL)}"

# ─── 10. Wait for the custom domain (bounded) ───────────────────────────────

json_field() { node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{const v=process.argv[1].split(".").reduce((o,k)=>o?.[k],JSON.parse(s));console.log(v??"")}catch{console.log("")}})' "$1"; }

domain_status_of() {
  curl -fsS --max-time 15 \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$PAGES_PROJECT/domains/$1" 2>/dev/null \
    | json_field result.status
}
domain_status() { domain_status_of "$CUSTOM_DOMAIN"; }

step "Waiting for $CUSTOM_DOMAIN to become active"
DOMAIN_STATUS=""
for attempt in $(seq 1 "$DOMAIN_WAIT_ATTEMPTS"); do
  DOMAIN_STATUS="$(domain_status || true)"
  if [ "$DOMAIN_STATUS" = "active" ]; then
    break
  fi
  printf '  attempt %s/%s: status=%s\n' "$attempt" "$DOMAIN_WAIT_ATTEMPTS" "${DOMAIN_STATUS:-unknown}"
  if [ "$attempt" -lt "$DOMAIN_WAIT_ATTEMPTS" ]; then
    sleep "$DOMAIN_WAIT_SECONDS"
  fi
done

# ─── 11. Verify HTTPS and SPA routes ────────────────────────────────────────

# Resolve through DNS-over-HTTPS so a stale local DNS cache (e.g. from the previous
# record) does not hide a working deployment. Falls back to the system resolver.
CURL_DOH=()
if curl -sS --max-time 10 --doh-url https://cloudflare-dns.com/dns-query -o /dev/null https://cloudflare.com 2>/dev/null; then
  CURL_DOH=(--doh-url https://cloudflare-dns.com/dns-query)
fi
web_curl() { curl ${CURL_DOH[@]+"${CURL_DOH[@]}"} "$@"; }

# 200 + the SPA shell for each route; retried because edge/DNS propagation lags.
verify_routes() {
  local base="$1" path code body
  for path in / /login /rooms/spa-route-check /admin/login; do
    local passed=0
    for _ in 1 2 3 4 5 6; do
      body="$(web_curl -sS --max-time 15 -w '\n%{http_code}' "$base$path" 2>/dev/null || true)"
      code="${body##*$'\n'}"
      if [ "$code" = "200" ] && printf '%s' "$body" | grep -q 'id="root"'; then
        passed=1
        break
      fi
      sleep 5
    done
    [ "$passed" = "1" ] || return 1
  done
}

DOMAIN_ACTIVE=0
if [ "$DOMAIN_STATUS" = "active" ] && verify_routes "$FRONTEND_URL"; then
  DOMAIN_ACTIVE=1
  ok "Custom domain attached"
  ok "HTTPS available ($FRONTEND_URL serves /, /login, /rooms/*, /admin/login)"
  HTTP_REDIRECT="$(web_curl -sS -o /dev/null --max-time 15 -w '%{http_code} %{redirect_url}' "http://$CUSTOM_DOMAIN/" 2>/dev/null || true)"
  case "$HTTP_REDIRECT" in
    30[1278]\ https://*) ok "http:// redirects to https://" ;;
    *) warn "http://$CUSTOM_DOMAIN did not redirect to https:// ($HTTP_REDIRECT). Set manage_always_use_https = true for one environment." ;;
  esac
  if [ -n "$WWW_DOMAIN" ]; then
    WWW_STATUS="$(domain_status_of "$WWW_DOMAIN" || true)"
    if [ "$WWW_STATUS" = "active" ]; then ok "www alias active (https://$WWW_DOMAIN → $FRONTEND_URL)"; else warn "www alias $WWW_DOMAIN is still ${WWW_STATUS:-pending}; Cloudflare activates it on its own."; fi
  fi
else
  if verify_routes "https://$PAGES_DEV_DOMAIN"; then
    ok "Deployment verified on https://$PAGES_DEV_DOMAIN (SPA routes return the app)"
  else
    warn "Could not verify https://$PAGES_DEV_DOMAIN yet; Pages may still be propagating."
  fi
  if [ "$DOMAIN_STATUS" = "active" ]; then
    warn "Cloudflare reports $CUSTOM_DOMAIN as active, but its routes could not be verified from this machine (network or DNS propagation). Check $FRONTEND_URL in a browser."
  else
    warn "Infrastructure deployed successfully, but the custom domain is still pending Cloudflare activation (status: ${DOMAIN_STATUS:-unknown})."
    warn "Cloudflare finishes DNS/certificate provisioning on its own; re-run this command later to re-check."
  fi
fi

# ─── Summary ────────────────────────────────────────────────────────────────

printf '\n%sDeployment Summary%s\n\n' "$BOLD" "$RESET"
printf 'Environment:\n  %s\n\n' "$ENVIRONMENT"
printf 'Pages project:\n  %s\n\n' "$PAGES_PROJECT"
printf 'Pages URL:\n  https://%s\n\n' "$PAGES_DEV_DOMAIN"
printf 'Custom domain:\n  %s%s\n\n' "$FRONTEND_URL" "$([ "$DOMAIN_ACTIVE" = "1" ] && echo "" || echo "  (pending activation)")"
printf 'Backend:\n  %s\n\n' "$VITE_API_BASE_URL"
printf 'Version:\n  %s\n\n' "${GIT_SHA:-unknown (no git metadata)}"
printf 'MeetQ:\n  %s\n' "$FRONTEND_URL"
