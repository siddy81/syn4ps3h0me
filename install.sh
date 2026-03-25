#!/usr/bin/env bash
set -Eeuo pipefail

# ============================================================
# Smart-Home + Hailo installer
# - installiert Docker (falls nötig)
# - fügt Benutzer der docker-Gruppe hinzu
# - klont/installiert hailo-apps in ~/workspace/hailo-apps
# - aktiviert setup_env.sh und lädt Whisper-Ressourcen
# - lädt/installiert hailo_gen_ai_model_zoo_5.1.1_arm64.deb
# - legt hailo-ollama als systemd-Service an
# - aktiviert/startet hailo-ollama
# - startet am Ende den Compose-Stack
# ============================================================

# ----------------------------
# Konfiguration
# ----------------------------
SERVICE_USER="siddy"
SERVICE_WORKDIR="/home/siddy"
SERVICE_EXEC="/usr/bin/hailo-ollama"
SERVICE_FILE="/etc/systemd/system/hailo-ollama.service"

DEB_URL="https://dev-public.hailo.ai/2025_12/Hailo10/hailo_gen_ai_model_zoo_5.1.1_arm64.deb"
DEB_FILE="hailo_gen_ai_model_zoo_5.1.1_arm64.deb"

HAILO_APPS_REPO="https://github.com/hailo-ai/hailo-apps.git"

# Script liegt in ~/workspace/Siddys-Shelly-Smart-Home/install.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
WORKSPACE_DIR="$(dirname "${PROJECT_DIR}")"
HAILO_APPS_DIR="${WORKSPACE_DIR}/hailo-apps"

# ----------------------------
# Logging
# ----------------------------
log()  { echo "[INFO]  $*"; }
warn() { echo "[WARN]  $*" >&2; }
fail() { echo "[ERROR] $*" >&2; exit 1; }

# ----------------------------
# Root / sudo
# ----------------------------
require_root_or_sudo() {
  if [[ "${EUID}" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || fail "sudo fehlt."
    SUDO="sudo"
  else
    SUDO=""
  fi
}

detect_real_user() {
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    REAL_USER="${SUDO_USER}"
  else
    REAL_USER="${USER:-${SERVICE_USER}}"
  fi
}

# ----------------------------
# Hailo setup_env helper
# ----------------------------
source_hailo_env() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || fail "setup_env.sh fehlt: ${env_file}"

  set +u
  # shellcheck disable=SC1090
  source "${env_file}"
  set -u
}

# ----------------------------
# Basics
# ----------------------------
install_base_packages() {
  log "Installiere Basis-Pakete ..."
  ${SUDO} apt-get update
  ${SUDO} apt-get install -y curl wget git ca-certificates portaudio19-dev
}

# ----------------------------
# Docker
# ----------------------------
install_docker_if_needed() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker ist bereits installiert."
    return
  fi

  log "Docker fehlt. Lade Docker Convenience Script ..."
  cd "${PROJECT_DIR}"
  curl -fsSL https://get.docker.com -o get-Docker.sh

  log "Installiere Docker ..."
  ${SUDO} sh ./get-Docker.sh

  command -v docker >/dev/null 2>&1 || fail "Docker wurde nicht korrekt installiert."
}

ensure_docker_group_membership() {
  if id -nG "${REAL_USER}" | grep -qw docker; then
    log "Benutzer ${REAL_USER} ist bereits in der docker-Gruppe."
    return
  fi

  log "Füge ${REAL_USER} zur docker-Gruppe hinzu ..."
  ${SUDO} usermod -aG docker "${REAL_USER}"
  warn "Die neue Gruppenmitgliedschaft greift regulär erst nach Re-Login."
  warn "Im Skript unkritisch, da Compose am Ende per sudo gestartet wird."
}

# ----------------------------
# hailo-apps + Whisper
# ----------------------------
setup_hailo_apps_and_whisper() {
  log "Gehe in den übergeordneten Ordner: ${WORKSPACE_DIR}"
  pushd "${WORKSPACE_DIR}" >/dev/null

  if [[ ! -d "hailo-apps/.git" ]]; then
    log "Klonen von hailo-apps nach ${WORKSPACE_DIR}/hailo-apps ..."
    ${SUDO} -u "${REAL_USER}" git clone "${HAILO_APPS_REPO}"
  else
    log "hailo-apps existiert bereits in ${WORKSPACE_DIR}/hailo-apps"
  fi

  cd hailo-apps

  log "Führe sudo ./install.sh aus ..."
  ${SUDO} ./install.sh

  [[ -f "setup_env.sh" ]] || fail "setup_env.sh wurde nicht gefunden in ${PWD}"

  log "Aktiviere hailo-apps Umgebung ..."
  source_hailo_env "${PWD}/setup_env.sh"

  log "Installiere GenAI-Abhängigkeiten ..."
  python3 -m pip install -e '.[gen-ai]'

  if ! command -v hailo-download-resources >/dev/null 2>&1; then
    fail "hailo-download-resources ist nach source setup_env.sh nicht verfügbar."
  fi

  log "Lade Whisper-Ressourcen für Hailo-10H ..."
  hailo-download-resources --group whisper_chat --arch hailo10h

  log "Gehe zurück ins Projektverzeichnis ..."
  popd >/dev/null
}

# ----------------------------
# Hailo GenAI Model Zoo .deb
# ----------------------------
download_deb_if_needed() {
  cd "${PROJECT_DIR}"

  if [[ -f "${DEB_FILE}" ]]; then
    log "${DEB_FILE} ist bereits vorhanden."
    return
  fi

  log "Lade ${DEB_FILE} herunter ..."
  wget -O "${DEB_FILE}" "${DEB_URL}"
}

install_hailo_ollama_if_needed() {
  cd "${PROJECT_DIR}"

  if command -v hailo-ollama >/dev/null 2>&1; then
    log "hailo-ollama ist bereits installiert."
    return
  fi

  log "Installiere ${DEB_FILE} ..."
  ${SUDO} dpkg -i "./${DEB_FILE}" || true

  log "Behebe ggf. Abhängigkeiten ..."
  ${SUDO} apt-get update
  ${SUDO} apt-get -f install -y

  command -v hailo-ollama >/dev/null 2>&1 || fail "hailo-ollama wurde nach der Installation nicht gefunden."
}

# ----------------------------
# systemd service
# ----------------------------
write_hailo_service() {
  local tmpfile
  tmpfile="$(mktemp)"

  cat > "${tmpfile}" <<EOF
[Unit]
Description=Hailo Ollama Backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${SERVICE_WORKDIR}
ExecStart=${SERVICE_EXEC}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  if [[ -f "${SERVICE_FILE}" ]] && cmp -s "${tmpfile}" "${SERVICE_FILE}"; then
    log "Service-Datei ist bereits aktuell."
    rm -f "${tmpfile}"
    return
  fi

  log "Schreibe ${SERVICE_FILE} ..."
  ${SUDO} install -m 0644 "${tmpfile}" "${SERVICE_FILE}"
  rm -f "${tmpfile}"
}

enable_and_start_hailo_service() {
  log "Aktiviere und starte hailo-ollama.service ..."
  ${SUDO} systemctl daemon-reload
  ${SUDO} systemctl enable hailo-ollama.service
  ${SUDO} systemctl restart hailo-ollama.service
}

wait_for_hailo_ollama() {
  log "Warte auf hailo-ollama API ..."
  local retries=25
  local i
  for ((i=1; i<=retries; i++)); do
    if curl --silent --fail "http://localhost:8000/hailo/v1/list" >/dev/null 2>&1; then
      log "hailo-ollama antwortet auf Port 8000."
      return
    fi
    sleep 1
  done
  warn "hailo-ollama antwortet noch nicht auf http://localhost:8000/hailo/v1/list"
}

# ----------------------------
# Docker Compose
# ----------------------------
compose_up() {
  cd "${PROJECT_DIR}"

  if [[ ! -f "docker-compose.yml" && ! -f "docker-compose.yaml" && ! -f "compose.yml" && ! -f "compose.yaml" ]]; then
    fail "Keine Compose-Datei in ${PROJECT_DIR} gefunden."
  fi

  if ${SUDO} docker compose version >/dev/null 2>&1; then
    log "Starte Compose-Stack mit docker compose up -d ..."
    ${SUDO} docker compose up -d
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    log "Starte Compose-Stack mit docker-compose up -d ..."
    ${SUDO} docker-compose up -d
    return
  fi

  fail "Weder 'docker compose' noch 'docker-compose' ist verfügbar."
}

# ----------------------------
# Summary
# ----------------------------
summary() {
  echo
  echo "============================================================"
  echo "FERTIG"
  echo "============================================================"
  echo "Docker:"
  ${SUDO} docker --version || true
  echo
  echo "Projektverzeichnis:"
  echo "${PROJECT_DIR}"
  echo
  echo "Workspace:"
  echo "${WORKSPACE_DIR}"
  echo
  echo "hailo-apps Dir:"
  echo "${HAILO_APPS_DIR}"
  echo
  echo "hailo-ollama:"
  command -v hailo-ollama || true
  echo
  echo "hailo-ollama Service enabled:"
  ${SUDO} systemctl is-enabled hailo-ollama.service || true
  echo
  echo "hailo-ollama Service active:"
  ${SUDO} systemctl is-active hailo-ollama.service || true
  echo
  echo "hailo API:"
  curl --silent "http://localhost:8000/hailo/v1/list" || true
  echo
  echo "hailo-download-resources:"
  bash -lc "
    set +u
    cd '${HAILO_APPS_DIR}' 2>/dev/null || exit 0
    source setup_env.sh 2>/dev/null || exit 0
    set -u
    command -v hailo-download-resources || true
  "
  echo
  echo "Whisper-Dateien:"
  find /usr/local/hailo/resources -iname '*whisper*' 2>/dev/null || true
  echo "============================================================"
}

main() {
  require_root_or_sudo
  detect_real_user
  install_base_packages
  install_docker_if_needed
  ensure_docker_group_membership

  setup_hailo_apps_and_whisper

  download_deb_if_needed
  install_hailo_ollama_if_needed
  write_hailo_service
  enable_and_start_hailo_service
  wait_for_hailo_ollama

  compose_up
  summary
}

main "$@"