#!/usr/bin/env bash
# Manual or scheduled backup: ./scripts/db-backup.sh [--environment prod] [--label before-release]
set -euo pipefail
# shellcheck source=scripts/_db-backup-common.sh
. "$(dirname "${BASH_SOURCE[0]}")/_db-backup-common.sh"

global=()
command_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --environment|--env|--env-file|--docker-network) global+=("$1" "$2"); shift 2 ;;
    --use-docker|--quiet|--verbose) global+=("$1"); shift ;;
    *) command_args+=("$1"); shift ;;
  esac
done
run_cli ${global[@]+"${global[@]}"} backup ${command_args[@]+"${command_args[@]}"}
