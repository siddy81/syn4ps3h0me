import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request

from ..router import SmartHomeCommand


logger = logging.getLogger("voice_pipeline")


@dataclass(frozen=True)
class ShellyTarget:
    id: str
    room: str
    group: str
    aliases: tuple[str, ...]
    base_url: str
    command_path: str


@dataclass(frozen=True)
class ShellyResponse:
    success: bool
    status_code: int
    message: str


class ShellyClient:
    def __init__(self) -> None:
        self.timeout = float(os.getenv("SHELLY_TIMEOUT_SECONDS", "5"))
        self.default_command_path = os.getenv("SHELLY_DEFAULT_COMMAND_PATH", "/script/light-control")
        self._targets = self._load_targets()

    def _load_targets(self) -> list[ShellyTarget]:
        raw_json = os.getenv("SHELLY_DEVICE_MAP_JSON", "").strip()
        map_file = os.getenv("SHELLY_DEVICE_MAP_FILE", "/app/app/config/shelly_devices.json").strip()

        records: list[dict] = []
        if raw_json:
            records = json.loads(raw_json)
        elif Path(map_file).exists():
            records = json.loads(Path(map_file).read_text())

        targets: list[ShellyTarget] = []
        for record in records:
            base_url = str(record.get("base_url", "")).strip()
            if not base_url:
                continue
            targets.append(
                ShellyTarget(
                    id=str(record.get("id", "")),
                    room=str(record.get("room", "")).lower(),
                    group=str(record.get("group", "")).lower(),
                    aliases=tuple(str(x).lower() for x in record.get("aliases", [])),
                    base_url=base_url,
                    command_path=str(record.get("command_path", self.default_command_path)),
                )
            )

        logger.info("Shelly-Mapping geladen: %s Targets", len(targets))
        return targets

    def send(self, command: SmartHomeCommand) -> ShellyResponse:
        target = self._resolve_target(command)
        if target is None:
            raise RuntimeError(f"Kein Shelly-Mapping gefunden für room={command.room} device={command.device} text='{command.raw}'")

        query = parse.urlencode({"action": command.action})
        url = f"{target.base_url.rstrip('/')}{target.command_path}?{query}"
        logger.info("Shelly-Request [%s]: %s", target.id, url)
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

        logger.info("Shelly-Response [%s]: status=%s success=%s body=%s", target.id, status, success, body)
        return ShellyResponse(success=success, status_code=status, message=message)

    def _resolve_target(self, command: SmartHomeCommand) -> ShellyTarget | None:
        haystack = command.raw.lower()
        room = (command.room or "").lower()
        device = (command.device or "").lower()

        for target in self._targets:
            alias_match = any(alias in haystack for alias in target.aliases)
            room_match = room and room in {target.room, target.group}
            device_match = device and device in target.aliases
            if alias_match or room_match or device_match:
                return target
        return None
