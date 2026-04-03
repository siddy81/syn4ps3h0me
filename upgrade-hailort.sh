#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_HAILORT_VERSION="5.2.0"
DO_REBOOT="${DO_REBOOT:-0}"

SERVICE_USER="${SUDO_USER:-$USER}"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
UPGRADE_DIR="${SERVICE_HOME}/hailo-upg"
MANUAL_DEB_DIR="${UPGRADE_DIR}/manual-debs"

PKG_HAILORT="hailort_${TARGET_HAILORT_VERSION}_arm64.deb"
PKG_PCIE="hailort-pcie-driver_${TARGET_HAILORT_VERSION}_all.deb"

FILE_HAILORT="${MANUAL_DEB_DIR}/${PKG_HAILORT}"
FILE_PCIE="${MANUAL_DEB_DIR}/${PKG_PCIE}"

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
  local target="$1"
  local label="$2"
  local found=1

  if [[ -f "${target}" ]]; then
    [[ -s "${target}" ]] || die "Datei ist leer: ${target}"
    dpkg-deb -I "${target}" >/dev/null 2>&1 || die "Ungültige .deb-Datei: ${target}"
    log "$label gefunden: ${target}"
    found=0
  else
    log "WARNUNG: $label nicht gefunden (${target}) — wird übersprungen."
  fi

  return "${found}"
}

main() {
  require_root
  check_architecture
  require_command apt-get
  require_command dpkg
  require_command dpkg-deb
  require_command getent
  require_command cut
  require_command uname

  mkdir -p "$MANUAL_DEB_DIR"
  log "Suche manuell bereitgestellte .deb-Dateien in: ${MANUAL_DEB_DIR}"

  local -a install_files=()
  if download_file "$FILE_HAILORT" "$PKG_HAILORT"; then
    install_files+=("$FILE_HAILORT")
  fi
  if download_file "$FILE_PCIE" "$PKG_PCIE"; then
    install_files+=("$FILE_PCIE")
  fi

  if [[ "${#install_files[@]}" -eq 0 ]]; then
    log "WARNUNG: Keine passenden .deb-Dateien gefunden. Es wurde nichts installiert."
    return 0
  fi

  log "Entferne alte Pakete ..."
  sudo apt remove -y h10-hailort-pcie-driver || true
  sudo apt remove -y h10-hailort || true

  log "Installiere neue Pakete ..."
  sudo dpkg --install "${install_files[@]}"

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
