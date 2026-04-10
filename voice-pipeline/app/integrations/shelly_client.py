import json
import logging
import os
from dataclasses import dataclass
from urllib import error, parse, request


logger = logging.getLogger("voice_pipeline")


@dataclass(frozen=True)
class ShellyResponse:
    success: bool
    status_code: int
    message: str


class ShellyClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("SHELLY_KITCHEN_LIGHT_BASE_URL", "").strip()
        self.command_path = os.getenv("SHELLY_KITCHEN_LIGHT_COMMAND_PATH", "/script/light-control")
        self.timeout = float(os.getenv("SHELLY_TIMEOUT_SECONDS", "5"))

    def send_kitchen_light(self, action: str) -> ShellyResponse:
        if not self.base_url:
            raise RuntimeError("SHELLY_KITCHEN_LIGHT_BASE_URL ist nicht gesetzt.")

        query = parse.urlencode({"action": action})
        url = f"{self.base_url.rstrip('/')}{self.command_path}?{query}"
        logger.info("Shelly-Request: %s", url)
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

        logger.info("Shelly-Response: status=%s success=%s body=%s", status, success, body)
        return ShellyResponse(success=success, status_code=status, message=message)
