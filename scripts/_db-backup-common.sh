#!/usr/bin/env bash
# Shared by scripts/db-*.sh: pick the Python environment and run the CLI.
# No business logic here: everything lives in tools/db_backup (Python).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${DB_BACKUP_VENV:-$ROOT_DIR/tools/db_backup/.venv}"

ensure_python() {
  if [ -n "${DB_BACKUP_PYTHON:-}" ]; then
    PYTHON="$DB_BACKUP_PYTHON"
    return
  fi
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    command -v python3 >/dev/null 2>&1 || { echo "✗ python3 is required." >&2; exit 2; }
    echo "Setting up the backup tool environment in $VENV_DIR (one time)..." >&2
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
    "$VENV_DIR/bin/python" -m pip install --quiet -r "$ROOT_DIR/tools/db_backup/requirements.txt"
  fi
  PYTHON="$VENV_DIR/bin/python"
}

run_cli() {
  ensure_python
  cd "$ROOT_DIR"
  # .env.backup (git-ignored) is read by the CLI itself; real environment variables win.
  exec "$PYTHON" -m tools.db_backup "$@"
}
