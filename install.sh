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
DEFAULT_LLM_MODEL="llama3.2:3b"
ACTIVE_LLM_MODEL="${DEFAULT_LLM_MODEL}"

HAILO_APPS_REPO="https://github.com/hailo-ai/hailo-apps.git"

MODULE_SMARTHOME=false
MODULE_PIHOLE=false
MODULE_CADDY=false
MODULE_VOICE=false
MODULE_LLM_CHAT=false

declare -a COMPOSE_SERVICES=()

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

is_yes() {
  local answer="${1:-}"
  [[ "${answer}" =~ ^([JjYy]|[Jj][Aa]|[Yy][Ee][Ss])$ ]]
}

ask_module() {
  local prompt="$1"
  local answer=""
  read -r -p "${prompt} [j/N]: " answer
  is_yes "${answer}"
}

upsert_env_key() {
  local key="$1"
  local value="$2"
  local env_file="$3"

  [[ -f "${env_file}" ]] || return

  if grep -qE "^${key}=" "${env_file}"; then
    awk -v k="${key}" -v v="${value}" '
      BEGIN { replaced=0 }
      $0 ~ ("^" k "=") { print k "=" v; replaced=1; next }
      { print }
      END { if (!replaced) print k "=" v }
    ' "${env_file}" > "${env_file}.tmp"
    mv "${env_file}.tmp" "${env_file}"
  else
    echo "${key}=${value}" >> "${env_file}"
  fi
}

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

repair_system_packages() {
  log "Prüfe/repairiere ggf. Paketstatus (dpkg/apt) ..."
  ${SUDO} dpkg --configure -a || true
  ${SUDO} apt -f install -y || true
  ${SUDO} apt-get update
  ${SUDO} apt-get full-upgrade -y || true
  ${SUDO} apt-get clean || true
  ${SUDO} apt-get autoclean || true
  ${SUDO} apt-get autoremove -y || true
}

select_modules() {
  local install_all=false

  echo
  echo "============================================================"
  echo "Modulauswahl"
  echo "============================================================"
  echo "Docker/Basis wird immer installiert."
  echo "Bitte auswählen, welche Module installiert werden sollen:"
  echo

  if ask_module "Alles installieren (alle Module)"; then
    install_all=true
  fi

  if [[ "${install_all}" == "true" ]]; then
    MODULE_SMARTHOME=true
    MODULE_PIHOLE=true
    MODULE_CADDY=true
    MODULE_VOICE=true
    MODULE_LLM_CHAT=true
    COMPOSE_SERVICES+=(mosquitto influxdb telegraf grafana pihole caddy voice-pipeline open-webui)
    log "Option 'Alles installieren' gewählt."
  else

    if ask_module "1) Smart Home Shelly Überwachung (mosquitto, influxdb, telegraf, grafana)"; then
      MODULE_SMARTHOME=true
      COMPOSE_SERVICES+=(mosquitto influxdb telegraf grafana)
    fi

    if ask_module "2) Pi-hole"; then
      MODULE_PIHOLE=true
      COMPOSE_SERVICES+=(pihole)
    fi

    if ask_module "3) Caddy"; then
      MODULE_CADDY=true
      COMPOSE_SERVICES+=(caddy)
    fi

    if ask_module "4) Voice Pipeline"; then
      MODULE_VOICE=true
      COMPOSE_SERVICES+=(voice-pipeline)
    fi

    if ask_module "5) LLM-Chat (open-webui, hailo-ollama, model download)"; then
      MODULE_LLM_CHAT=true
      COMPOSE_SERVICES+=(open-webui)
    fi
  fi

  if [[ ${#COMPOSE_SERVICES[@]} -eq 0 ]]; then
    warn "Kein Modul ausgewählt. Es wird nur Docker/Basis installiert."
  else
    mapfile -t COMPOSE_SERVICES < <(printf "%s\n" "${COMPOSE_SERVICES[@]}" | awk '!seen[$0]++')
    log "Ausgewählte Compose-Services: ${COMPOSE_SERVICES[*]}"
  fi
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
  if ! ${SUDO} ./install.sh; then
    warn "hailo-apps install.sh meldete Fehler. Versuche automatische Reparatur für fehlende Hailo-Komponenten ..."
    if [[ -x "./scripts/hailo_installer.sh" ]]; then
      log "Starte ./scripts/hailo_installer.sh ..."
      ${SUDO} ./scripts/hailo_installer.sh
      log "Starte hailo-apps ./install.sh erneut ..."
      ${SUDO} ./install.sh
    else
      fail "hailo-apps Installation fehlgeschlagen und ./scripts/hailo_installer.sh wurde nicht gefunden."
    fi
  fi

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
  ${SUDO} dpkg --configure -a || true
  ${SUDO} apt-get update
  ${SUDO} apt-get -f install -y

  command -v hailo-ollama >/dev/null 2>&1 || fail "hailo-ollama wurde nach der Installation nicht gefunden."
}

install_hailo_h10_stack() {
  log "Installiere Hailo-Basispakete (dkms, hailo-h10-all) ..."
  ${SUDO} apt-get update
  ${SUDO} apt-get install -y dkms
  ${SUDO} apt-get install -y hailo-h10-all

  if ! command -v hailortcli >/dev/null 2>&1; then
    warn "hailortcli wurde nicht gefunden. Versuche HailoRT nachzuinstallieren ..."
    ${SUDO} apt-get install -y hailort || true
  fi
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

ensure_default_llm_model() {
  log "Prüfe, ob Standardmodell ${DEFAULT_LLM_MODEL} verfügbar ist ..."
  local tags_json
  if ! tags_json="$(curl --silent --show-error --fail "http://localhost:8000/api/tags" 2>/dev/null)"; then
    warn "Konnte Modellliste nicht über http://localhost:8000/api/tags lesen. Überspringe Standardmodell-Prüfung."
    return
  fi

  if grep -Eq "\"name\"[[:space:]]*:[[:space:]]*\"${DEFAULT_LLM_MODEL}\"|\"${DEFAULT_LLM_MODEL}\"" <<<"${tags_json}"; then
    log "Standardmodell ${DEFAULT_LLM_MODEL} ist bereits vorhanden."
    ACTIVE_LLM_MODEL="${DEFAULT_LLM_MODEL}"
    return
  fi

  log "Lade Standardmodell ${DEFAULT_LLM_MODEL} über die lokale Hailo-Ollama API ..."
  if ! curl --silent \
      "http://localhost:8000/api/pull" \
      -H "Content-Type: application/json" \
      -d "{ \"model\": \"${DEFAULT_LLM_MODEL}\", \"stream\" : true }" >/dev/null; then
    warn "Download von ${DEFAULT_LLM_MODEL} fehlgeschlagen. Installation läuft weiter; bitte Modell ggf. manuell laden."
    return
  fi

  if curl --silent --fail \
      "http://localhost:8000/api/chat" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${DEFAULT_LLM_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Translate to French: The cat is on the table.\"}]}" >/dev/null; then
    ACTIVE_LLM_MODEL="${DEFAULT_LLM_MODEL}"
    log "Modelltest über /api/chat erfolgreich."
    return
  fi

  warn "Modelltest über /api/chat ist fehlgeschlagen. Bitte Modell-/Backend-Status prüfen."
}


ensure_voice_env_defaults() {
  cd "${PROJECT_DIR}"

  [[ -f ".env" ]] || return

  local uid gid
  uid="$(id -u "${REAL_USER}" 2>/dev/null || id -u)"
  gid="$(id -g "${REAL_USER}" 2>/dev/null || id -g)"

  local defaults=(
    "VOICE_HOST_UID=${uid}"
    "VOICE_HOST_GID=${gid}"
    "VOICE_WAKEWORD_MODEL=jarvis"
    "VOICE_WAKEWORD_MODEL_PATH="
    "VOICE_WAKE_WORD_THRESHOLD=0.5"
    "VOICE_WAKE_EVENT_COOLDOWN_SECONDS=2.0"
    "VOICE_POST_WAKE_RECORD_SECONDS=6"
    "VOICE_HAILO_APPS_DIR=/home/siddy/workspace/hailo-apps"
    "VOICE_HAILO_VENV_PYTHON=/home/siddy/workspace/hailo-apps/venv_hailo_apps/bin/python"
    "VOICE_WHISPER_BACKEND=hailo_local_cmd"
    "VOICE_HAILO_WHISPER_CMD=cd /home/siddy/workspace/hailo-apps && source setup_env.sh && /home/siddy/workspace/hailo-apps/venv_hailo_apps/bin/python -m hailo_apps.python.gen_ai_apps.simple_whisper_chat.simple_whisper_chat --audio-file {audio_path} --language {language}"
    "VOICE_HAILO_WHISPER_CMD_TIMEOUT=120"
    "VOICE_WHISPER_MODEL=tiny"
    "VOICE_WHISPER_COMPUTE_TYPE=int8"
    "VOICE_WHISPER_LANGUAGE=de"
    "VOICE_AUDIO_SAMPLE_RATE=16000"
    "VOICE_AUDIO_DEVICE_REFRESH_SECONDS=30"
    "OPEN_WEBUI_PORT=3000"
    "OPEN_WEBUI_IMAGE=ghcr.io/open-webui/open-webui:main"
    "OPEN_WEBUI_OLLAMA_BASE_URL=http://127.0.0.1:8000"
    "OPEN_WEBUI_ENABLE_PERSISTENT_CONFIG=false"
    "OPEN_WEBUI_DEFAULT_MODELS=${ACTIVE_LLM_MODEL}"
  )

  local entry key
  for entry in "${defaults[@]}"; do
    key="${entry%%=*}"
    if ! grep -qE "^${key}=" .env; then
      echo "${entry}" >> .env
      log "Ergänze fehlende .env Vorgabe: ${key}"
    fi
  done

  upsert_env_key "OPEN_WEBUI_DEFAULT_MODELS" "${ACTIVE_LLM_MODEL}" ".env"
  upsert_env_key "OPEN_WEBUI_OLLAMA_BASE_URL" "http://127.0.0.1:8000" ".env"
  upsert_env_key "OPEN_WEBUI_IMAGE" "ghcr.io/open-webui/open-webui:main" ".env"
  log "Setze OPEN_WEBUI_DEFAULT_MODELS auf ${ACTIVE_LLM_MODEL}"
}

build_voice_service_image() {
  cd "${PROJECT_DIR}"

  if [[ ! -f "voice-pipeline/Dockerfile" ]]; then
    warn "Voice-Pipeline Dockerfile fehlt; Image-Build wird übersprungen."
    return
  fi

  log "Baue Voice-Pipeline Image (autostart-ready) ..."
  ${SUDO} docker compose build voice-pipeline
}

# ----------------------------
# Voice pipeline preflight
# ----------------------------
voice_pipeline_preflight() {
  cd "${PROJECT_DIR}"

  if [[ ! -f "voice-pipeline/Dockerfile" ]]; then
    warn "voice-pipeline/Dockerfile fehlt. Voice-Container kann nicht gebaut werden."
    return
  fi

  if [[ ! -d "/dev/snd" ]]; then
    warn "/dev/snd wurde auf dem Host nicht gefunden. Audio-Capture im Voice-Container ist dann nicht möglich."
  else
    log "Audio-Geräte-Node /dev/snd vorhanden."
  fi

  local user_uid
  user_uid="$(id -u "${REAL_USER}" 2>/dev/null || id -u)"
  local voice_runtime_dir="/run/user/${user_uid}"
  if [[ -d "${voice_runtime_dir}" ]]; then
    log "PipeWire Runtime-Verzeichnis gefunden: ${voice_runtime_dir}"
  else
    warn "PipeWire Runtime-Verzeichnis fehlt: ${voice_runtime_dir}"
  fi

  if [[ -S "${voice_runtime_dir}/pipewire-0" ]]; then
    log "PipeWire Socket gefunden: ${voice_runtime_dir}/pipewire-0"
  else
    warn "PipeWire Socket nicht gefunden: ${voice_runtime_dir}/pipewire-0"
  fi

  if ! ${SUDO} docker compose config >/dev/null 2>&1; then
    fail "docker compose config fehlgeschlagen (inkl. Voice-Pipeline)."
  fi

  log "Compose-Konfiguration inkl. Voice-Pipeline ist gültig."
}

# ----------------------------
# Docker Compose
# ----------------------------
compose_up() {
  cd "${PROJECT_DIR}"

  if [[ ! -f "docker-compose.yml" && ! -f "docker-compose.yaml" && ! -f "compose.yml" && ! -f "compose.yaml" ]]; then
    fail "Keine Compose-Datei in ${PROJECT_DIR} gefunden."
  fi

  if [[ ${#COMPOSE_SERVICES[@]} -eq 0 ]]; then
    log "Keine Compose-Services ausgewählt. Überspringe docker compose up."
    return
  fi

  if ${SUDO} docker compose version >/dev/null 2>&1; then
    log "Starte ausgewählte Compose-Services mit docker compose up -d ..."
    ${SUDO} docker compose up -d "${COMPOSE_SERVICES[@]}"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    log "Starte ausgewählte Compose-Services mit docker-compose up -d ..."
    ${SUDO} docker-compose up -d "${COMPOSE_SERVICES[@]}"
    return
  fi

  fail "Weder 'docker compose' noch 'docker-compose' ist verfügbar."
}

ensure_open_webui_runtime() {
  cd "${PROJECT_DIR}"

  if [[ "${MODULE_LLM_CHAT}" != "true" ]]; then
    return
  fi

  log "Ziehe Open WebUI Image (main) ..."
  ${SUDO} docker pull ghcr.io/open-webui/open-webui:main || warn "Konnte Open WebUI Image nicht aktualisieren."

  if ${SUDO} docker compose version >/dev/null 2>&1; then
    log "Recreate open-webui mit Compose ..."
    ${SUDO} docker compose up -d --force-recreate open-webui || warn "Compose-Recreate für open-webui fehlgeschlagen."
  elif command -v docker-compose >/dev/null 2>&1; then
    log "Recreate open-webui mit docker-compose ..."
    ${SUDO} docker-compose up -d --force-recreate open-webui || warn "docker-compose Recreate für open-webui fehlgeschlagen."
  fi
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
  if [[ "${MODULE_LLM_CHAT}" == "true" ]]; then
    echo "hailo-ollama Service enabled:"
    ${SUDO} systemctl is-enabled hailo-ollama.service || true
    echo
    echo "hailo-ollama Service active:"
    ${SUDO} systemctl is-active hailo-ollama.service || true
    echo
    echo "hailo API:"
    curl --silent "http://localhost:8000/hailo/v1/list" || true
    echo
    echo "Hailo Modelle:"
    curl --silent "http://localhost:8000/hailo/v1/list" || true
    echo
  fi

  if [[ "${MODULE_VOICE}" == "true" ]]; then
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
    echo
    echo "Voice-Pipeline files:"
    ls -1 "${PROJECT_DIR}/voice-pipeline" 2>/dev/null || true
  fi
  echo
  echo "Installierte/Ausgewählte Compose-Services:"
  if [[ ${#COMPOSE_SERVICES[@]} -eq 0 ]]; then
    echo "(keine)"
  else
    printf -- "- %s\n" "${COMPOSE_SERVICES[@]}"
  fi
  echo "============================================================"
}

main() {
  require_root_or_sudo
  detect_real_user
  select_modules
  install_base_packages
  install_docker_if_needed
  ensure_docker_group_membership

  if [[ "${MODULE_VOICE}" == "true" ]]; then
    setup_hailo_apps_and_whisper
  fi

  if [[ "${MODULE_LLM_CHAT}" == "true" ]]; then
    repair_system_packages
    install_hailo_h10_stack
    download_deb_if_needed
    install_hailo_ollama_if_needed
    write_hailo_service
    enable_and_start_hailo_service
    wait_for_hailo_ollama
    ensure_default_llm_model
  fi

  if [[ "${MODULE_VOICE}" == "true" || "${MODULE_LLM_CHAT}" == "true" ]]; then
    ensure_voice_env_defaults
  fi

  if [[ "${MODULE_VOICE}" == "true" ]]; then
    voice_pipeline_preflight
    build_voice_service_image
  fi

  compose_up
  ensure_open_webui_runtime
  summary
}

main "$@"
