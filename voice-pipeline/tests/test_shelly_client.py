import json
import os
import unittest
from unittest.mock import patch

from app.integrations.shelly_client import ShellyClient
from app.router import SmartHomeCommand


class ShellyClientTests(unittest.TestCase):
    def test_resolve_target_by_room_alias(self) -> None:
        mapping = [
            {
                "id": "kueche_lampe1",
                "room": "kueche",
                "group": "kueche",
                "aliases": ["küche", "kueche", "lampe1"],
                "base_url": "http://kueche-lampe1.local",
                "command_path": "/script/light-control",
            }
        ]
        with patch.dict(os.environ, {"SHELLY_DEVICE_MAP_JSON": json.dumps(mapping)}, clear=False):
            client = ShellyClient()

        cmd = SmartHomeCommand(action="off", room="kueche", device="licht", raw="schalte küche licht aus")
        target = client._resolve_target(cmd)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.id, "kueche_lampe1")


if __name__ == "__main__":
    unittest.main()
