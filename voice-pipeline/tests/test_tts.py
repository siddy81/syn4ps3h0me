import os
import unittest
from unittest.mock import patch

from app.tts import TTSClient


class FakeResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TTSTests(unittest.TestCase):
    def test_list_sinks_parses_all_outputs(self) -> None:
        client = TTSClient()
        with patch.object(client, "_run", return_value=FakeResult(0, "1\talsa_output.a\n2\tbluez_output.b\n")):
            sinks = client._list_sinks()
        self.assertEqual(sinks, ["alsa_output.a", "bluez_output.b"])

    def test_auto_mode_enabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TTSClient()
        self.assertTrue(client.auto_enabled)

    def test_announce_ready_uses_speak(self) -> None:
        with patch.dict(os.environ, {"READY_ANNOUNCEMENT_ENABLED": "true", "READY_ANNOUNCEMENT_TEXT": "bereit"}, clear=True):
            client = TTSClient()
        with patch.object(client, "speak") as speak:
            client.announce_ready()
        speak.assert_called_once_with("bereit")

    def test_beep_runs_paplay(self) -> None:
        client = TTSClient()
        with patch.object(client, "_run", return_value=FakeResult(0)) as run:
            client.beep()
        run.assert_called_once()
        called_cmd = run.call_args[0][0]
        self.assertEqual(called_cmd[0], "paplay")


if __name__ == "__main__":
    unittest.main()
