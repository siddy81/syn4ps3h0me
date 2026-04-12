from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from .device_registry import DeviceRegistry, device_to_dict

logger = logging.getLogger("voice_pipeline")


class RegistryApiServer:
    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry
        self.host = os.getenv("DEVICE_REGISTRY_BIND", "0.0.0.0")
        self.port = int(os.getenv("DEVICE_REGISTRY_PORT", "8091"))
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._httpd is not None:
            return

        registry = self.registry

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                data = self.rfile.read(length).decode("utf-8") if length else "{}"
                return json.loads(data or "{}")

            def log_message(self, format: str, *args):  # noqa: A003
                return

            def do_POST(self):  # noqa: N802
                client_ip = self.client_address[0]
                try:
                    payload = self._read_body()
                except json.JSONDecodeError:
                    self._json(400, {"ok": False, "error": "invalid_json"})
                    return

                try:
                    if self.path == "/api/devices/register":
                        record = registry.register_device(payload, client_ip=client_ip)
                        self._json(200, {"ok": True, "device": device_to_dict(record)})
                        return
                    if self.path == "/api/devices/heartbeat":
                        record = registry.heartbeat(payload)
                        self._json(200, {"ok": True, "device": device_to_dict(record)})
                        return
                    self._json(404, {"ok": False, "error": "not_found"})
                except PermissionError as exc:
                    logger.warning("Registry security reject: %s", exc)
                    self._json(403, {"ok": False, "error": str(exc)})
                except (ValueError, KeyError) as exc:
                    logger.warning("Registry validation reject: %s", exc)
                    self._json(400, {"ok": False, "error": str(exc)})

            def do_GET(self):  # noqa: N802
                if self.path == "/api/devices":
                    items = [device_to_dict(x) for x in registry.list_devices()]
                    self._json(200, {"ok": True, "devices": items})
                    return
                if self.path.startswith("/api/devices/"):
                    device_id = self.path.rsplit("/", 1)[-1]
                    device = registry.get_device(device_id)
                    if not device:
                        self._json(404, {"ok": False, "error": "not_found"})
                        return
                    self._json(200, {"ok": True, "device": device_to_dict(device)})
                    return
                self._json(404, {"ok": False, "error": "not_found"})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Device Registry API gestartet auf %s:%s", self.host, self.port)

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
