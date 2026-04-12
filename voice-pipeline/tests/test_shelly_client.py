import json
import os
from unittest.mock import patch

from app.device_registry import DeviceRegistry
from app.integrations.shelly_client import ShellyClient


class FakeResponse:
    def __init__(self, body: str, status: int = 200):
        self._body = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_send_switch_uses_resolved_device() -> None:
    mapping = [{"id": "wz_lampe", "room": "wohnzimmer", "group": "wz", "aliases": ["wohnzimmerlicht"], "base_url": "http://wz-lampe.local", "command_path": "/script/light-control"}]
    with patch.dict(os.environ, {"SHELLY_DEVICE_MAP_JSON": "", "SHELLY_DEVICE_MAP_FILE": "/tmp/nonexistent"}, clear=False):
        registry = DeviceRegistry()
        registry.register_device({"id": "wz_lampe", "base_url": "http://wz-lampe.local", "room": "wohnzimmer", "group": "wz", "aliases": ["wohnzimmerlicht"], "registration_token": os.getenv("DEVICE_REGISTRATION_TOKEN", "change-me")}, client_ip="192.168.1.77")
        client = ShellyClient(registry=registry)

    device = registry.get_device("wz_lampe")
    assert device is not None
    with patch("app.integrations.shelly_client.request.urlopen", return_value=FakeResponse('{"ok":true,"message":"done"}')):
        response = client.send_switch(device=device, action="on")
    assert response.success is True
    assert response.device_id == "wz_lampe"
