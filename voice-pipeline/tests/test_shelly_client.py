from unittest.mock import patch

from app.device_registry import DeviceRecord
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


def test_send_action_success() -> None:
    client = ShellyClient()
    device = DeviceRecord(
        id="wohnzimmer_licht",
        type="shelly_1pm",
        room="wohnzimmer",
        group="lichter",
        aliases=["wohnzimmerlicht"],
        base_url="http://192.168.1.20",
        command_path="/script/light-control",
        capabilities=["switch"],
    )

    with patch("app.integrations.shelly_client.request.urlopen", return_value=FakeResponse('{"ok":true,"message":"on"}', 200)):
        response = client.send_action(device, "on")

    assert response.success is True
    assert response.message == "on"
