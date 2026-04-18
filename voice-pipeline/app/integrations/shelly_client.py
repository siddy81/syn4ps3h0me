import json
import logging
import os
from dataclasses import dataclass
from urllib import error, parse, request

from ..device_registry import DeviceRecord


logger = logging.getLogger("voice_pipeline")


@dataclass(frozen=True)
class ShellyResponse:
    success: bool
    status_code: int
    message: str


class ShellyClient:
    def __init__(self) -> None:
        self.timeout = float(os.getenv("SHELLY_TIMEOUT_SECONDS", "5"))

    def send_action(self, device: DeviceRecord, action: str) -> ShellyResponse:
        if action not in {"on", "off", "toggle"}:
            raise ValueError(f"Unerlaubte Shelly-Action: {action}")

        query = parse.urlencode({"action": action})
        url = f"{device.base_url.rstrip('/')}{device.command_path}?{query}"
        logger.info("Shelly-Request [%s]: %s", device.id, url)
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

        logger.info("Shelly-Response [%s]: status=%s success=%s body=%s", device.id, status, success, body)
        return ShellyResponse(success=success, status_code=status, message=message)
