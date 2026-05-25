#!/usr/bin/env bash
set -euo pipefail

# Installs a daily cronjob at 03:00 to run backup.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/backup.sh"
LOG_DIR="$SCRIPT_DIR/backups"
LOG_FILE="$LOG_DIR/backup-cron.log"

mkdir -p "$LOG_DIR"

if ! command -v crontab >/dev/null 2>&1; then
  echo "ERROR: crontab command not found." >&2
  exit 1
fi

LINE="0 3 * * * cd $SCRIPT_DIR && BACKUP_ROOT=$SCRIPT_DIR/backups ./backup.sh >> $LOG_FILE 2>&1"

( crontab -l 2>/dev/null | grep -v 'backup.sh'; echo "$LINE" ) | crontab -

echo "Cronjob installed:"
echo "$LINE"
