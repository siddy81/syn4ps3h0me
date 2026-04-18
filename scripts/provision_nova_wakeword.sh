#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_PATH="${PROJECT_DIR}/voice-pipeline/app/models/wakewords/nova.tflite"

usage() {
  cat <<EOF
Usage:
  $0 --source <local_file_or_url>

Examples:
  $0 --source /home/siddy/models/nova.tflite
  $0 --source https://example.local/models/nova.tflite
EOF
}

SOURCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${SOURCE}" ]]; then
  echo "Missing --source argument." >&2
  usage
  exit 1
fi

mkdir -p "$(dirname "${TARGET_PATH}")"

if [[ "${SOURCE}" =~ ^https?:// ]]; then
  echo "[INFO] Downloading nova wakeword model from URL ..."
  curl --fail --silent --show-error --location "${SOURCE}" --output "${TARGET_PATH}"
else
  if [[ ! -f "${SOURCE}" ]]; then
    echo "[ERROR] Source file does not exist: ${SOURCE}" >&2
    exit 1
  fi
  echo "[INFO] Copying nova wakeword model from local file ..."
  cp "${SOURCE}" "${TARGET_PATH}"
fi

if [[ ! -s "${TARGET_PATH}" ]]; then
  echo "[ERROR] Provisioning failed, target file is empty: ${TARGET_PATH}" >&2
  exit 1
fi

echo "[OK] nova.tflite provisioned at: ${TARGET_PATH}"
