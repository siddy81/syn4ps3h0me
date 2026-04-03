#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_HAILORT_VERSION="5.2.0"
DO_REBOOT="${DO_REBOOT:-0}"

SERVICE_USER="${SUDO_USER:-$USER}"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
UPGRADE_DIR="${SERVICE_HOME}/hailo-upg"

PKG_HAILORT="hailort_${TARGET_HAILORT_VERSION}_arm64.deb"
PKG_PCIE="hailort-pcie-driver_${TARGET_HAILORT_VERSION}_all.deb"

PUBLIC_HAILO_DEB_BASE_URL="https://dev-public.hailo.ai/2026_01/Hailo10"
HAILORT_DEB_URL="${PUBLIC_HAILO_DEB_BASE_URL}/${PKG_HAILORT}"
PCIE_DRIVER_DEB_URL="${PUBLIC_HAILO_DEB_BASE_URL}/${PKG_PCIE}"

FILE_HAILORT="${UPGRADE_DIR}/${PKG_HAILORT}"
FILE_PCIE="${UPGRADE_DIR}/${PKG_PCIE}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

trap 'die "Abbruch in Zeile ${LINENO}."' ERR

require_root() {
  [[ $EUID -eq 0 ]] || die "Bitte mit sudo/root ausführen."
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Benötigtes Kommando fehlt: $1"
}

check_architecture() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    aarch64|arm64) ;;
    *) die "Nur für ARM64/aarch64 gedacht. Gefunden: $arch" ;;
  esac
}

download_file() {
  local url="$1"
  local target="$2"
  local label="$3"

  if [[ -f "$target" ]]; then
    log "$label bereits vorhanden: $target"
    return 0
  fi

  log "Lade $label herunter: $url"
  curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -o "$target" "$url" \
    || die "Download fehlgeschlagen für $label über $url"

  [[ -s "$target" ]] || die "Leere Datei heruntergeladen: $target"
  dpkg-deb -I "$target" >/dev/null 2>&1 || die "Ungültige .deb-Datei: $target"
}

main() {
  require_root
  check_architecture
  require_command apt-get
  require_command dpkg
  require_command dpkg-deb
  require_command curl
  require_command getent
  require_command cut
  require_command uname

  mkdir -p "$UPGRADE_DIR"
  cd "$UPGRADE_DIR"

  download_file "$HAILORT_DEB_URL" "$FILE_HAILORT" "$PKG_HAILORT"
  download_file "$PCIE_DRIVER_DEB_URL" "$FILE_PCIE" "$PKG_PCIE"

  log "Entferne alte Pakete ..."
  sudo apt remove -y h10-hailort-pcie-driver || true
  sudo apt remove -y h10-hailort || true

  log "Installiere neue Pakete ..."
  sudo dpkg --install \
    "$FILE_HAILORT" \
    "$FILE_PCIE"

  log "Installiere rpicam-apps-hailo-postprocess neu ..."
  sudo apt install -y rpicam-apps-hailo-postprocess

  log "Prüfe Installation ..."
  hailortcli fw-control identify || log "WARNUNG: hailortcli fw-control identify war nicht erfolgreich."

  if [[ "$DO_REBOOT" == "1" ]]; then
    log "Reboot ..."
    sudo reboot
  else
    log "Fertig. Bitte jetzt manuell neu starten: sudo reboot"
  fi
}

main "$@"
