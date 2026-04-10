#!/usr/bin/env bash
set -Eeuo pipefail

# ============================================================
# Modularer Uninstaller
# - entfernt ausgewählte Compose-Services + zugehörige Volumes
# - entfernt optional Hailo/Ollama Komponenten
# - kann optional Docker komplett entfernen (bei "Alles")
# ============================================================

SERVICE_FILE="/etc/systemd/system/hailo-ollama.service"
HAILO_DEB_PACKAGE="hailo-gen-ai-model-zoo"

MODULE_SMARTHOME=false
MODULE_PIHOLE=false
MODULE_CADDY=false
MODULE_VOICE=false
MODULE_LLM_CHAT=false
REMOVE_DOCKER=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
WORKSPACE_DIR="$(dirname "${PROJECT_DIR}")"
HAILO_APPS_DIR="${WORKSPACE_DIR}/hailo-apps"

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

require_root_or_sudo() {
  if [[ "${EUID}" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || fail "sudo fehlt."
    SUDO="sudo"
  else
    SUDO=""
  fi
}

has_compose() {
  if ${SUDO} docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=("${SUDO}" docker compose)
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=("${SUDO}" docker-compose)
    return 0
  fi

  return 1
}

select_modules() {
  local uninstall_all=false

  echo
  echo "============================================================"
  echo "Deinstallationsauswahl"
  echo "============================================================"
  echo "Bitte auswählen, welche Module entfernt werden sollen:"
  echo

  if ask_module "Alles deinstallieren (inkl. Docker)"; then
    uninstall_all=true
  fi

  if [[ "${uninstall_all}" == "true" ]]; then
    MODULE_SMARTHOME=true
    MODULE_PIHOLE=true
    MODULE_CADDY=true
    MODULE_VOICE=true
    MODULE_LLM_CHAT=true
    REMOVE_DOCKER=true
    log "Option 'Alles deinstallieren (inkl. Docker)' gewählt."
    return
  fi

  if ask_module "1) Smart Home Shelly Überwachung (mosquitto, influxdb, telegraf, grafana)"; then
    MODULE_SMARTHOME=true
  fi

  if ask_module "2) Pi-hole"; then
    MODULE_PIHOLE=true
  fi

  if ask_module "3) Caddy"; then
    MODULE_CADDY=true
  fi

  if ask_module "4) Voice Pipeline"; then
    MODULE_VOICE=true
  fi

  if ask_module "5) LLM-Chat (open-webui, hailo-ollama, model download)"; then
    MODULE_LLM_CHAT=true
  fi

  if [[ "${MODULE_SMARTHOME}" == "false" && "${MODULE_PIHOLE}" == "false" && "${MODULE_CADDY}" == "false" && "${MODULE_VOICE}" == "false" && "${MODULE_LLM_CHAT}" == "false" ]]; then
    warn "Kein Modul ausgewählt. Es wird nichts deinstalliert."
  fi
}

compose_stop_and_remove_service() {
  local service="$1"

  if ! has_compose; then
    warn "Docker Compose nicht gefunden. Service '${service}' kann nicht automatisch entfernt werden."
    return
  fi

  cd "${PROJECT_DIR}"
  "${COMPOSE_CMD[@]}" stop "${service}" >/dev/null 2>&1 || true
  "${COMPOSE_CMD[@]}" rm -fsv "${service}" >/dev/null 2>&1 || true
  log "Compose-Service entfernt: ${service}"
}

remove_volume_if_exists() {
  local volume="$1"
  if ! command -v docker >/dev/null 2>&1; then
    return
  fi

  if ${SUDO} docker volume inspect "${volume}" >/dev/null 2>&1; then
    ${SUDO} docker volume rm "${volume}" >/dev/null 2>&1 || warn "Volume konnte nicht entfernt werden: ${volume}"
    log "Volume entfernt: ${volume}"
  fi
}

uninstall_smarthome() {
  log "Deinstalliere Modul: Smart Home Shelly Überwachung"
  compose_stop_and_remove_service mosquitto
  compose_stop_and_remove_service influxdb
  compose_stop_and_remove_service telegraf
  compose_stop_and_remove_service grafana

  remove_volume_if_exists "syn4ps3h0me_mosquitto_data"
  remove_volume_if_exists "syn4ps3h0me_mosquitto_log"
  remove_volume_if_exists "syn4ps3h0me_influxdb_data"
  remove_volume_if_exists "syn4ps3h0me_influxdb_config"
  remove_volume_if_exists "syn4ps3h0me_grafana_data"
}

uninstall_pihole() {
  log "Deinstalliere Modul: Pi-hole"
  compose_stop_and_remove_service pihole
}

uninstall_caddy() {
  log "Deinstalliere Modul: Caddy"
  compose_stop_and_remove_service caddy
  remove_volume_if_exists "syn4ps3h0me_caddy_data"
}

uninstall_voice_pipeline() {
  log "Deinstalliere Modul: Voice Pipeline"
  compose_stop_and_remove_service voice-pipeline

  if command -v docker >/dev/null 2>&1; then
    ${SUDO} docker image rm syn4ps3h0me-voice-pipeline >/dev/null 2>&1 || true
  fi
}

uninstall_llm_chat() {
  log "Deinstalliere Modul: LLM-Chat"
  compose_stop_and_remove_service open-webui
  remove_volume_if_exists "syn4ps3h0me_open-webui"

  if ${SUDO} systemctl list-unit-files | grep -q '^hailo-ollama\.service'; then
    ${SUDO} systemctl disable --now hailo-ollama.service >/dev/null 2>&1 || true
  fi

  if [[ -f "${SERVICE_FILE}" ]]; then
    ${SUDO} rm -f "${SERVICE_FILE}"
    ${SUDO} systemctl daemon-reload
    log "Systemd-Service entfernt: hailo-ollama.service"
  fi

  if command -v hailo-ollama >/dev/null 2>&1; then
    ${SUDO} apt-get remove -y "${HAILO_DEB_PACKAGE}" >/dev/null 2>&1 || warn "Paket ${HAILO_DEB_PACKAGE} konnte nicht automatisch entfernt werden."
    ${SUDO} apt-get autoremove -y >/dev/null 2>&1 || true
  fi

  rm -f "${PROJECT_DIR}/hailo_gen_ai_model_zoo_5.1.1_arm64.deb" || true
}

remove_docker_completely() {
  log "Entferne Docker vollständig ..."

  if command -v docker >/dev/null 2>&1; then
    ${SUDO} docker ps -aq | xargs -r ${SUDO} docker rm -f >/dev/null 2>&1 || true
    ${SUDO} docker volume ls -q | xargs -r ${SUDO} docker volume rm >/dev/null 2>&1 || true
    ${SUDO} docker network prune -f >/dev/null 2>&1 || true
  fi

  ${SUDO} apt-get remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-compose >/dev/null 2>&1 || true
  ${SUDO} apt-get purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-compose >/dev/null 2>&1 || true
  ${SUDO} apt-get autoremove -y >/dev/null 2>&1 || true

  ${SUDO} rm -rf /var/lib/docker /var/lib/containerd || true
  log "Docker wurde entfernt (soweit vorhanden)."
}

summary() {
  echo
  echo "============================================================"
  echo "DEINSTALLATION FERTIG"
  echo "============================================================"
  echo "Projektverzeichnis: ${PROJECT_DIR}"
  echo "hailo-apps Verzeichnis: ${HAILO_APPS_DIR}"
  echo
  echo "Ausgewählte Module:"
  [[ "${MODULE_SMARTHOME}" == "true" ]] && echo "- Smart Home Shelly Überwachung"
  [[ "${MODULE_PIHOLE}" == "true" ]] && echo "- Pi-hole"
  [[ "${MODULE_CADDY}" == "true" ]] && echo "- Caddy"
  [[ "${MODULE_VOICE}" == "true" ]] && echo "- Voice Pipeline"
  [[ "${MODULE_LLM_CHAT}" == "true" ]] && echo "- LLM-Chat"
  [[ "${REMOVE_DOCKER}" == "true" ]] && echo "- Docker komplett entfernt"
  echo "============================================================"
}

main() {
  require_root_or_sudo
  select_modules

  [[ "${MODULE_SMARTHOME}" == "true" ]] && uninstall_smarthome
  [[ "${MODULE_PIHOLE}" == "true" ]] && uninstall_pihole
  [[ "${MODULE_CADDY}" == "true" ]] && uninstall_caddy
  [[ "${MODULE_VOICE}" == "true" ]] && uninstall_voice_pipeline
  [[ "${MODULE_LLM_CHAT}" == "true" ]] && uninstall_llm_chat
  [[ "${REMOVE_DOCKER}" == "true" ]] && remove_docker_completely

  summary
}

main "$@"
