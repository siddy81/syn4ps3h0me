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
    "DNS_SUFFIX=home.lan"
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


configure_service_fqdn_defaults() {
  local dns_suffix=""
  local mqtt_fqdn=""
  local answer=""

  dns_suffix="$(read_env_key "DNS_SUFFIX" "${ENV_FILE}")"
  if [[ -z "${dns_suffix}" ]]; then
    dns_suffix="home.lan"
  fi

  read -r -p "DNS-Suffix für Service-FQDNs [${dns_suffix}]: " answer
  answer="${answer// /}"
  if [[ -n "${answer}" ]]; then
    dns_suffix="${answer}"
  fi

  upsert_env_key "DNS_SUFFIX" "${dns_suffix}" "${ENV_FILE}"
  upsert_env_key "INTRANET_DOMAIN" "${dns_suffix}" "${ENV_FILE}"

  mqtt_fqdn="mosquitto.${dns_suffix}"
  upsert_env_key "MQTT_BROKER_FQDN" "${mqtt_fqdn}" "${ENV_FILE}"
  upsert_env_key "GRAFANA_DOMAIN" "grafana.${dns_suffix}" "${ENV_FILE}"
  upsert_env_key "PIHOLE_DOMAIN" "pihole.${dns_suffix}" "${ENV_FILE}"
  upsert_env_key "LEGACY_HOST_DOMAIN" "nightmaresiddious.${dns_suffix}" "${ENV_FILE}"
  upsert_env_key "CADDY_DOMAIN" "caddy.${dns_suffix}" "${ENV_FILE}"
  upsert_env_key "LLM_DOMAIN" "llm.${dns_suffix}" "${ENV_FILE}"
  upsert_env_key "OPEN_WEBUI_DOMAIN" "open-webui.${dns_suffix}" "${ENV_FILE}"

  log "Setze DNS_SUFFIX/INTRANET_DOMAIN auf ${dns_suffix}"
  log "Setze MQTT_BROKER_FQDN auf ${mqtt_fqdn}"
}



is_valid_hostname_label() {
  local value="${1,,}"
  [[ "${value}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]
}

build_reserved_hostname_list() {
  local -a reserved=(
    "grafana" "batman" "darksiddious" "fritzbox" "nightmaresiddious"
    "open-webui" "llm" "caddy" "pihole" "padawan" "mosquitto" "voice"
  )
  local custom_list_file="${PROJECT_DIR}/pihole/etc-pihole/custom.list"
  local host

  if [[ -f "${custom_list_file}" ]]; then
    while read -r host; do
      [[ -n "${host}" ]] && reserved+=("${host%%.*}")
    done < <(awk '!/^[[:space:]]*#/ && NF>=2 {print $2}' "${custom_list_file}")
  fi

  printf '%s\n' "${reserved[@]}" | awk 'NF {print tolower($0)}' | sort -u
}

request_hostname_from_llm() {
  local ip="$1"
  local dns_suffix="$2"
  local reserved_csv="$3"
  local prompt_template="$4"
  local prompt=""
  local payload=""
  local reply=""
  local candidate=""

  prompt="${prompt_template}\nAntwortformat: NUR JSON wie {\"hostname\":\"beispielname\"}. Keine weiteren Felder.\nIP: ${ip}\nDomain: ${dns_suffix}\nBereits vergebene Namen: ${reserved_csv}"
  payload="$(printf '{"message":%s}' "$(printf '%s' "${prompt}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"

  reply="$(curl -fsS -X POST "http://localhost:8000/api/chat" -H "Content-Type: application/json" -d "${payload}" || true)"
  candidate="$(printf '%s' "${reply}" | python3 -c 'import json,sys,re
raw=sys.stdin.read().strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    data=json.loads(raw)
    text=data.get("response") or data.get("message") or raw
except Exception:
    text=raw
m=re.search(r'\{\s*"hostname"\s*:\s*"([a-zA-Z0-9-]+)"\s*\}', text)
if m:
    print(m.group(1).lower())
else:
    print("")')"

  printf '%s' "${candidate}"
}

scan_network_and_assign_fqdns() {
  local dns_suffix="$1"
  local scan_cidr=""
  local default_cidr="192.168.1.0/24"
  local detected_ipv4=""
  local prompt_template=""
  local custom_list_file="${PROJECT_DIR}/pihole/etc-pihole/custom.list"

  if [[ -n "${RPI_IP:-}" ]]; then
    default_cidr="${RPI_IP%.*}.0/24"
  else
    detected_ipv4="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
    if [[ "${detected_ipv4}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
      default_cidr="${detected_ipv4%.*}.0/24"
    else
      warn "RPI_IP ist nicht gesetzt und automatische CIDR-Erkennung war nicht möglich. Nutze Fallback ${default_cidr}."
    fi
  fi

  scan_cidr="$(read_env_key "NETWORK_SCAN_CIDR" "${ENV_FILE}")"
  [[ -n "${scan_cidr}" ]] || scan_cidr="${default_cidr}"

  read -r -p "CIDR für Netzwerkscan [${scan_cidr}]: " answer
  answer="${answer// /}"
  [[ -n "${answer}" ]] && scan_cidr="${answer}"

  upsert_env_key "NETWORK_SCAN_CIDR" "${scan_cidr}" "${ENV_FILE}"

  prompt_template="$(read_env_key "FQDN_NAME_PROMPT" "${ENV_FILE}")"
  if [[ -z "${prompt_template}" ]]; then
    prompt_template='gib mir ausschließlich einen guten FQDN-Namen für meine Geräte - nimm Filmnamen aus Der Herr Der Ringe oder Batman'
    upsert_env_key "FQDN_NAME_PROMPT" "${prompt_template}" "${ENV_FILE}"
  fi

  mkdir -p "$(dirname "${custom_list_file}")"
  touch "${custom_list_file}"

  mapfile -t reserved_hosts < <(build_reserved_hostname_list)
  local reserved_csv
  reserved_csv="$(IFS=,; echo "${reserved_hosts[*]}")"

  log "Scanne Heimnetz (${scan_cidr}) via nmap ..."
  mapfile -t discovered_ips < <(${SUDO} nmap -sn "${scan_cidr}" 2>/dev/null | awk '/Nmap scan report/{print $NF}' | tr -d '()' | awk '/^[0-9]+\./{print}')

  if [[ ${#discovered_ips[@]} -eq 0 ]]; then
    warn "Keine Geräte im Netzwerkscan gefunden oder nmap nicht verfügbar."
    return
  fi

  local existing_ip existing_host ip candidate tries generated_entries=""
  for ip in "${discovered_ips[@]}"; do
    existing_host="$(awk -v ip="${ip}" '!/^[[:space:]]*#/ && $1==ip {print $2; exit}' "${custom_list_file}")"
    [[ -n "${existing_host}" ]] && continue

    tries=0
    candidate=""
    while [[ ${tries} -lt 5 ]]; do
      candidate="$(request_hostname_from_llm "${ip}" "${dns_suffix}" "${reserved_csv}" "${prompt_template}")"
      if [[ -n "${candidate}" ]] && is_valid_hostname_label "${candidate}" && [[ ! " ${reserved_hosts[*]} " =~ " ${candidate} " ]]; then
        break
      fi
      candidate=""
      tries=$((tries+1))
    done

    if [[ -z "${candidate}" ]]; then
      candidate="device-${ip##*.}"
      warn "LLM lieferte keinen eindeutigen Namen für ${ip}; fallback auf ${candidate}."
    fi

    echo "${ip} ${candidate}.${dns_suffix}" >> "${custom_list_file}"
    reserved_hosts+=("${candidate}")
    reserved_csv="$(IFS=,; echo "${reserved_hosts[*]}")"
    log "FQDN vergeben: ${ip} -> ${candidate}.${dns_suffix}"
  done
}

process_password_strategy() {
  ensure_env_file_present
  collect_required_secrets_for_selected_modules
  ensure_non_secret_env_defaults
  configure_service_fqdn_defaults
  scan_network_and_assign_fqdns "$(read_env_key "DNS_SUFFIX" "${ENV_FILE}")"
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

configure_docker_log_rotation() {
  log "Konfiguriere Docker Logrotation in /etc/docker/daemon.json ..."

  local result=""
  result="$(${SUDO} python3 - <<'PY'
import json
import os
import shutil
import tempfile

path = "/etc/docker/daemon.json"
desired = {
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3",
    },
}

os.makedirs(os.path.dirname(path), exist_ok=True)

if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()
    current = json.loads(content) if content else {}
else:
    current = {}

if not isinstance(current, dict):
    raise SystemExit(f"{path} muss ein JSON-Objekt enthalten.")

updated = dict(current)
updated["log-driver"] = desired["log-driver"]
updated["log-opts"] = desired["log-opts"]

if updated == current:
    print("unchanged")
    raise SystemExit(0)

fd, tmp_path = tempfile.mkstemp(
    prefix="daemon.json.",
    suffix=".tmp",
    dir=os.path.dirname(path),
    text=True,
)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(updated, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with open(tmp_path, "r", encoding="utf-8") as handle:
        json.load(handle)

    if os.path.exists(path):
        shutil.copymode(path, tmp_path)
    else:
        os.chmod(tmp_path, 0o644)

    os.replace(tmp_path, path)
except Exception:
    try:
        os.unlink(tmp_path)
    except FileNotFoundError:
        pass
    raise

print("changed")
PY
  )"

  case "${result}" in
    changed)
      log "Docker Logrotation aktualisiert. Starte Docker neu ..."
      ${SUDO} systemctl restart docker
      ;;
    unchanged)
      log "Docker Logrotation ist bereits aktuell."
      ;;
    *)
      fail "Unerwartetes Ergebnis bei Docker Logrotation: ${result}"
      ;;
  esac
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
    log "Starte ausgewählte Compose-Services mit docker compose up -d --pull always ..."
    ${SUDO} docker compose up -d --pull always --force-recreate "${COMPOSE_SERVICES[@]}"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    log "Starte ausgewählte Compose-Services mit docker-compose up -d --pull always ..."
    ${SUDO} docker-compose up -d --pull always --force-recreate "${COMPOSE_SERVICES[@]}"
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
    ${SUDO} docker compose up -d --pull always --force-recreate open-webui || warn "Compose-Recreate für open-webui fehlgeschlagen."
  elif command -v docker-compose >/dev/null 2>&1; then
    log "Recreate open-webui mit docker-compose ..."
    ${SUDO} docker-compose up -d --pull always --force-recreate open-webui || warn "docker-compose Recreate für open-webui fehlgeschlagen."
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
  configure_docker_log_rotation
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
