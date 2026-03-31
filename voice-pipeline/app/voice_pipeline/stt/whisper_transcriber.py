from __future__ import annotations

import json
import subprocess
from pathlib import Path


class WhisperTranscriber:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        if self.config.whisper_mode != "hailo_local_cmd":
            raise ValueError("Nur WHISPER_BACKEND=hailo_local_cmd ist unterstützt.")

    def transcribe(self, wav_path: Path) -> str | None:
        cmd = (
            self.config.hailo_whisper_cmd
            .replace("{audio_path}", str(wav_path))
            .replace("{language}", self.config.whisper_language)
            .replace("{hailo_apps_dir}", self.config.hailo_apps_dir)
            .replace("{hailo_python}", self.config.hailo_python)
        )
        self.logger.info("[STT] Starte Hailo Whisper.")
        try:
            result = subprocess.run(
                ["bash", "-lc", cmd],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.hailo_whisper_timeout,
            )
        except subprocess.TimeoutExpired:
            self.logger.error("[STT] Whisper Timeout nach %ss", self.config.hailo_whisper_timeout)
            return None

        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        if result.returncode != 0:
            self.logger.error("[STT] Whisper Fehler rc=%s", result.returncode)
            self.logger.debug("[STT] output=%s", output.strip())
            return None

        transcript = self._extract(output)
        if transcript:
            self.logger.info('[STT] [VOICE] Recognized text: "%s"', transcript)
        else:
            self.logger.info("[STT] Keine Sprache erkannt.")
        return transcript

    def _extract(self, output: str) -> str | None:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        for line in reversed(lines):
            if line.startswith("{") and line.endswith("}"):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for key in ("text", "transcript", "result"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        for line in reversed(lines):
            if line.lower().startswith("transcript:"):
                return line.split(":", 1)[1].strip()
        if lines:
            return lines[-1]
        return None
