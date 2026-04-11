#!/usr/bin/env python3
"""Synchronisiert Dateien aus /knowledge-import in Open WebUI Knowledge Bases.

Regeln:
- Jede Top-Level-Ordnerstruktur wird als eigene Knowledge-Kategorie behandelt.
- Dateien im Root von /knowledge-import landen in einer separaten Root-Kategorie.
- Änderungen werden per SHA256 erkannt; veraltete Dateien werden aus Knowledge entfernt.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time
from collections import defaultdict
from typing import Any

import requests

DEFAULT_ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".doc",
    ".rtf",
    ".csv",
    ".json",
}

ROOT_CATEGORY_KEY = "__root__"


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_extensions(raw: str | None) -> set[str]:
    if not raw:
        return DEFAULT_ALLOWED_EXTENSIONS
    return {f".{part.strip().lstrip('.').lower()}" for part in raw.split(",") if part.strip()}


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category_for_path(base_dir: pathlib.Path, file_path: pathlib.Path) -> str:
    rel = file_path.relative_to(base_dir)
    return rel.parts[0] if len(rel.parts) > 1 else ROOT_CATEGORY_KEY


class WebUIClient:
    def __init__(self, base_url: str, email: str, password: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = self._login(email, password)

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200,),
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        merged_headers = headers.copy() if headers else {}
        merged_headers["Authorization"] = f"Bearer {self.token}"

        response = requests.request(method, url, timeout=self.timeout, headers=merged_headers, **kwargs)
        if response.status_code not in expected:
            raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
        return response

    def _login(self, email: str, password: str) -> str:
        payload = {"email": email, "password": password}
        for path in ("/api/v1/auths/signin", "/api/auths/signin"):
            try:
                response = requests.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code != 200:
                    continue
                body = response.json()
                token = body.get("token") or body.get("access_token")
                if token:
                    print(f"[sync] Authenticated via {path}")
                    return token
            except requests.RequestException:
                continue
        raise RuntimeError("Open WebUI login failed")

    def list_knowledge(self) -> list[dict[str, Any]]:
        for path in ("/api/v1/knowledge/", "/api/v1/knowledge"):
            try:
                response = self._request("GET", path)
                data = response.json()
                return data if isinstance(data, list) else data.get("data", [])
            except Exception:
                continue
        raise RuntimeError("Unable to list knowledge bases")

    def list_models(self) -> list[dict[str, Any]]:
        for path in ("/api/v1/models", "/api/models"):
            try:
                response = self._request("GET", path)
                data = response.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    return data["data"]
                return []
            except Exception:
                continue
        raise RuntimeError("Unable to list models")

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any] | None:
        for path in (f"/api/v1/knowledge/{knowledge_id}", f"/api/v1/knowledge/id/{knowledge_id}"):
            try:
                return self._request("GET", path).json()
            except Exception:
                continue
        return None

    def create_knowledge(self, name: str, description: str) -> dict[str, Any]:
        payload = {"name": name, "description": description}
        for path in ("/api/v1/knowledge/create", "/api/v1/knowledge"):
            try:
                response = self._request(
                    "POST",
                    path,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    expected=(200, 201),
                )
                return response.json()
            except Exception:
                continue
        raise RuntimeError(f"Unable to create knowledge base '{name}'")

    def ensure_knowledge(self, *, preferred_id: str | None, name: str, description: str) -> str:
        if preferred_id:
            existing = self.get_knowledge(preferred_id)
            if existing and str(existing.get("id", "")) == str(preferred_id):
                return str(preferred_id)

        matches = [kb for kb in self.list_knowledge() if str(kb.get("name", "")).strip().lower() == name.strip().lower()]
        if matches:
            # Verhindert weitere Dubletten: nimm deterministisch die kleinste ID
            selected = sorted(matches, key=lambda x: str(x.get("id", "")))[0]
            return str(selected["id"])

        created = self.create_knowledge(name, description)
        knowledge_id = created.get("id")
        if not knowledge_id:
            raise RuntimeError(f"Knowledge base '{name}' created but id missing")
        print(f"[sync] Created knowledge base '{name}' ({knowledge_id})")
        return str(knowledge_id)

    def upload_file(self, path: pathlib.Path) -> str:
        with path.open("rb") as handle:
            response = self._request(
                "POST",
                "/api/v1/files/",
                files={"file": (path.name, handle)},
                headers={"Accept": "application/json"},
            )
        body = response.json()
        file_id = body.get("id")
        if not file_id:
            raise RuntimeError(f"No file id returned after upload: {path}")
        return str(file_id)

    def wait_for_processing(self, file_id: str, timeout_seconds: int = 300) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = self._request("GET", f"/api/v1/files/{file_id}/process/status").json().get("status")
            if status == "completed":
                return
            if status == "failed":
                raise RuntimeError(f"File processing failed for {file_id}")
            time.sleep(2)
        raise TimeoutError(f"Timeout waiting for file processing: {file_id}")

    def add_file_to_knowledge(self, knowledge_id: str, file_id: str) -> None:
        self._request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/file/add",
            json={"file_id": file_id},
            headers={"Content-Type": "application/json"},
        )

    def remove_file_from_knowledge(self, knowledge_id: str, file_id: str) -> None:
        payload = {"file_id": file_id}
        for path in (
            f"/api/v1/knowledge/{knowledge_id}/file/remove",
            f"/api/v1/knowledge/{knowledge_id}/files/remove",
        ):
            try:
                self._request("POST", path, json=payload, headers={"Content-Type": "application/json"}, expected=(200, 201))
                return
            except Exception:
                continue
        print(f"[sync] WARN: Could not detach file {file_id} from knowledge {knowledge_id}")

    def delete_file(self, file_id: str) -> None:
        for path in (f"/api/v1/files/{file_id}", f"/api/v1/files/{file_id}/delete"):
            try:
                self._request("DELETE", path, expected=(200, 204))
                return
            except Exception:
                continue
        print(f"[sync] WARN: Could not delete file {file_id}")

    def ensure_workspace_model(self, *, workspace_model_id: str, workspace_model_name: str, base_model_id: str) -> None:
        try:
            models = self.list_models()
        except Exception as exc:
            print(f"[sync] WARN: Could not list models for workspace model sync: {exc}")
            return

        for model in models:
            if str(model.get("id", "")).strip() == workspace_model_id:
                return

        payload_candidates = [
            {
                "id": workspace_model_id,
                "name": workspace_model_name,
                "base_model_id": base_model_id,
            },
            {
                "id": workspace_model_id,
                "name": workspace_model_name,
                "base_model_id": base_model_id,
                "meta": {},
                "params": {},
            },
            {
                "id": workspace_model_id,
                "name": workspace_model_name,
                "model": base_model_id,
                "base_model_id": base_model_id,
                "meta": {},
                "params": {},
            },
        ]

        for path in ("/api/v1/models/create", "/api/v1/models/add"):
            for payload in payload_candidates:
                try:
                    self._request(
                        "POST",
                        path,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        expected=(200, 201),
                    )
                    print(f"[sync] Created workspace model '{workspace_model_name}' ({workspace_model_id})")
                    return
                except Exception:
                    continue

        print(
            "[sync] WARN: Could not auto-create workspace model. "
            "Please create it once manually in Workspace -> Models."
        )


def load_state(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"categories": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        state.setdefault("categories", {})
        return state
    except json.JSONDecodeError:
        return {"categories": {}}


def save_state(path: pathlib.Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def iter_knowledge_files(knowledge_dir: pathlib.Path, allowed_extensions: set[str]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for file_path in sorted(knowledge_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if any(part.startswith(".") for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in allowed_extensions:
            continue
        files.append(file_path)
    return files


def sync_once() -> None:
    base_url = env("OPEN_WEBUI_BASE_URL", "http://127.0.0.1:8080")
    email = env("OPEN_WEBUI_ADMIN_EMAIL")
    password = env("OPEN_WEBUI_ADMIN_PASSWORD")
    root_knowledge_name = env("OPEN_WEBUI_ROOT_KNOWLEDGE_NAME", "syn4ps3h0me")
    knowledge_prefix = env("OPEN_WEBUI_KNOWLEDGE_PREFIX", "")
    workspace_model_enabled = os.getenv("OPEN_WEBUI_WORKSPACE_MODEL_ENABLED", "true").lower() in {"1", "true", "yes"}
    workspace_model_id = env("OPEN_WEBUI_WORKSPACE_MODEL_ID", "llama3.2-3b-workspace")
    workspace_model_name = env("OPEN_WEBUI_WORKSPACE_MODEL_NAME", "Llama 3.2 3B (Workspace)")
    workspace_model_base_id = env("OPEN_WEBUI_WORKSPACE_MODEL_BASE_ID", "llama3.2:3b")
    knowledge_desc = env(
        "OPEN_WEBUI_KNOWLEDGE_DESCRIPTION",
        "Automatisch synchronisierte Projekt-Dokumentation aus /knowledge-import",
    )
    knowledge_dir = pathlib.Path(env("KNOWLEDGE_IMPORT_DIR", "/knowledge-import"))
    state_path = pathlib.Path(env("KNOWLEDGE_SYNC_STATE_FILE", "/sync-state/state.json"))
    allowed_extensions = parse_extensions(os.getenv("KNOWLEDGE_SYNC_EXTENSIONS"))

    if not knowledge_dir.exists():
        raise RuntimeError(f"Knowledge import directory not found: {knowledge_dir}")

    client = WebUIClient(base_url=base_url, email=email, password=password)

    if workspace_model_enabled:
        client.ensure_workspace_model(
            workspace_model_id=workspace_model_id,
            workspace_model_name=workspace_model_name,
            base_model_id=workspace_model_base_id,
        )

    state = load_state(state_path)
    categories_state: dict[str, Any] = state.setdefault("categories", {})

    files_by_category: dict[str, list[pathlib.Path]] = defaultdict(list)
    for file_path in iter_knowledge_files(knowledge_dir, allowed_extensions):
        files_by_category[category_for_path(knowledge_dir, file_path)].append(file_path)

    synced = 0
    skipped = 0
    removed = 0

    for category, category_files in sorted(files_by_category.items(), key=lambda x: x[0]):
        category_state = categories_state.setdefault(category, {"files": {}})
        category_state.setdefault("files", {})

        knowledge_name = root_knowledge_name if category == ROOT_CATEGORY_KEY else f"{knowledge_prefix}{category}"
        knowledge_id = client.ensure_knowledge(
            preferred_id=category_state.get("knowledge_id"),
            name=knowledge_name,
            description=knowledge_desc,
        )

        category_state["knowledge_id"] = knowledge_id
        category_state["knowledge_name"] = knowledge_name
        known_files: dict[str, Any] = category_state["files"]

        current_rel_paths = set()

        for file_path in category_files:
            rel_name = str(file_path.relative_to(knowledge_dir))
            current_rel_paths.add(rel_name)
            checksum = file_sha256(file_path)
            previous = known_files.get(rel_name)

            if previous and previous.get("sha256") == checksum:
                skipped += 1
                continue

            previous_file_id = previous.get("uploaded_file_id") if previous else None
            if previous_file_id:
                client.remove_file_from_knowledge(knowledge_id, str(previous_file_id))
                client.delete_file(str(previous_file_id))
                removed += 1

            new_file_id = client.upload_file(file_path)
            client.wait_for_processing(new_file_id)
            client.add_file_to_knowledge(knowledge_id, new_file_id)

            known_files[rel_name] = {
                "sha256": checksum,
                "uploaded_file_id": new_file_id,
                "synced_at_epoch": int(time.time()),
            }
            synced += 1

        stale_paths = [path for path in known_files if path not in current_rel_paths]
        for stale_rel in stale_paths:
            stale_file_id = known_files[stale_rel].get("uploaded_file_id")
            if stale_file_id:
                client.remove_file_from_knowledge(knowledge_id, str(stale_file_id))
                client.delete_file(str(stale_file_id))
                removed += 1
            del known_files[stale_rel]

    # Kategorien entfernen, die lokal nicht mehr existieren
    current_categories = set(files_by_category.keys())
    for stale_category in [c for c in categories_state if c not in current_categories]:
        stale_entry = categories_state[stale_category]
        knowledge_id = stale_entry.get("knowledge_id")
        for stale_rel, stale_file_meta in list(stale_entry.get("files", {}).items()):
            stale_file_id = stale_file_meta.get("uploaded_file_id")
            if stale_file_id and knowledge_id:
                client.remove_file_from_knowledge(str(knowledge_id), str(stale_file_id))
                client.delete_file(str(stale_file_id))
                removed += 1
            del stale_entry["files"][stale_rel]
        del categories_state[stale_category]

    save_state(state_path, state)
    print(f"[sync] Done. synced={synced}, skipped={skipped}, removed={removed}, categories={len(files_by_category)}")


def main() -> int:
    run_once = os.getenv("KNOWLEDGE_SYNC_RUN_ONCE", "false").lower() in {"1", "true", "yes"}
    interval_seconds = int(os.getenv("KNOWLEDGE_SYNC_INTERVAL_SECONDS", "120"))

    if run_once:
        sync_once()
        return 0

    while True:
        try:
            sync_once()
        except Exception as exc:
            print(f"[sync] Error: {exc}", file=sys.stderr)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
