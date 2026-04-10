import logging
import os
import subprocess


logger = logging.getLogger("voice_pipeline")


class TTSClient:
    def __init__(self) -> None:
        self.template = os.getenv("TTS_SHELL_COMMAND", "").strip()
        self.enabled = bool(self.template)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        if not self.enabled:
            logger.info("TTS übersprungen (kein TTS_SHELL_COMMAND konfiguriert).")
            return

        cmd = self.template.replace("{text}", text.replace('"', '\\"'))
        logger.info("TTS gestartet.")
        result = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.error("TTS fehlgeschlagen (rc=%s): %s", result.returncode, (result.stderr or result.stdout).strip())
