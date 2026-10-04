#!/usr/bin/env bash
# Removes the Cloudflare frontend infrastructure of one environment
# (Pages project with its deployments, custom-domain binding, DNS record).
#
#   CONFIRM_DESTROY=dev  ./scripts/destroy.sh dev     (or: make destroy-dev)
#   CONFIRM_DESTROY=prod ./scripts/destroy.sh prod    (or: make destroy-prod)
#
# CONFIRM_DESTROY must repeat the environment name, so a typo cannot remove production.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform/frontend"

fail() {
  printf '✗ %s\n' "$1" >&2
  shift || true
  for line in "$@"; do printf '  %s\n' "$line" >&2; done
  exit 1
}

ENVIRONMENT="${1:-}"
case "$ENVIRONMENT" in
  dev | staging | prod) ;;
  *) fail "Usage: CONFIRM_DESTROY=<environment> $(basename "$0") <dev|staging|prod>" ;;
esac

[ "${CONFIRM_DESTROY:-}" = "$ENVIRONMENT" ] || fail "Refusing to destroy \"$ENVIRONMENT\"." \
  "Set CONFIRM_DESTROY=$ENVIRONMENT to confirm. This deletes the Pages project, its deployments," \
  "the custom domain binding and the DNS record for $ENVIRONMENT."

DEPLOY_SECRETS_FILE="${DEPLOY_SECRETS_FILE:-$ROOT_DIR/.env.deploy}"
if [ -f "$DEPLOY_SECRETS_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$DEPLOY_SECRETS_FILE"
  set +a
fi
[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || fail "CLOUDFLARE_API_TOKEN is not set."
command -v terraform >/dev/null 2>&1 || fail "Terraform is required." "Install Terraform before running this script."

TFVARS_FILE="$TF_DIR/env/$ENVIRONMENT.tfvars"
[ -f "$TFVARS_FILE" ] || fail "Missing $TFVARS_FILE."

terraform -chdir="$TF_DIR" init -input=false >/dev/null
terraform -chdir="$TF_DIR" workspace select "$ENVIRONMENT" >/dev/null 2>&1 \
  || fail "No Terraform workspace \"$ENVIRONMENT\": nothing has been deployed from this machine."

terraform -chdir="$TF_DIR" destroy -input=false -auto-approve -var-file="$TFVARS_FILE"

printf '✓ Destroyed the %s frontend infrastructure.\n' "$ENVIRONMENT"
printf '  Note: the zone-wide "Always Use HTTPS" setting (if it was managed) is left as is.\n'
