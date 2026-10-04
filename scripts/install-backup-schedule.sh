#!/usr/bin/env bash
# Install the daily backup schedule on a Linux server.
#
#   sudo ./scripts/install-backup-schedule.sh            # systemd timer (preferred)
#   ./scripts/install-backup-schedule.sh --print-cron    # print a crontab line instead (installs nothing)
#
# Prerequisite: a configured .env.backup in the repository root and one successful
# manual run of ./scripts/db-backup.sh.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${BACKUP_RUN_USER:-${SUDO_USER:-$(id -un)}}"
SCHEDULE="${BACKUP_ON_CALENDAR:-*-*-* 02:00:00}"

if [ "${1:-}" = "--print-cron" ]; then
  echo "# MeetQ database backup, daily at 02:00 (add with: crontab -e)"
  echo "0 2 * * * cd $ROOT_DIR && ./scripts/db-backup.sh --quiet --trigger scheduled >> /var/log/meetq-db-backup.log 2>&1"
  exit 0
fi

fail() { echo "✗ $*" >&2; exit 2; }
command -v systemctl >/dev/null 2>&1 || fail "systemd not found. Use --print-cron for a cron entry."
[ "$(id -u)" -eq 0 ] || fail "Run with sudo to install the systemd timer (or use --print-cron)."
[ -f "$ROOT_DIR/.env.backup" ] || fail "Missing $ROOT_DIR/.env.backup (cp .env.backup.example .env.backup and configure it)."
grep -q '^BACKUP_ENVIRONMENT=' "$ROOT_DIR/.env.backup" || fail "Set BACKUP_ENVIRONMENT in .env.backup."
chmod 600 "$ROOT_DIR/.env.backup"

for unit in meetq-db-backup.service meetq-db-backup.timer; do
  sed -e "s|@MEETQ_DIR@|$ROOT_DIR|g" -e "s|@RUN_USER@|$RUN_USER|g" -e "s|^OnCalendar=.*|OnCalendar=$SCHEDULE|" \
    "$ROOT_DIR/deploy/systemd/$unit" > "/etc/systemd/system/$unit"
done

# Prepare the Python environment once as the service user (no surprise downloads at 02:00).
sudo -u "$RUN_USER" "$ROOT_DIR/scripts/db-backup.sh" --help >/dev/null

systemctl daemon-reload
systemctl enable --now meetq-db-backup.timer
echo "✓ Installed meetq-db-backup.timer ($SCHEDULE, user $RUN_USER)"
systemctl list-timers meetq-db-backup.timer --no-pager || true
echo
echo "Status:  systemctl status meetq-db-backup.service"
echo "Logs:    journalctl -u meetq-db-backup.service"
echo "Run now: sudo systemctl start meetq-db-backup.service"
