import json
import logging
import os
from dataclasses import dataclass
from urllib import error, parse, request

from ..device_registry import DeviceRecord, DeviceRegistry

logger = logging.getLogger("voice_pipeline")


@dataclass(frozen=True)
class ShellyResponse:
    success: bool
    status_code: int
    message: str
    device_id: str


class ShellyClient:
    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        self.timeout = float(os.getenv("SHELLY_TIMEOUT_SECONDS", "5"))
        self.registry = registry or DeviceRegistry()

    def send_switch(self, *, device: DeviceRecord, action: str) -> ShellyResponse:
        query = parse.urlencode({"action": action})
        url = f"{device.base_url.rstrip('/')}{device.command_path}?{query}"
        logger.info("Shelly execution request [%s]: %s", device.id, url)
        req = request.Request(url, method="GET")

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                status = getattr(resp, "status", 200)
        except error.URLError as exc:
            raise RuntimeError(f"Shelly-Request fehlgeschlagen: {exc}") from exc

        message = body
        success = 200 <= status < 300
        try:
            payload = json.loads(body)
            message = str(payload.get("message", payload))
            success = bool(payload.get("ok", success))
        except json.JSONDecodeError:
            pass

        logger.info("Shelly response [%s]: status=%s success=%s", device.id, status, success)
        return ShellyResponse(success=success, status_code=status, message=message, device_id=device.id)
