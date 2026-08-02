from __future__ import annotations

import json
import logging
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .device_registry import DeviceRecord, DeviceRegistry


logger = logging.getLogger("voice_pipeline")


class DeviceRegistryApiServer:
    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry
        self.host = os.getenv("DEVICE_REGISTRY_BIND_HOST", "0.0.0.0")
        self.port = int(os.getenv("DEVICE_REGISTRY_BIND_PORT", "8091"))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return

        server = ThreadingHTTPServer((self.host, self.port), self._handler_factory())
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="device-registry-api", daemon=True)
        self._thread.start()
        logger.info("Device Registry API gestartet auf %s:%s", self.host, self.port)

    def _handler_factory(self):
        registry = self.registry

        class Handler(BaseHTTPRequestHandler):
            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                return json.loads(raw.decode("utf-8"))

            def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _to_dict(self, device: DeviceRecord) -> dict[str, Any]:
                return {
                    "id": device.id,
                    "type": device.type,
                    "room": device.room,
                    "group": device.group,
                    "aliases": device.aliases,
                    "base_url": device.base_url,
                    "command_path": device.command_path,
                    "capabilities": device.capabilities,
                    "last_seen": device.last_seen.isoformat(),
                    "online": device.online,
                    "firmware_version": device.firmware_version,
                    "model": device.model,
                    "registration_source": device.registration_source,
                }

            def do_POST(self) -> None:  # noqa: N802
                source_ip = self.client_address[0]
                try:
                    payload = self._read_json()
                except Exception:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                    return

                if self.path == "/api/devices/register":
                    try:
                        device = registry.register(payload, source_ip=source_ip)
                    except ValueError as exc:
                        logger.warning("Registry register validation error: %s", exc)
                        self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                        return
                    self._write_json(HTTPStatus.OK, {"ok": True, "device": self._to_dict(device)})
                    return

                if self.path == "/api/devices/heartbeat":
                    try:
                        device = registry.heartbeat(payload, source_ip=source_ip)
                    except ValueError as exc:
                        self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                        return
                    self._write_json(HTTPStatus.OK, {"ok": True, "device": self._to_dict(device)})
                    return

                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/devices":
                    devices = [self._to_dict(device) for device in registry.all_devices()]
                    self._write_json(HTTPStatus.OK, {"ok": True, "devices": devices})
                    return

                if self.path.startswith("/api/devices/"):
                    device_id = self.path.split("/api/devices/", 1)[1].strip()
                    device = registry.get_device(device_id)
                    if device is None:
                        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
                        return
                    self._write_json(HTTPStatus.OK, {"ok": True, "device": self._to_dict(device)})
                    return

                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

            def log_message(self, fmt: str, *args: Any) -> None:
                logger.debug("device-registry-api: " + fmt, *args)

        return Handler
