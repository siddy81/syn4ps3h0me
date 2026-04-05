#!/usr/bin/env python3
"""Imports documents from /knowledge-import into an Open WebUI knowledge base."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import pathlib
import sys
import time
from dataclasses import dataclass
import requests


SOURCE_DIR = pathlib.Path("/knowledge-import")
STATE_FILE = pathlib.Path("/state/ingested-files.json")
DEFAULT_TIMEOUT = int(os.getenv("OPEN_WEBUI_INGEST_REQUEST_TIMEOUT_SECONDS", "120"))


def configure_logging() -> None:
  level_name = os.getenv("OPEN_WEBUI_INGEST_LOG_LEVEL", "INFO").upper()
  level = getattr(logging, level_name, logging.INFO)
  logging.basicConfig(
    level=level,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
  )


@dataclass(frozen=True)
class Config:
  base_url: str
  email: str
  password: str
  knowledge_base_name: str
  knowledge_base_description: str
  interval_seconds: int


def read_config() -> Config:
  base_url = os.getenv("OPEN_WEBUI_BASE_URL", "http://open-webui:8080").rstrip("/")
  email = os.getenv("OPEN_WEBUI_ADMIN_EMAIL", "")
  password = os.getenv("OPEN_WEBUI_ADMIN_PASSWORD", "")
  kb_name = os.getenv("OPEN_WEBUI_KNOWLEDGE_BASE_NAME", "knowledge-import")
  kb_description = os.getenv(
    "OPEN_WEBUI_KNOWLEDGE_BASE_DESCRIPTION",
    "Automatisch aus open-webui/knowledge importierte Dokumente",
  )
  interval_seconds = int(os.getenv("OPEN_WEBUI_INGEST_INTERVAL_SECONDS", "60"))

  missing = []
  if not email:
    missing.append("OPEN_WEBUI_ADMIN_EMAIL")
  if not password:
    missing.append("OPEN_WEBUI_ADMIN_PASSWORD")
  if missing:
    raise RuntimeError(f"Missing required environment values: {', '.join(missing)}")

  return Config(
    base_url=base_url,
    email=email,
    password=password,
    knowledge_base_name=kb_name,
    knowledge_base_description=kb_description,
    interval_seconds=max(interval_seconds, 10),
  )


def sha256sum(path: pathlib.Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as file_handle:
    for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def detect_content_type(path: pathlib.Path) -> str:
  guessed, _ = mimetypes.guess_type(path.name)
  return guessed or "application/octet-stream"


def load_state() -> dict[str, dict[str, str]]:
  if not STATE_FILE.exists():
    return {}
  try:
    with STATE_FILE.open("r", encoding="utf-8") as state_handle:
      data = json.load(state_handle)
      if isinstance(data, dict):
        return data
  except json.JSONDecodeError:
    logging.warning("State file is invalid JSON. Rebuilding state from scratch.")
  return {}


def save_state(state: dict[str, dict[str, str]]) -> None:
  STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
  tmp_file = STATE_FILE.with_suffix(".tmp")
  with tmp_file.open("w", encoding="utf-8") as state_handle:
    json.dump(state, state_handle, indent=2, sort_keys=True)
  tmp_file.replace(STATE_FILE)


def list_documents() -> list[pathlib.Path]:
  if not SOURCE_DIR.exists():
    logging.warning("Source directory does not exist: %s", SOURCE_DIR)
    return []
  return sorted(path for path in SOURCE_DIR.rglob("*") if path.is_file())


class OpenWebUIClient:
  def __init__(self, config: Config):
    self._config = config
    self._session = requests.Session()
    self._session.headers.update({"Accept": "application/json"})

  def authenticate(self) -> None:
    auth_payload = {
      "email": self._config.email,
      "password": self._config.password,
    }
    response = self._session.post(
      f"{self._config.base_url}/api/v1/auths/signin",
      json=auth_payload,
      timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    token = body.get("token")
    if token:
      self._session.headers.update({"Authorization": f"Bearer {token}"})
    logging.info("Authenticated against Open WebUI API.")

  def get_or_create_knowledge_base(self) -> str:
    response = self._session.get(
      f"{self._config.base_url}/api/v1/knowledge/",
      timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    entries = payload if isinstance(payload, list) else payload.get("data", [])
    for entry in entries:
      if entry.get("name") == self._config.knowledge_base_name:
        kb_id = entry.get("id")
        if kb_id:
          return str(kb_id)

    create_payload = {
      "name": self._config.knowledge_base_name,
      "description": self._config.knowledge_base_description,
    }
    create_response = self._session.post(
      f"{self._config.base_url}/api/v1/knowledge/create",
      json=create_payload,
      timeout=DEFAULT_TIMEOUT,
    )
    create_response.raise_for_status()
    created = create_response.json()
    kb_id = created.get("id") or created.get("data", {}).get("id")
    if not kb_id:
      raise RuntimeError("Knowledge base creation succeeded but no id was returned.")
    logging.info("Created knowledge base '%s' (%s).", self._config.knowledge_base_name, kb_id)
    return str(kb_id)

  def upload_file(self, file_path: pathlib.Path) -> str:
    if file_path.stat().st_size == 0:
      raise ValueError(f"Cannot upload empty file: {file_path}")

    content_type = detect_content_type(file_path)
    with file_path.open("rb") as binary:
      response = self._session.post(
        f"{self._config.base_url}/api/v1/files/",
        files={"file": (file_path.name, binary, content_type)},
        timeout=DEFAULT_TIMEOUT,
      )
    response.raise_for_status()
    body = response.json()
    file_id = body.get("id") or body.get("data", {}).get("id")
    if not file_id:
      raise RuntimeError(f"Upload for '{file_path}' succeeded but no file id was returned.")
    return str(file_id)

  def add_file_to_knowledge_base(self, knowledge_base_id: str, file_id: str) -> None:
    response = self._session.post(
      f"{self._config.base_url}/api/v1/knowledge/{knowledge_base_id}/file/add",
      json={"file_id": file_id},
      timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()

  def delete_file(self, file_id: str) -> None:
    response = self._session.delete(
      f"{self._config.base_url}/api/v1/files/{file_id}",
      timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code not in (200, 204, 404):
      response.raise_for_status()


def ingest_once(client: OpenWebUIClient, knowledge_base_id: str, state: dict[str, dict[str, str]]) -> bool:
  changed = False
  current_paths = {str(path.relative_to(SOURCE_DIR)): path for path in list_documents()}

  # Remove state entries for deleted files.
  for stored_path in list(state):
    if stored_path not in current_paths:
      removed = state.pop(stored_path, None)
      logging.info("Source file removed, dropping state: %s", stored_path)
      if removed and removed.get("file_id"):
        client.delete_file(removed["file_id"])
      changed = True

  for relative, absolute_path in current_paths.items():
    if absolute_path.stat().st_size == 0:
      logging.warning("Skipping empty source file: %s", relative)
      continue

    file_hash = sha256sum(absolute_path)
    current_state = state.get(relative)
    if current_state and current_state.get("sha256") == file_hash:
      continue

    if current_state and current_state.get("file_id"):
      client.delete_file(current_state["file_id"])

    logging.info("Ingesting %s", relative)
    file_id = client.upload_file(absolute_path)
    client.add_file_to_knowledge_base(knowledge_base_id, file_id)
    state[relative] = {"sha256": file_hash, "file_id": file_id}
    changed = True

  return changed


def main() -> int:
  configure_logging()
  try:
    config = read_config()
  except Exception as exc:  # pylint: disable=broad-except
    logging.error("Configuration error: %s", exc)
    return 1

  state = load_state()
  client = OpenWebUIClient(config)

  while True:
    try:
      client.authenticate()
      knowledge_base_id = client.get_or_create_knowledge_base()
      if ingest_once(client, knowledge_base_id, state):
        save_state(state)
    except requests.RequestException as exc:
      logging.warning("Open WebUI API not available yet: %s", exc)
    except Exception as exc:  # pylint: disable=broad-except
      logging.exception("Ingest cycle failed: %s", exc)

    time.sleep(config.interval_seconds)


if __name__ == "__main__":
  sys.exit(main())
