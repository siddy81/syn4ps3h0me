from datetime import datetime, timedelta, timezone
import unittest

from app.device_registry import DeviceRegistry


class DeviceRegistryTests(unittest.TestCase):
    def _registry(self) -> DeviceRegistry:
        registry = DeviceRegistry()
        registry.registration_token = "secret"
        return registry

    def test_auto_registration_success(self) -> None:
        registry = self._registry()
        device = registry.register(
            {
                "registration_token": "secret",
                "id": "dev1",
                "type": "shelly_1pm",
                "room": "wohnzimmer",
                "group": "lichter",
                "aliases": ["wohnzimmerlicht"],
                "base_url": "http://192.168.1.44",
                "command_path": "/script/light-control",
                "capabilities": ["switch"],
            },
            source_ip="192.168.1.90",
        )
        self.assertEqual(device.id, "dev1")

    def test_invalid_registration_token_rejected(self) -> None:
        registry = self._registry()
        with self.assertRaises(ValueError):
            registry.register(
                {
                    "registration_token": "wrong",
                    "id": "dev1",
                    "base_url": "http://192.168.1.44",
                },
                source_ip="192.168.1.90",
            )

    def test_invalid_registration_data_rejected(self) -> None:
        registry = self._registry()
        with self.assertRaises(ValueError):
            registry.register(
                {
                    "registration_token": "secret",
                    "id": "",
                    "base_url": "http://192.168.1.44",
                },
                source_ip="192.168.1.90",
            )

    def test_missing_heartbeat_marks_offline(self) -> None:
        registry = self._registry()
        registry.heartbeat_timeout_sec = 1
        registry.register(
            {
                "registration_token": "secret",
                "id": "dev1",
                "base_url": "http://192.168.1.44",
                "command_path": "/script/light-control",
                "room": "wohnzimmer",
                "group": "lichter",
                "aliases": ["wohnzimmerlicht"],
                "capabilities": ["switch"],
            },
            source_ip="192.168.1.90",
        )

        registry._devices["dev1"].last_seen = datetime.now(timezone.utc) - timedelta(seconds=5)
        registry.mark_stale_devices_offline()
        self.assertFalse(registry.get_device("dev1").online)


if __name__ == "__main__":
    unittest.main()
