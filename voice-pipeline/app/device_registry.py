from __future__ import annotations

import ipaddress
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


logger = logging.getLogger("voice_pipeline")


@dataclass
class DeviceRecord:
    id: str
    type: str
    room: str
    group: str
    aliases: list[str]
    base_url: str
    command_path: str
    capabilities: list[str]
    registration_source: str = "static"
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    online: bool = True
    firmware_version: str | None = None
    model: str | None = None


class DeviceRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.heartbeat_timeout_sec = int(os.getenv("DEVICE_HEARTBEAT_TIMEOUT_SEC", "90"))
        self.registration_token = os.getenv("DEVICE_REGISTRATION_TOKEN", "CHANGE_ME")
        self.allow_private_networks_only = os.getenv("DEVICE_REGISTRY_PRIVATE_ONLY", "true").lower() == "true"
        self.default_command_path = os.getenv("SHELLY_DEFAULT_COMMAND_PATH", "/script/light-control")
        self._devices: dict[str, DeviceRecord] = {}
        self._load_static_devices()

    def _load_static_devices(self) -> None:
        raw_json = os.getenv("SHELLY_DEVICE_MAP_JSON", "").strip()
        map_file = Path(os.getenv("SHELLY_DEVICE_MAP_FILE", "/app/app/config/shelly_devices.json"))

        records: list[dict[str, Any]] = []
        if raw_json:
            records = json.loads(raw_json)
        elif map_file.exists():
            records = json.loads(map_file.read_text())

        for entry in records:
            try:
                normalized = self._normalize_registration_payload(entry, source_ip="127.0.0.1", is_static=True)
            except ValueError as exc:
                logger.warning("Überspringe statisches Device wegen Validierungsfehler: %s", exc)
                continue
            self._upsert(normalized)

        logger.info("Device Registry initialisiert: %s bekannte Geräte", len(self._devices))

    def register(self, payload: dict[str, Any], source_ip: str) -> DeviceRecord:
        if payload.get("registration_token") != self.registration_token:
            logger.warning("Ungültiger Registrierungstoken von %s", source_ip)
            raise ValueError("invalid_registration_token")

        normalized = self._normalize_registration_payload(payload, source_ip=source_ip, is_static=False)
        return self._upsert(normalized)

    def heartbeat(self, payload: dict[str, Any], source_ip: str) -> DeviceRecord:
        device_id = str(payload.get("id", "")).strip()
        if not device_id:
            raise ValueError("heartbeat_missing_id")

        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                raise ValueError("unknown_device")
            device.last_seen = datetime.now(timezone.utc)
            device.online = True
            logger.info("Device heartbeat: id=%s source=%s", device_id, source_ip)
            return device

    def all_devices(self) -> list[DeviceRecord]:
        self.mark_stale_devices_offline()
        with self._lock:
            return [self._copy_device(d) for d in self._devices.values()]

    def get_device(self, device_id: str) -> DeviceRecord | None:
        self.mark_stale_devices_offline()
        with self._lock:
            device = self._devices.get(device_id)
            return self._copy_device(device) if device else None

    def resolve_device(self, *, device_id: str | None, room: str | None, group: str | None, alias: str | None) -> tuple[DeviceRecord | None, list[DeviceRecord]]:
        self.mark_stale_devices_offline()
        with self._lock:
            devices = list(self._devices.values())

        matches: list[DeviceRecord] = []
        for device in devices:
            if device_id and device.id == device_id:
                matches.append(device)
                continue

            room_match = room and room.lower() == device.room.lower()
            group_match = group and group.lower() == device.group.lower()
            alias_match = alias and alias.lower() in {a.lower() for a in device.aliases}

            if room_match or group_match or alias_match:
                matches.append(device)

        unique = {d.id: d for d in matches}
        result = list(unique.values())
        if len(result) == 1:
            return result[0], result
        return None, result

    def mark_stale_devices_offline(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.heartbeat_timeout_sec)
        with self._lock:
            for device in self._devices.values():
                if device.last_seen < cutoff and device.online:
                    device.online = False
                    logger.warning("Device offline markiert: id=%s last_seen=%s", device.id, device.last_seen.isoformat())

    def _upsert(self, normalized: dict[str, Any]) -> DeviceRecord:
        device = DeviceRecord(**normalized)
        with self._lock:
            action = "update" if device.id in self._devices else "new"
            self._devices[device.id] = device
        logger.info("Device registration upsert (%s): id=%s room=%s group=%s source=%s", action, device.id, device.room, device.group, device.registration_source)
        return self._copy_device(device)

    def _normalize_registration_payload(self, payload: dict[str, Any], *, source_ip: str, is_static: bool) -> dict[str, Any]:
        device_id = str(payload.get("id", "")).strip()
        if not device_id:
            raise ValueError("device_id_required")

        base_url = str(payload.get("base_url", "")).strip()
        if not base_url:
            raise ValueError("base_url_required")

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("invalid_base_url_scheme")
        if not parsed.hostname:
            raise ValueError("invalid_base_url_host")

        if self.allow_private_networks_only:
            try:
                host_ip = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                host_ip = None
            if host_ip is not None and not host_ip.is_private:
                raise ValueError("base_url_not_private")

        if self.allow_private_networks_only and not is_static:
            ip_obj = ipaddress.ip_address(source_ip)
            if not ip_obj.is_private:
                raise ValueError("source_not_private")

        aliases = payload.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError("aliases_must_be_array")

        capabilities = payload.get("capabilities") or ["switch"]
        if not isinstance(capabilities, list):
            raise ValueError("capabilities_must_be_array")

        now = datetime.now(timezone.utc)
        return {
            "id": device_id,
            "type": str(payload.get("type", "shelly_1pm")).strip() or "shelly_1pm",
            "room": str(payload.get("room", "")).strip().lower(),
            "group": str(payload.get("group", "")).strip().lower(),
            "aliases": [str(a).strip().lower() for a in aliases if str(a).strip()],
            "base_url": f"{parsed.scheme}://{parsed.netloc}",
            "command_path": str(payload.get("command_path", self.default_command_path)).strip() or self.default_command_path,
            "capabilities": [str(c).strip().lower() for c in capabilities if str(c).strip()],
            "firmware_version": payload.get("firmware_version"),
            "model": payload.get("model"),
            "last_seen": now,
            "online": True,
            "registration_source": "static" if is_static else "auto",
        }

    @staticmethod
    def _copy_device(device: DeviceRecord) -> DeviceRecord:
        return DeviceRecord(
            id=device.id,
            type=device.type,
            room=device.room,
            group=device.group,
            aliases=list(device.aliases),
            base_url=device.base_url,
            command_path=device.command_path,
            capabilities=list(device.capabilities),
            registration_source=device.registration_source,
            last_seen=device.last_seen,
            online=device.online,
            firmware_version=device.firmware_version,
            model=device.model,
        )
