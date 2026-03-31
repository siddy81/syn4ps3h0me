from __future__ import annotations

import subprocess
from pathlib import Path


class AudioPlayer:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def play(self, wav_path: Path) -> bool:
        cmd = [self.config.playback_cmd]
        if self.config.playback_cmd == "aplay" and self.config.output_device:
            cmd += ["-D", self.config.output_device]
        cmd += [str(wav_path)]

        try:
            self.logger.info("[PLAYBACK] Spiele Audio ab: %s", wav_path)
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            self.logger.error("[PLAYBACK] Playback-Fehler: %s", exc)
            return False

        if result.returncode != 0:
            self.logger.error("[PLAYBACK] Playback fehlgeschlagen rc=%s stderr=%s", result.returncode, (result.stderr or "").strip())
            return False
        return True
