from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile


class PiperTtsService:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def synthesize(self, text: str) -> Path | None:
        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        output_path = Path(tmp.name)

        cmd = ["piper", "--model", self.config.tts_voice_model, "--output_file", str(output_path)]
        if self.config.tts_voice_config:
            cmd += ["--config", self.config.tts_voice_config]

        self.logger.info("[TTS] Starte Piper TTS mit Stimme: %s", self.config.tts_voice_model)
        try:
            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                check=False,
                timeout=35,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            self.logger.error("[TTS] Piper konnte nicht gestartet werden: %s", exc)
            output_path.unlink(missing_ok=True)
            return None

        if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 512:
            self.logger.error("[TTS] Piper Fehler rc=%s stderr=%s", result.returncode, (result.stderr or "").strip())
            output_path.unlink(missing_ok=True)
            return None

        return output_path
