#!/usr/bin/env bash
set -euo pipefail

# syn4ps3h0me backup script
# - Creates InfluxDB logical backups (best for restore/migration)
# - Creates Docker volume archives for InfluxDB + Mosquitto (full safety net)
# - Rotates old backups

BACKUP_ROOT="${BACKUP_ROOT:-$PWD/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date +%F_%H-%M-%S)"
TARGET_DIR="$BACKUP_ROOT/$TIMESTAMP"
LATEST_LINK="$BACKUP_ROOT/latest"

# Compose/container names used by this repository
INFLUX_CONTAINER="${INFLUX_CONTAINER:-influx-db}"

# Volumes from docker-compose.yml
VOLUMES=(
  influxdb_data
  influxdb_config
  mosquitto_data
  mosquitto_log
)

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
require_cmd find
mkdir -p "$TARGET_DIR"

log "Starting backup into $TARGET_DIR"

# 1) Influx logical backup
log "Running InfluxDB logical backup"
docker exec "$INFLUX_CONTAINER" sh -lc 'rm -rf /tmp/influx-backup && influx backup /tmp/influx-backup'
docker cp "$INFLUX_CONTAINER":/tmp/influx-backup "$TARGET_DIR/influx-logical"

# 2) Volume tar backups
log "Archiving Docker volumes"
for vol in "${VOLUMES[@]}"; do
  out="$TARGET_DIR/${vol}.tar.gz"
  log " - $vol -> $(basename "$out")"
  docker run --rm \
    -v "$vol":/from:ro \
    -v "$TARGET_DIR":/to \
    alpine sh -c "tar czf /to/${vol}.tar.gz -C /from ."
done

# 3) Metadata for easier restore/troubleshooting
cat > "$TARGET_DIR/backup-meta.txt" <<META
created_at=$(date -Is)
hostname=$(hostname)
influx_container=$INFLUX_CONTAINER
volumes=${VOLUMES[*]}
META

# 4) latest symlink and retention
ln -sfn "$TARGET_DIR" "$LATEST_LINK"

log "Applying retention: removing backup directories older than $RETENTION_DAYS days"
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -print -exec rm -rf {} +

log "Backup completed successfully"
log "Backup location: $TARGET_DIR"
