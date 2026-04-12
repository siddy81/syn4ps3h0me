from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
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
    last_seen: float
    online: bool
    firmware_version: str | None = None
    model: str | None = None
    source: str = "static"


@dataclass
class RegistryConfig:
    registration_token: str
    heartbeat_timeout_sec: int = 120
    allow_private_network_only: bool = True


class DeviceRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceRecord] = {}
        self._cfg = RegistryConfig(
            registration_token=os.getenv("DEVICE_REGISTRATION_TOKEN", "change-me"),
            heartbeat_timeout_sec=int(os.getenv("DEVICE_HEARTBEAT_TIMEOUT_SEC", "120")),
            allow_private_network_only=os.getenv("DEVICE_REGISTRY_PRIVATE_ONLY", "true").lower() == "true",
        )
        self._load_static_devices()

    def _load_static_devices(self) -> None:
        map_file = os.getenv("SHELLY_DEVICE_MAP_FILE", "/app/app/config/shelly_devices.json").strip()
        records: list[dict[str, Any]] = []
        path = Path(map_file)
        if path.exists():
            records = json.loads(path.read_text())

        now = time.time()
        with self._lock:
            for record in records:
                base_url = str(record.get("base_url", "")).strip()
                if not base_url:
                    continue
                device_id = str(record.get("id", "")).strip()
                if not device_id:
                    continue
                self._devices[device_id] = DeviceRecord(
                    id=device_id,
                    type=str(record.get("type", "shelly")),
                    room=str(record.get("room", "")).lower(),
                    group=str(record.get("group", "")).lower(),
                    aliases=[str(x).lower() for x in record.get("aliases", [])],
                    base_url=base_url,
                    command_path=str(record.get("command_path", "/script/light-control")),
                    capabilities=["switch"],
                    last_seen=now,
                    online=True,
                    firmware_version=record.get("firmware_version"),
                    model=record.get("model"),
                    source="static",
                )

    def _validate_base_url(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Ungültige base_url")

    def _validate_registration(self, payload: dict[str, Any], client_ip: str) -> None:
        if payload.get("registration_token") != self._cfg.registration_token:
            raise PermissionError("Ungültiger Registrierungstoken")
        if self._cfg.allow_private_network_only and not (
            client_ip.startswith("10.") or client_ip.startswith("192.168.") or client_ip.startswith("172.")
        ):
            raise PermissionError("Nur Geräte aus lokalem Netz erlaubt")

        if not str(payload.get("id", "")).strip():
            raise ValueError("device id fehlt")
        self._validate_base_url(str(payload.get("base_url", "")))

    def register_device(self, payload: dict[str, Any], client_ip: str) -> DeviceRecord:
        self._validate_registration(payload, client_ip)
        now = time.time()
        device_id = str(payload["id"]).strip()

        with self._lock:
            existing = self._devices.get(device_id)
            record = DeviceRecord(
                id=device_id,
                type=str(payload.get("type", "shelly")),
                room=str(payload.get("room", "")).lower(),
                group=str(payload.get("group", "")).lower(),
                aliases=[str(x).lower() for x in payload.get("aliases", [])],
                base_url=str(payload["base_url"]),
                command_path=str(payload.get("command_path", "/script/light-control")),
                capabilities=[str(x) for x in payload.get("capabilities", ["switch"])],
                last_seen=now,
                online=True,
                firmware_version=payload.get("firmware_version"),
                model=payload.get("model"),
                source="auto",
            )
            self._devices[device_id] = record
            logger.info("Registry upsert: id=%s neu=%s", device_id, existing is None)
            return record

    def heartbeat(self, payload: dict[str, Any]) -> DeviceRecord:
        device_id = str(payload.get("id", "")).strip()
        if not device_id:
            raise ValueError("heartbeat id fehlt")

        with self._lock:
            if device_id not in self._devices:
                raise KeyError("unbekanntes Gerät")
            record = self._devices[device_id]
            record.last_seen = time.time()
            record.online = True
            logger.info("Registry heartbeat: id=%s", device_id)
            return record

    def mark_offline_devices(self) -> list[str]:
        now = time.time()
        changed: list[str] = []
        with self._lock:
            for device_id, record in self._devices.items():
                if record.online and (now - record.last_seen) > self._cfg.heartbeat_timeout_sec:
                    record.online = False
                    changed.append(device_id)
                    logger.warning("Registry offline mark: id=%s", device_id)
        return changed

    def get_device(self, device_id: str) -> DeviceRecord | None:
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self) -> list[DeviceRecord]:
        with self._lock:
            return list(self._devices.values())

    def resolve_switch_target(self, args: dict[str, Any]) -> DeviceRecord | list[DeviceRecord] | None:
        device_id = str(args.get("device_id", "")).lower().strip()
        room = str(args.get("room", "")).lower().strip()
        group = str(args.get("group", "")).lower().strip()
        alias = str(args.get("alias", "")).lower().strip()

        with self._lock:
            if device_id:
                return self._devices.get(device_id)

            matches: list[DeviceRecord] = []
            for record in self._devices.values():
                if not record.online:
                    continue
                if room and room in {record.room, record.group}:
                    matches.append(record)
                    continue
                if group and group == record.group:
                    matches.append(record)
                    continue
                if alias and alias in record.aliases:
                    matches.append(record)

        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        return matches


def device_to_dict(device: DeviceRecord) -> dict[str, Any]:
    return asdict(device)
