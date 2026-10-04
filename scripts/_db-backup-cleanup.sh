#!/usr/bin/env bash
# Removes this tool's own stale temp directories (never other /tmp files).
set -euo pipefail
# shellcheck source=scripts/_db-backup-common.sh
. "$(dirname "${BASH_SOURCE[0]}")/_db-backup-common.sh"
run_cli --quiet cleanup-local --older-than-hours 24
