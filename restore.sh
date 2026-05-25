#!/usr/bin/env bash
set -euo pipefail

# syn4ps3h0me restore script
# Manual-only execution with safety prompt.
# Restores:
# - InfluxDB logical backup (if present)
# - Docker volumes (influxdb_data, influxdb_config, mosquitto_data, mosquitto_log)

if [[ "${AUTO_RESTORE:-}" == "1" ]]; then
  echo "ERROR: AUTO_RESTORE is not allowed. Run this script manually." >&2
  exit 1
fi

if [[ -t 0 ]]; then
  :
else
  echo "ERROR: restore.sh requires an interactive terminal (manual execution only)." >&2
  exit 1
fi

BACKUP_ROOT="${BACKUP_ROOT:-$PWD/backups}"
INFLUX_CONTAINER="${INFLUX_CONTAINER:-influx-db}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

usage() {
  cat <<USAGE
Usage:
  ./restore.sh <backup-folder>
  ./restore.sh latest

Examples:
  ./restore.sh backups/2026-05-25_03-00-00
  ./restore.sh latest

Environment overrides:
  BACKUP_ROOT (default: ./backups)
  INFLUX_CONTAINER (default: influx-db)
  COMPOSE_FILE (default: docker-compose.yml)
USAGE
}

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

require_cmd docker
require_cmd tar

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

arg="$1"
if [[ "$arg" == "latest" ]]; then
  BACKUP_DIR="$BACKUP_ROOT/latest"
else
  BACKUP_DIR="$arg"
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "ERROR: backup directory not found: $BACKUP_DIR" >&2
  exit 1
fi

log "Selected backup: $BACKUP_DIR"
read -r -p "This will overwrite live data. Type RESTORE to continue: " confirm
if [[ "$confirm" != "RESTORE" ]]; then
  echo "Aborted."
  exit 1
fi

# Stop services to avoid write activity during volume restore
log "Stopping stack"
docker compose -f "$COMPOSE_FILE" down

restore_volume() {
  local volume="$1"
  local tarfile="$BACKUP_DIR/${volume}.tar.gz"

  if [[ ! -f "$tarfile" ]]; then
    log "WARN: $tarfile not found, skipping volume $volume"
    return
  fi

  log "Restoring volume $volume from $(basename "$tarfile")"
  docker run --rm -v "$volume":/to alpine sh -c 'rm -rf /to/* /to/.[!.]* /to/..?* || true'
  docker run --rm -v "$volume":/to -v "$BACKUP_DIR":/from alpine sh -c "cd /to && tar xzf /from/${volume}.tar.gz"
}

restore_volume influxdb_data
restore_volume influxdb_config
restore_volume mosquitto_data
restore_volume mosquitto_log

log "Starting only InfluxDB for logical restore phase"
docker compose -f "$COMPOSE_FILE" up -d influxdb
sleep 5

if [[ -d "$BACKUP_DIR/influx-logical" ]]; then
  log "Running InfluxDB logical restore"
  docker cp "$BACKUP_DIR/influx-logical" "$INFLUX_CONTAINER":/tmp/restore
  docker exec "$INFLUX_CONTAINER" sh -lc 'influx restore /tmp/restore/influx-backup || influx restore /tmp/restore'
else
  log "No influx-logical folder found, skipping logical restore"
fi

log "Starting full stack"
docker compose -f "$COMPOSE_FILE" up -d

log "Restore completed"
