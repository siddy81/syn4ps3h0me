#!/usr/bin/env python3
import json
import os
import time
import mimetypes
from pathlib import Path
from urllib import request, error

OPENWEBUI_URL = os.getenv("OPENWEBUI_URL", "http://127.0.0.1:3000").rstrip("/")
EMAIL = os.getenv("OPENWEBUI_EMAIL", "")
PASSWORD = os.getenv("OPENWEBUI_PASSWORD", "")
STATE_FILE = Path(os.getenv("BOOTSTRAP_STATE_FILE", "/bootstrap/.knowledge_bootstrap_state.json"))
MAX_FILE_MB = int(os.getenv("KNOWLEDGE_MAX_FILE_MB", "25"))
POLL_TIMEOUT = int(os.getenv("KNOWLEDGE_PROCESS_TIMEOUT_SECONDS", "180"))
POLL_INTERVAL = float(os.getenv("KNOWLEDGE_PROCESS_POLL_SECONDS", "2"))

SOURCES = [
    {
        "name": os.getenv("KB_NAME_USER_CONTENT", "user-content"),
        "description": "Automatisch importierte User-Dateien aus knowledge-import/user-content",
        "path": Path("/knowledge/user-content"),
    },
    {
        "name": os.getenv("KB_NAME_REPO", "syn4ps3h0me-live"),
        "description": "Live-Quellcode und Konfigurationen des syn4ps3h0me-Repositories",
        "path": Path("/knowledge/syn4ps3h0me-live"),
    },
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
SKIP_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".bin", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mp3", ".wav"}


def log(msg: str) -> None:
    print(f"[knowledge-bootstrap] {msg}", flush=True)


def http_json(method: str, url: str, token: str | None = None, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, method=method, headers=headers, data=data)
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code} {body}") from exc


def auth_token() -> str:
    payload = {"email": EMAIL, "password": PASSWORD}
    data = http_json("POST", f"{OPENWEBUI_URL}/api/v1/auths/signin", payload=payload)
    token = data.get("token") or data.get("access_token")
    if not token:
        raise RuntimeError(f"No token in signin response keys={list(data.keys())}")
    return str(token)


def wait_openwebui() -> None:
    for i in range(60):
        try:
            with request.urlopen(f"{OPENWEBUI_URL}/health", timeout=5) as resp:
                if resp.status == 200:
                    log("Open WebUI ist erreichbar.")
                    return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("Open WebUI wurde nicht rechtzeitig erreichbar.")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def ensure_knowledge(token: str, name: str, description: str) -> str:
    existing = http_json("GET", f"{OPENWEBUI_URL}/api/v1/knowledge/", token=token)
    if isinstance(existing, list):
        for item in existing:
            if str(item.get("name", "")).strip() == name:
                return str(item["id"])

    payload = {"name": name, "description": description, "data": {}, "access_control": {}}
    created = http_json("POST", f"{OPENWEBUI_URL}/api/v1/knowledge/create", token=token, payload=payload)
    kid = created.get("id")
    if not kid:
        raise RuntimeError(f"Knowledge create lieferte keine ID: {created}")
    return str(kid)


def iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > MAX_FILE_MB:
            continue
        yield p


def upload_file(token: str, path: Path) -> str:
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()

    body = []
    body.append(f"--{boundary}\r\n".encode())
    body.append(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode())
    body.append(f"Content-Type: {mime}\r\n\r\n".encode())
    body.append(file_bytes)
    body.append(f"\r\n--{boundary}--\r\n".encode())
    data = b"".join(body)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = request.Request(f"{OPENWEBUI_URL}/api/v1/files/", method="POST", headers=headers, data=data)
    try:
        with request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload fehlgeschlagen für {path}: HTTP {exc.code} {body}") from exc

    file_id = payload.get("id")
    if not file_id:
        raise RuntimeError(f"Upload ohne file id für {path}: {payload}")
    return str(file_id)


def wait_file_processed(token: str, file_id: str) -> None:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        status = http_json("GET", f"{OPENWEBUI_URL}/api/v1/files/{file_id}/process/status", token=token)
        state = str(status.get("status", "")).lower()
        if state == "completed":
            return
        if state == "failed":
            raise RuntimeError(f"File processing failed for {file_id}: {status}")
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"Timeout waiting for file processing: {file_id}")


def add_to_knowledge(token: str, knowledge_id: str, file_id: str) -> None:
    http_json(
        "POST",
        f"{OPENWEBUI_URL}/api/v1/knowledge/{knowledge_id}/file/add",
        token=token,
        payload={"file_id": file_id},
    )


def fingerprint(path: Path) -> str:
    st = path.stat()
    return f"{int(st.st_mtime)}:{st.st_size}"


def main() -> int:
    if not EMAIL or not PASSWORD:
        log("OPENWEBUI_EMAIL / OPENWEBUI_PASSWORD fehlen - überspringe Bootstrap.")
        return 0

    wait_openwebui()
    token = auth_token()
    state = load_state()

    total_uploaded = 0

    for src in SOURCES:
        src_name = src["name"]
        root: Path = src["path"]
        if not root.exists():
            log(f"Quelle fehlt, überspringe: {root}")
            continue

        knowledge_id = ensure_knowledge(token, src_name, src["description"])
        src_state = state.setdefault(src_name, {})

        for path in iter_files(root):
            rel = str(path.relative_to(root))
            fp = fingerprint(path)
            if src_state.get(rel) == fp:
                continue

            try:
                log(f"Importiere {src_name}: {rel}")
                file_id = upload_file(token, path)
                wait_file_processed(token, file_id)
                add_to_knowledge(token, knowledge_id, file_id)
                src_state[rel] = fp
                total_uploaded += 1
            except Exception as exc:
                log(f"WARN: {exc}")

    save_state(state)
    log(f"Bootstrap abgeschlossen. Neu/aktualisiert: {total_uploaded} Dateien")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
