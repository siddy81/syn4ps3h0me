import unittest

from app.router import CommandRouter, RouteTarget, normalize_command


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_normalize_removes_wake_word(self) -> None:
        self.assertEqual(normalize_command("Jarvis, erzähl mir einen Witz"), "erzähl mir einen Witz")

    def test_routes_kitchen_light_off(self) -> None:
        routed = self.router.route("Jarvis schalte das Licht in der Küche aus")
        self.assertEqual(routed.target, RouteTarget.SHELLY)
        assert routed.smart_home is not None
        self.assertEqual(routed.smart_home.action, "off")
        self.assertEqual(routed.smart_home.room, "kueche")
        self.assertEqual(routed.smart_home.device, "licht")

    def test_routes_general_prompt_to_llm(self) -> None:
        routed = self.router.route("Jarvis, erklär mir Quantenphysik")
        self.assertEqual(routed.target, RouteTarget.LLM)

    def test_routes_compound_room_device_token_to_shelly(self) -> None:
        routed = self.router.route("Jarvis, schalte das Wohnzimmerlicht aus")
        self.assertEqual(routed.target, RouteTarget.SHELLY)
        assert routed.smart_home is not None
        self.assertEqual(routed.smart_home.action, "off")
        self.assertEqual(routed.smart_home.room, "wohnzimmer")
        self.assertEqual(routed.smart_home.device, "licht")


if __name__ == "__main__":
    unittest.main()
