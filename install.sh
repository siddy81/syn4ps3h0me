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
FUNCTION_CALLING_MODEL="qwen2-1.5b-instruct-function-calling-v1"
ACTIVE_LLM_MODEL="${DEFAULT_LLM_MODEL}"

HAILO_APPS_REPO="https://github.com/hailo-ai/hailo-apps.git"
HAILO_TARGET_ARCH="${HAILO_TARGET_ARCH:-hailo10h}"

MODULE_SMARTHOME=false
MODULE_PIHOLE=false
MODULE_CADDY=false
MODULE_VOICE=false
MODULE_LLM_CHAT=false

declare -a COMPOSE_SERVICES=()
declare -a REQUIRED_SECRET_KEYS=()

PASSWORD_MODE_MANUAL="manual"
PASSWORD_MODE_GENERATE="generate"
PASSWORD_MODE_USE_ENV="use_env"
PASSWORD_MODE=""

ENV_FILE_BASENAME=".env"
ENV_FILE=""

# Script liegt in ~/workspace/Siddys-Shelly-Smart-Home/install.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
WORKSPACE_DIR="$(dirname "${PROJECT_DIR}")"
HAILO_APPS_DIR="${WORKSPACE_DIR}/hailo-apps"
HAILO_COMPAT_REQUIREMENTS="${PROJECT_DIR}/requirements-hailo-compat.txt"

# ----------------------------
# Logging
# ----------------------------
log()  { echo "[INFO]  $*"; }
warn() { echo "[WARN]  $*" >&2; }
fail() { echo "[ERROR] $*" >&2; exit 1; }

model_present_in_tags() {
  local tags_json="$1"
  local wanted_model="$2"
  TAGS_JSON="${tags_json}" WANTED_MODEL="${wanted_model}" python3 - <<'PY'
import json
import os
import sys

raw = os.environ.get("TAGS_JSON", "")
wanted = os.environ.get("WANTED_MODEL", "").strip().lower()
if not raw or not wanted:
    sys.exit(1)

def canonical(name: str) -> str:
    n = name.strip().lower()
    if ":" in n:
        n = n.split(":", 1)[0]
    return n

try:
    payload = json.loads(raw)
except Exception:
    sys.exit(1)

names = []
for item in payload.get("models", []):
    if isinstance(item, dict) and item.get("name"):
        names.append(str(item["name"]))

wanted_c = canonical(wanted)
for name in names:
    cur = canonical(name)
    if cur == wanted_c:
        sys.exit(0)
    if wanted_c in cur:
        sys.exit(0)

sys.exit(1)
PY
}

detect_available_function_model() {
  local tags_json="${1:-}"
  local hailo_json="${2:-}"
  TAGS_JSON="${tags_json}" HAILO_JSON="${hailo_json}" python3 - <<'PY'
import json
import os

tags_raw = os.environ.get("TAGS_JSON", "")
hailo_raw = os.environ.get("HAILO_JSON", "")

def canonical(text: str) -> str:
    t = text.strip().lower()
    if ":" in t:
        t = t.split(":", 1)[0]
    return t

def collect_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from collect_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from collect_strings(v)
    elif isinstance(obj, str):
        yield obj

def load_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

tags = load_json(tags_raw)
hailo = load_json(hailo_raw)

models = []
for item in tags.get("models", []):
    if isinstance(item, dict) and item.get("name"):
        models.append(str(item["name"]))

models.extend(collect_strings(hailo))

def is_fc_qwen_candidate(name: str) -> bool:
    n = canonical(name)
    return "qwen2" in n and "1.5" in n and ("function" in n or "tool" in n)

for name in models:
    if is_fc_qwen_candidate(name):
        print(name.strip())
        raise SystemExit(0)

raise SystemExit(1)
PY
}

extract_hailo_runtime_models() {
  local hailo_json="${1:-}"
  HAILO_JSON="${hailo_json}" python3 - <<'PY'
import json
import os

raw = os.environ.get("HAILO_JSON", "")
if not raw:
    raise SystemExit(0)

try:
    payload = json.loads(raw)
except Exception:
    raise SystemExit(0)

models = []
if isinstance(payload, dict):
    if isinstance(payload.get("models"), list):
        for item in payload["models"]:
            if isinstance(item, str):
                models.append(item)
            elif isinstance(item, dict):
                for key in ("name", "model"):
                    if isinstance(item.get(key), str):
                        models.append(item[key])
                        break
for m in models:
    print(m)
PY
}

wait_with_progress() {
  local pid="$1"
  local message="$2"
  local interval="${3:-2}"
  local rc=0

  printf "%s" "${message}"
  while kill -0 "${pid}" 2>/dev/null; do
    printf "."
    sleep "${interval}"
  done

  if ! wait "${pid}"; then
    rc=$?
  fi
  echo
  return "${rc}"
}

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
  local tmp_file=""

  [[ -f "${env_file}" ]] || touch "${env_file}"

  tmp_file="$(mktemp)"
  awk -v k="${key}" -v v="${value}" '
    BEGIN { updated=0 }
    index($0, k "=") == 1 {
      if (!updated) {
        print k "=" v
        updated=1
      }
      next
    }
    { print }
    END {
      if (!updated) {
        print k "=" v
      }
    }
  ' "${env_file}" > "${tmp_file}"
  mv "${tmp_file}" "${env_file}"
}

append_unique() {
  local value="$1"
  local item=""

  for item in "${REQUIRED_SECRET_KEYS[@]}"; do
    [[ "${item}" == "${value}" ]] && return
  done

  REQUIRED_SECRET_KEYS+=("${value}")
}

get_secret_description() {
  local key="$1"

  case "${key}" in
    MQTT_PASSWORD) echo "Mosquitto/Telegraf MQTT Passwort" ;;
    INFLUXDB_PASSWORD) echo "InfluxDB Admin-Passwort" ;;
    INFLUXDB_WRITE_TOKEN) echo "InfluxDB Write-Token (Telegraf/Grafana Datasource)" ;;
    GRAFANA_ADMIN_PASSWORD) echo "Grafana Admin-Passwort" ;;
    PIHOLE_API_PASSWORD) echo "Pi-hole API-Passwort" ;;
    PIHOLE_ADMIN_PASSWORD) echo "Pi-hole Web-Admin-Passwort" ;;
    OPEN_WEBUI_ADMIN_PASSWORD) echo "Open WebUI Admin-Passwort" ;;
    *) echo "${key}" ;;
  esac
}

collect_required_secrets_for_selected_modules() {
  REQUIRED_SECRET_KEYS=()

  if [[ "${MODULE_SMARTHOME}" == "true" ]]; then
    append_unique "MQTT_PASSWORD"
    append_unique "INFLUXDB_PASSWORD"
    append_unique "INFLUXDB_WRITE_TOKEN"
    append_unique "GRAFANA_ADMIN_PASSWORD"
  fi

  if [[ "${MODULE_PIHOLE}" == "true" ]]; then
    append_unique "PIHOLE_API_PASSWORD"
    append_unique "PIHOLE_ADMIN_PASSWORD"
  fi

  if [[ "${MODULE_LLM_CHAT}" == "true" ]]; then
    append_unique "OPEN_WEBUI_ADMIN_PASSWORD"
  fi
}

ensure_env_file_present() {
  ENV_FILE="${PROJECT_DIR}/${ENV_FILE_BASENAME}"
  [[ -f "${ENV_FILE}" ]] || touch "${ENV_FILE}"
}

ensure_non_secret_env_defaults() {
  local defaults=(
    "MQTT_USER=telegraf"
    "INFLUXDB_INIT_MODE=setup"
    "INFLUXDB_USERNAME=admin"
    "INFLUXDB_ORG=home"
    "INFLUXDB_BUCKET=shelly"
    "GF_ADMIN_USER=admin"
    "OPEN_WEBUI_ADMIN_EMAIL=admin@local"
    "OPEN_WEBUI_ADMIN_NAME=admin"
  )
  local entry key
  for entry in "${defaults[@]}"; do
    key="${entry%%=*}"
    if ! grep -qE "^${key}=" "${ENV_FILE}"; then
      upsert_env_key "${key}" "${entry#*=}" "${ENV_FILE}"
      log "Ergänze .env Default: ${key}"
    fi
  done
}

read_env_key() {
  local key="$1"
  local env_file="$2"

  [[ -f "${env_file}" ]] || {
    echo ""
    return 0
  }

  awk -F= -v k="${key}" 'index($0, k "=") == 1 { print substr($0, length(k)+2); exit }' "${env_file}"
}

env_key_has_value() {
  local key="$1"
  local env_file="$2"
  local current_value=""

  [[ -f "${env_file}" ]] || return 1
  current_value="$(awk -F= -v k="${key}" 'index($0, k "=") == 1 { print substr($0, length(k)+2); exit }' "${env_file}")"
  [[ -n "${current_value}" ]]
}

generate_secret_value() {
  local length="$1"
  local generated=""
  generated="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${length}" || true)"
  if [[ "${#generated}" -lt "${length}" ]]; then
    generated="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "${length}")"
  fi
  echo "${generated}"
}

prompt_secret_with_confirmation() {
  local key="$1"
  local label="$2"
  local first=""
  local second=""
  local had_xtrace=false

  if [[ "$-" == *x* ]]; then
    had_xtrace=true
    set +x
  fi

  while true; do
    read -r -s -p "${label}: " first
    echo
    [[ -n "${first}" ]] || { warn "${key} darf nicht leer sein."; continue; }

    read -r -s -p "${label} bestätigen: " second
    echo
    if [[ "${first}" == "${second}" ]]; then
      printf "%s" "${first}"
      break
    fi
    warn "Eingaben stimmen nicht überein. Bitte erneut eingeben."
  done

  if [[ "${had_xtrace}" == "true" ]]; then
    set -x
  fi

  return 0
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

get_installed_package_version() {
  local package_name="$1"
  dpkg-query -W -f='${Version}' "${package_name}" 2>/dev/null || true
}

run_hailo_installer_fallback() {
  local -a installer_args=("${HAILO_TARGET_ARCH}")
  local hailort_version tappas_version

  hailort_version="$(get_installed_package_version "hailort")"
  tappas_version="$(get_installed_package_version "hailo-tappas-core")"

  if [[ -n "${hailort_version}" ]]; then
    installer_args+=("--hailort-version" "${hailort_version}")
  fi
  if [[ -n "${tappas_version}" ]]; then
    installer_args+=("--tappas-core-version" "${tappas_version}")
  fi

  log "Starte ./scripts/hailo_installer.sh ${installer_args[*]} ..."
  ${SUDO} ./scripts/hailo_installer.sh "${installer_args[@]}"
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

select_password_mode() {
  local choice=""

  if [[ ${#REQUIRED_SECRET_KEYS[@]} -eq 0 ]]; then
    log "Keine passwortpflichtigen Module ausgewählt. Passwortstrategie wird übersprungen."
    return
  fi

  echo
  echo "============================================================"
  echo "Passwortstrategie"
  echo "============================================================"
  echo "1) Passwörter selbst eingeben"
  echo "2) Passwörter generieren (8-12 Zeichen, alphanumerisch)"
  echo "3) Bestehende Passwörter aus .env verwenden"

  while true; do
    read -r -p "Bitte wählen [1-3]: " choice
    case "${choice}" in
      1) PASSWORD_MODE="${PASSWORD_MODE_MANUAL}"; return ;;
      2) PASSWORD_MODE="${PASSWORD_MODE_GENERATE}"; return ;;
      3) PASSWORD_MODE="${PASSWORD_MODE_USE_ENV}"; return ;;
      *) warn "Ungültige Auswahl. Bitte 1, 2 oder 3 wählen." ;;
    esac
  done
}

apply_manual_secret_entry() {
  local key desc secret_value
  for key in "${REQUIRED_SECRET_KEYS[@]}"; do
    desc="$(get_secret_description "${key}")"
    echo
    echo "------------------------------------------------------------"
    echo "Manuelle Eingabe: ${desc}"
    echo "------------------------------------------------------------"
    secret_value="$(prompt_secret_with_confirmation "${key}" "${desc}")"
    upsert_env_key "${key}" "${secret_value}" "${ENV_FILE}"
    echo
  done
}

apply_generated_secrets() {
  local key desc generated length
  for key in "${REQUIRED_SECRET_KEYS[@]}"; do
    length="$((RANDOM % 5 + 8))"
    generated="$(generate_secret_value "${length}")"
    desc="$(get_secret_description "${key}")"
    [[ -n "${generated}" ]] || fail "Konnte Secret für ${key} nicht generieren."
    upsert_env_key "${key}" "${generated}" "${ENV_FILE}"
    log "Secret aktualisiert: ${desc}"
  done
}

resolve_missing_env_secrets() {
  local -a missing=("$@")
  local choice=""
  local key desc secret_value length generated

  echo
  warn "In .env fehlen erforderliche Werte für ausgewählte Module:"
  for key in "${missing[@]}"; do
    echo " - ${key}"
  done
  echo
  echo "Wie sollen fehlende Werte behandelt werden?"
  echo "1) Fehlende Werte manuell erfassen"
  echo "2) Fehlende Werte generieren"
  echo "3) Installation abbrechen"

  while true; do
    read -r -p "Bitte wählen [1-3]: " choice
    case "${choice}" in
      1)
        for key in "${missing[@]}"; do
          desc="$(get_secret_description "${key}")"
          secret_value="$(prompt_secret_with_confirmation "${key}" "${desc}")"
          upsert_env_key "${key}" "${secret_value}" "${ENV_FILE}"
        done
        return
        ;;
      2)
        for key in "${missing[@]}"; do
          length="$((RANDOM % 5 + 8))"
          generated="$(generate_secret_value "${length}")"
          [[ -n "${generated}" ]] || fail "Konnte Secret für ${key} nicht generieren."
          upsert_env_key "${key}" "${generated}" "${ENV_FILE}"
          log "Fehlendes Secret ergänzt: $(get_secret_description "${key}")"
        done
        return
        ;;
      3) fail "Erforderliche .env-Secrets fehlen. Abbruch auf Benutzerwunsch." ;;
      *) warn "Ungültige Auswahl. Bitte 1, 2 oder 3 wählen." ;;
    esac
  done
}

use_existing_env_secrets() {
  local -a missing=()
  local key
  for key in "${REQUIRED_SECRET_KEYS[@]}"; do
    if ! env_key_has_value "${key}" "${ENV_FILE}"; then
      missing+=("${key}")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    log "Alle benötigten Secrets sind in .env vorhanden und werden wiederverwendet."
    return
  fi

  resolve_missing_env_secrets "${missing[@]}"
}

process_password_strategy() {
  ensure_env_file_present
  collect_required_secrets_for_selected_modules
  ensure_non_secret_env_defaults
  select_password_mode

  case "${PASSWORD_MODE}" in
    "${PASSWORD_MODE_MANUAL}") apply_manual_secret_entry ;;
    "${PASSWORD_MODE_GENERATE}") apply_generated_secrets ;;
    "${PASSWORD_MODE_USE_ENV}") use_existing_env_secrets ;;
    "") ;;
    *) fail "Unbekannter Passwortmodus: ${PASSWORD_MODE}" ;;
  esac
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
      if command -v hailortcli >/dev/null 2>&1; then
        warn "hailortcli ist bereits installiert. Überspringe hailo_installer-Fallback."
        warn "Wenn 'hailortcli fw-control identify' fehlschlägt, liegt meist ein Geräte-/Treiber-/Reboot-Thema vor."
        fail "hailo-apps Post-Install fehlgeschlagen, obwohl HailoRT vorhanden ist. Bitte Device-Verbindung prüfen und nach Treiberinstallation neu starten."
      fi
      run_hailo_installer_fallback
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

  if [[ -f "${HAILO_COMPAT_REQUIREMENTS}" ]]; then
    log "Installiere Hailo-Kompatibilitätsabhängigkeiten aus ${HAILO_COMPAT_REQUIREMENTS} ..."
    python3 -m pip install -r "${HAILO_COMPAT_REQUIREMENTS}"
  fi

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

ensure_hailo_runtime_for_selected_modules() {
  if [[ "${MODULE_VOICE}" != "true" && "${MODULE_LLM_CHAT}" != "true" ]]; then
    return
  fi

  repair_system_packages
  install_hailo_h10_stack
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
  log "Hinweis: Der Model-Download kann je nach Netzwerk und Modellgröße mehrere Minuten dauern."
  curl --silent --show-error \
    "http://localhost:8000/api/pull" \
    -H "Content-Type: application/json" \
    -d "{ \"model\": \"${DEFAULT_LLM_MODEL}\", \"stream\" : true }" >/dev/null &
  local pull_pid=$!
  if ! wait_with_progress "${pull_pid}" "[INFO]  Download läuft, bitte warten" 2; then
    warn "Download von ${DEFAULT_LLM_MODEL} fehlgeschlagen. Installation läuft weiter; bitte Modell ggf. manuell laden."
    return
  fi
  log "Model-Download abgeschlossen."

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

ensure_function_calling_model() {
  log "Prüfe, ob Function-Calling-Modell ${FUNCTION_CALLING_MODEL} verfügbar ist ..."
  local tags_json
  local hailo_json=""
  local candidate
  local candidates_csv
  local max_checks=60
  local check_no
  local pull_response=""
  local detected_model=""
  local pull_not_found_count=0
  local candidate_count=0
  local runtime_models=""
  local allow_fc_fallback=""
  local fallback_candidate=""

  if ! tags_json="$(curl --silent --show-error --fail "http://localhost:8000/api/tags" 2>/dev/null)"; then
    fail "Konnte Modellliste nicht lesen. Function-Calling-Modell kann nicht verifiziert werden."
  fi

  hailo_json="$(curl --silent "http://localhost:8000/hailo/v1/list" 2>/dev/null || true)"
  runtime_models="$(extract_hailo_runtime_models "${hailo_json}")"
  if detected_model="$(detect_available_function_model "${tags_json}" "${hailo_json}" 2>/dev/null)"; then
    FUNCTION_CALLING_MODEL="${detected_model}"
    log "Verwende bereits verfügbares Function-Calling-Modell aus Runtime-Liste: ${FUNCTION_CALLING_MODEL}"
    return
  fi

  if model_present_in_tags "${tags_json}" "${FUNCTION_CALLING_MODEL}"; then
    log "Function-Calling-Modell ${FUNCTION_CALLING_MODEL} ist bereits vorhanden."
    return
  fi

  candidates_csv="${FUNCTION_CALLING_MODEL_CANDIDATES:-${FUNCTION_CALLING_MODEL},Qwen2-1.5B-Instruct-Function-Calling-v1,qwen2-1.5b-instruct-function-calling-v1:latest}"

  IFS=',' read -r -a _candidates <<<"${candidates_csv}"
  candidate_count="${#_candidates[@]}"
  for candidate in "${_candidates[@]}"; do
    candidate="$(echo "${candidate}" | xargs)"
    [[ -n "${candidate}" ]] || continue
    log "Function-Calling-Modell-Kandidat fehlt: ${candidate}. Starte Vorab-Download ..."

    if ! pull_response="$(curl --silent --show-error --fail \
        "http://localhost:8000/api/pull" \
        -H "Content-Type: application/json" \
        -d "{ \"model\": \"${candidate}\", \"stream\" : true }" 2>&1)"; then
      warn "Download für Kandidat fehlgeschlagen: ${candidate}"
      continue
    fi
    if grep -qi "\"error\"" <<<"${pull_response}"; then
      warn "Pull-API meldete Fehler für Kandidat ${candidate}: ${pull_response}"
      if grep -qi "not found" <<<"${pull_response}"; then
        pull_not_found_count=$((pull_not_found_count + 1))
      fi
      continue
    fi

    for ((check_no=1; check_no<=max_checks; check_no++)); do
      if ! tags_json="$(curl --silent --show-error --fail "http://localhost:8000/api/tags" 2>/dev/null)"; then
        sleep 1
        continue
      fi
      hailo_json="$(curl --silent "http://localhost:8000/hailo/v1/list" 2>/dev/null || true)"
      if detected_model="$(detect_available_function_model "${tags_json}" "${hailo_json}" 2>/dev/null)"; then
        FUNCTION_CALLING_MODEL="${detected_model}"
        log "Function-Calling-Modell erfolgreich vorinstalliert und in Runtime erkannt: ${FUNCTION_CALLING_MODEL}"
        return
      fi
      if model_present_in_tags "${tags_json}" "${candidate}"; then
        FUNCTION_CALLING_MODEL="${candidate}"
        log "Function-Calling-Modell erfolgreich vorinstalliert und verifiziert: ${FUNCTION_CALLING_MODEL}"
        return
      fi
      sleep 1
    done
    warn "Kandidat nach Download nicht in /api/tags sichtbar: ${candidate}"
  done

  if ! tags_json="$(curl --silent --show-error --fail "http://localhost:8000/api/tags" 2>/dev/null)"; then
    fail "Nach Download konnte die Modellliste nicht erneut gelesen werden."
  fi
  hailo_json="$(curl --silent "http://localhost:8000/hailo/v1/list" 2>/dev/null || true)"
  runtime_models="$(extract_hailo_runtime_models "${hailo_json}")"
  if detected_model="$(detect_available_function_model "${tags_json}" "${hailo_json}" 2>/dev/null)"; then
    FUNCTION_CALLING_MODEL="${detected_model}"
    log "Function-Calling-Modell aus Runtime-Listung erkannt: ${FUNCTION_CALLING_MODEL}"
    return
  fi

  if [[ "${pull_not_found_count}" -ge "${candidate_count}" ]]; then
    allow_fc_fallback="$(echo "${VOICE_ALLOW_FUNCTION_MODEL_FALLBACK:-true}" | tr '[:upper:]' '[:lower:]')"
    if [[ "${allow_fc_fallback}" == "true" ]]; then
      for fallback_candidate in qwen2:1.5b qwen2.5-instruct:1.5b llama3.2:3b; do
        if grep -qx "${fallback_candidate}" <<<"${runtime_models}"; then
          FUNCTION_CALLING_MODEL="${fallback_candidate}"
          warn "Function-Calling-Modell aktuell nicht verfügbar. Nutze expliziten Übergangs-Fallback: ${FUNCTION_CALLING_MODEL}. Bitte später auf Qwen2-Function-Calling upgraden."
          return
        fi
      done
    fi

    fail "Kein Kandidat ist in deiner hailo-ollama Version verfügbar (alle Pulls = 'model not found'). Runtime-Modelle laut /hailo/v1/list: ${runtime_models:-<leer>}. Bitte hailo_gen_ai_model_zoo/hailo-ollama auf eine Version mit Qwen2 Function-Calling aktualisieren oder VOICE_FUNCTION_CALLING_MODEL auf ein tatsächlich gelistetes FC-Modell setzen. Optionaler Übergang: VOICE_ALLOW_FUNCTION_MODEL_FALLBACK=true."
  fi

  fail "Kein Function-Calling-Modell konnte vorbereitet werden. Geprüfte Kandidaten: ${candidates_csv}. Bitte prüfe 'curl http://localhost:8000/hailo/v1/list' und 'curl http://localhost:8000/api/tags' und setze VOICE_FUNCTION_CALLING_MODEL auf den dort sichtbaren Modellnamen."
}

verify_hailo10h_runtime() {
  log "Verifiziere Hailo Runtime/Hardware (Hailo-10H erwartet) ..."

  if ! command -v hailortcli >/dev/null 2>&1; then
    fail "hailortcli fehlt. Hailo Runtime ist nicht installiert."
  fi

  local identify_output
  if ! identify_output="$(hailortcli fw-control identify 2>&1)"; then
    fail "Hailo Hardware-Identifikation fehlgeschlagen: ${identify_output}"
  fi
  log "hailortcli identify: ${identify_output}"
  if ! grep -qi "HAILO10H" <<<"${identify_output}"; then
    fail "Erkannte Architektur ist nicht HAILO10H. Ausgabe: ${identify_output}"
  fi

  local hailo_list
  if ! hailo_list="$(curl --silent --show-error --fail "http://localhost:8000/hailo/v1/list" 2>/dev/null)"; then
    fail "Hailo API /hailo/v1/list nicht erreichbar."
  fi
  if ! grep -qi "\"models\"" <<<"${hailo_list}"; then
    fail "Hailo API lieferte keine erwartete Modellliste. Antwort: ${hailo_list}"
  fi
  log "Hailo Runtime API erreichbar, Modellliste: ${hailo_list}"
}

run_function_calling_smoke_test() {
  log "Starte Function-Calling Smoke-Test (Qwen2-1.5B Function-Calling) ..."
  local payload response
  payload=$(cat <<EOF
{"model":"${FUNCTION_CALLING_MODEL}","stream":false,"messages":[{"role":"system","content":"Antworte nur mit JSON-Tool-Call."},{"role":"user","content":"Schalte Wohnzimmerlicht an"}],"tools":[{"type":"function","function":{"name":"switch_shelly_device","description":"Schaltet ein Shelly-Gerät","parameters":{"type":"object","properties":{"room":{"type":"string"},"action":{"type":"string","enum":["on","off","toggle"]}},"required":["action"]}}}]}
EOF
)
  if ! response="$(curl --silent --show-error --fail "http://localhost:8000/api/chat" -H "Content-Type: application/json" -d "${payload}")"; then
    fail "Function-Calling Smoke-Test fehlgeschlagen (kein API-Response)."
  fi
  if ! grep -Eq "tool_calls|switch_shelly_device|ask_for_clarification|answer_with_llm" <<<"${response}"; then
    fail "Function-Calling Smoke-Test fehlgeschlagen (keine Tool-Antwort): ${response}"
  fi
  log "Function-Calling Smoke-Test erfolgreich."
}


ensure_voice_env_defaults() {
  cd "${PROJECT_DIR}"

  ensure_env_file_present

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
    "VOICE_WHISPER_MODE=hf_local"
    "VOICE_WHISPER_MODEL=openai/whisper-base"
    "VOICE_WHISPER_LANGUAGE=de"
    "VOICE_WHISPER_CACHE_DIR=/home/siddy/.cache/huggingface"
    "VOICE_LLM_BASE_URL=http://host.docker.internal:8000"
    "VOICE_LLM_MODEL=llama3.2:3b"
    "VOICE_FUNCTION_CALLING_MODEL=${FUNCTION_CALLING_MODEL}"
    "VOICE_ALLOW_FUNCTION_MODEL_FALLBACK=true"
    "VOICE_FUNCTION_CALLING_REQUIRE_HAILO=true"
    "VOICE_LLM_TIMEOUT_SECONDS=45"
    "SHELLY_DEVICE_MAP_FILE=/app/app/config/shelly_devices.json"
    "SHELLY_DEVICE_MAP_JSON="
    "SHELLY_DEFAULT_COMMAND_PATH=/script/light-control"
    "SHELLY_TIMEOUT_SECONDS=5"
    "VOICE_TTS_SHELL_COMMAND="
    "VOICE_TTS_AUTO_ENABLED=true"
    "VOICE_TTS_LANGUAGE=de"
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
    if ! env_key_has_value "${key}" "${ENV_FILE}"; then
      upsert_env_key "${key}" "${entry#*=}" "${ENV_FILE}"
      log "Ergänze fehlende .env Vorgabe: ${key}"
    fi
  done

  local current_llm_base
  current_llm_base="$(read_env_key "VOICE_LLM_BASE_URL" "${ENV_FILE}")"
  if [[ "${current_llm_base}" == "http://127.0.0.1:8000" || "${current_llm_base}" == "http://localhost:8000" ]]; then
    upsert_env_key "VOICE_LLM_BASE_URL" "http://host.docker.internal:8000" "${ENV_FILE}"
    log "Migriere VOICE_LLM_BASE_URL auf host.docker.internal für Container-Zugriff."
  fi

  upsert_env_key "OPEN_WEBUI_DEFAULT_MODELS" "${ACTIVE_LLM_MODEL}" "${ENV_FILE}"
  upsert_env_key "OPEN_WEBUI_OLLAMA_BASE_URL" "http://127.0.0.1:8000" "${ENV_FILE}"
  upsert_env_key "OPEN_WEBUI_IMAGE" "ghcr.io/open-webui/open-webui:main" "${ENV_FILE}"
  log "Setze OPEN_WEBUI_DEFAULT_MODELS auf ${ACTIVE_LLM_MODEL}"
}


ensure_whisper_model_cache() {
  cd "${PROJECT_DIR}"
  ensure_env_file_present

  local cache_dir
  cache_dir="$(read_env_key "VOICE_WHISPER_CACHE_DIR" "${ENV_FILE}")"
  [[ -z "${cache_dir}" ]] && cache_dir="/home/${REAL_USER}/.cache/huggingface"

  mkdir -p "${cache_dir}"
  chown -R "${REAL_USER}:${REAL_USER}" "${cache_dir}" 2>/dev/null || true

  log "Prüfe/Cache Whisper-Modell openai/whisper-base in ${cache_dir} ..."
  if ${SUDO} docker compose run --rm voice-pipeline python -c "from huggingface_hub import snapshot_download; snapshot_download('openai/whisper-base', cache_dir='/models/huggingface')"; then
    log "Whisper-Modell openai/whisper-base ist verfügbar."
  else
    warn "Whisper-Modell konnte nicht vorab geladen werden. Wird ggf. beim ersten Lauf geladen."
  fi
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
    ${SUDO} docker compose up -d --force-recreate "${COMPOSE_SERVICES[@]}"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    log "Starte ausgewählte Compose-Services mit docker-compose up -d ..."
    ${SUDO} docker-compose up -d --force-recreate "${COMPOSE_SERVICES[@]}"
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
  process_password_strategy
  install_base_packages
  install_docker_if_needed
  ensure_docker_group_membership
  ensure_hailo_runtime_for_selected_modules

  if [[ "${MODULE_VOICE}" == "true" ]]; then
    setup_hailo_apps_and_whisper
  fi

  if [[ "${MODULE_LLM_CHAT}" == "true" ]]; then
    download_deb_if_needed
    install_hailo_ollama_if_needed
    write_hailo_service
    enable_and_start_hailo_service
    wait_for_hailo_ollama
    ensure_default_llm_model
    ensure_function_calling_model
    verify_hailo10h_runtime
    run_function_calling_smoke_test
  fi

  if [[ "${MODULE_VOICE}" == "true" || "${MODULE_LLM_CHAT}" == "true" ]]; then
    ensure_voice_env_defaults
  fi

  if [[ "${MODULE_VOICE}" == "true" ]]; then
    voice_pipeline_preflight
    build_voice_service_image
    ensure_whisper_model_cache
  fi

  compose_up
  ensure_open_webui_runtime
  summary
}

main "$@"
