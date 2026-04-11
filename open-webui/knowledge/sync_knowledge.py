#!/usr/bin/env python3
"""Synchronisiert Dateien aus /knowledge-import in eine Open WebUI Knowledge Base."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time
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
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WebUIClient:
    def __init__(self, base_url: str, email: str, password: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.timeout = timeout
        self.token = self._login()

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
        if self.token:
            merged_headers["Authorization"] = f"Bearer {self.token}"
        response = requests.request(method, url, timeout=self.timeout, headers=merged_headers, **kwargs)
        if response.status_code not in expected:
            raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
        return response

    def _login(self) -> str:
        candidates = ("/api/v1/auths/signin", "/api/auths/signin")
        payload = {"email": self.email, "password": self.password}

        last_error: str | None = None
        for path in candidates:
            try:
                response = requests.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code != 200:
                    last_error = f"{path} -> {response.status_code} {response.text}"
                    continue
                body = response.json()
                token = body.get("token") or body.get("access_token")
                if token:
                    print(f"[sync] Authenticated via {path}")
                    return token
                last_error = f"{path} -> token missing in response"
            except requests.RequestException as exc:
                last_error = f"{path} -> {exc}"

        raise RuntimeError(f"Open WebUI login failed. Last error: {last_error}")

    def list_knowledge(self) -> list[dict[str, Any]]:
        for path in ("/api/v1/knowledge/", "/api/v1/knowledge"):
            try:
                response = self._request("GET", path)
                data = response.json()
                return data if isinstance(data, list) else data.get("data", [])
            except Exception:
                continue
        raise RuntimeError("Unable to list knowledge bases via /api/v1/knowledge endpoints")

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
        raise RuntimeError("Unable to create knowledge base (tried /create and /knowledge)")

    def ensure_knowledge(self, name: str, description: str) -> str:
        for kb in self.list_knowledge():
            if kb.get("name") == name:
                kb_id = kb.get("id")
                if kb_id:
                    print(f"[sync] Using existing knowledge base '{name}' ({kb_id})")
                    return str(kb_id)

        created = self.create_knowledge(name, description)
        kb_id = created.get("id")
        if not kb_id:
            raise RuntimeError(f"Knowledge base created but no id returned: {created}")
        print(f"[sync] Created knowledge base '{name}' ({kb_id})")
        return str(kb_id)

    def upload_file(self, path: pathlib.Path) -> str:
        with path.open("rb") as file_handle:
            response = self._request(
                "POST",
                "/api/v1/files/",
                files={"file": (path.name, file_handle)},
                headers={"Accept": "application/json"},
            )
        body = response.json()
        file_id = body.get("id")
        if not file_id:
            raise RuntimeError(f"Upload succeeded but no file id returned for {path}: {body}")
        print(f"[sync] Uploaded {path} -> file id {file_id}")
        return str(file_id)

    def wait_for_processing(self, file_id: str, timeout_seconds: int = 300) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = self._request("GET", f"/api/v1/files/{file_id}/process/status")
            body = response.json()
            status = body.get("status")
            if status == "completed":
                return
            if status == "failed":
                raise RuntimeError(f"File processing failed for {file_id}: {body}")
            time.sleep(2)
        raise TimeoutError(f"Timeout waiting for file processing: {file_id}")

    def add_file_to_knowledge(self, knowledge_id: str, file_id: str) -> None:
        self._request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/file/add",
            json={"file_id": file_id},
            headers={"Content-Type": "application/json"},
        )
        print(f"[sync] Added file {file_id} to knowledge {knowledge_id}")


def load_state(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"files": {}}


def save_state(path: pathlib.Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def iter_knowledge_files(knowledge_dir: pathlib.Path, allowed_extensions: set[str]) -> list[pathlib.Path]:
    files = []
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
    knowledge_name = env("OPEN_WEBUI_KNOWLEDGE_NAME", "syn4ps3h0me")
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
    knowledge_id = client.ensure_knowledge(knowledge_name, knowledge_desc)

    state = load_state(state_path)
    state_files: dict[str, dict[str, Any]] = state.setdefault("files", {})

    synced = 0
    skipped = 0

    for file_path in iter_knowledge_files(knowledge_dir, allowed_extensions):
        rel_name = str(file_path.relative_to(knowledge_dir))
        checksum = file_sha256(file_path)
        previous = state_files.get(rel_name)

        if previous and previous.get("sha256") == checksum:
            skipped += 1
            print(f"[sync] Skip unchanged: {rel_name}")
            continue

        file_id = client.upload_file(file_path)
        client.wait_for_processing(file_id)
        client.add_file_to_knowledge(knowledge_id, file_id)

        state_files[rel_name] = {
            "sha256": checksum,
            "uploaded_file_id": file_id,
            "synced_at_epoch": int(time.time()),
        }
        synced += 1

    save_state(state_path, state)
    print(f"[sync] Done. synced={synced}, skipped={skipped}, total={synced + skipped}")


def main() -> int:
    run_once = os.getenv("KNOWLEDGE_SYNC_RUN_ONCE", "false").lower() in {"1", "true", "yes"}
    interval_seconds = int(os.getenv("KNOWLEDGE_SYNC_INTERVAL_SECONDS", "120"))

    if run_once:
        sync_once()
        return 0

    while True:
        try:
            sync_once()
        except Exception as exc:  # keep sidecar alive and retry
            print(f"[sync] Error: {exc}", file=sys.stderr)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
