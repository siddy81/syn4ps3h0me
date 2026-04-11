import logging
import math
import os
import struct
import subprocess
import wave
from pathlib import Path
from tempfile import NamedTemporaryFile


logger = logging.getLogger("voice_pipeline")


class TTSClient:
    def __init__(self) -> None:
        self.template = os.getenv("TTS_SHELL_COMMAND", "").strip()
        self.auto_enabled = os.getenv("TTS_AUTO_ENABLED", "true").lower() == "true"
        self.language = os.getenv("TTS_LANGUAGE", "de")
        self.ready_announcement_enabled = os.getenv("READY_ANNOUNCEMENT_ENABLED", "true").lower() == "true"
        self.ready_announcement_text = os.getenv("READY_ANNOUNCEMENT_TEXT", "Ich bin jetzt einsatzbereit.").strip()
        self.wake_beep_enabled = os.getenv("WAKE_BEEP_ENABLED", "true").lower() == "true"
        self.wake_beep_frequency_hz = int(os.getenv("WAKE_BEEP_FREQUENCY_HZ", "880"))
        self.wake_beep_duration_ms = int(os.getenv("WAKE_BEEP_DURATION_MS", "120"))
        self.wake_beep_volume = float(os.getenv("WAKE_BEEP_VOLUME", "0.25"))

    @staticmethod
    def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)

    def _list_sinks(self) -> list[str]:
        result = self._run(["pactl", "list", "sinks", "short"])
        if result.returncode != 0:
            logger.warning("TTS: Konnte Ausgabegeräte nicht ermitteln (pactl rc=%s): %s", result.returncode, (result.stderr or result.stdout).strip())
            return []

        sinks: list[str] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            if name:
                sinks.append(name)
        return sinks

    def _speak_with_template(self, text: str) -> None:
        cmd = self.template.replace("{text}", text.replace('"', '\\"'))
        logger.info("TTS gestartet (custom command).")
        result = self._run(["bash", "-lc", cmd])
        if result.returncode != 0:
            logger.error("TTS fehlgeschlagen (rc=%s): %s", result.returncode, (result.stderr or result.stdout).strip())

    def _speak_auto_all_sinks(self, text: str) -> None:
        sinks = self._list_sinks()
        if not sinks:
            logger.warning("TTS: Keine Ausgabegeräte gefunden.")
            return

        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        wav_path = Path(tmp.name)

        synth = self._run(["espeak-ng", "-v", self.language, "-w", str(wav_path), text])
        if synth.returncode != 0:
            logger.error("TTS-Synthese fehlgeschlagen (rc=%s): %s", synth.returncode, (synth.stderr or synth.stdout).strip())
            wav_path.unlink(missing_ok=True)
            return

        success_count = 0
        for sink in sinks:
            env = os.environ.copy()
            env["PULSE_SINK"] = sink
            playback = self._run(["paplay", str(wav_path)], env=env)
            if playback.returncode == 0:
                success_count += 1
                logger.info("TTS-Ausgabe erfolgreich auf Sink: %s", sink)
            else:
                logger.warning("TTS-Ausgabe fehlgeschlagen auf Sink %s (rc=%s): %s", sink, playback.returncode, (playback.stderr or playback.stdout).strip())

        wav_path.unlink(missing_ok=True)
        logger.info("TTS-Autoplay abgeschlossen: %s/%s Sinks erfolgreich", success_count, len(sinks))

    def announce_ready(self) -> None:
        if not self.ready_announcement_enabled:
            return
        if not self.ready_announcement_text:
            return
        self.speak(self.ready_announcement_text)

    def beep(self) -> None:
        if not self.wake_beep_enabled:
            return

        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        wav_path = Path(tmp.name)

        try:
            self._write_sine_beep_wav(wav_path)
            playback = self._run(["paplay", str(wav_path)])
            if playback.returncode != 0:
                logger.warning("Wake-Beep fehlgeschlagen (rc=%s): %s", playback.returncode, (playback.stderr or playback.stdout).strip())
        finally:
            wav_path.unlink(missing_ok=True)

    def _write_sine_beep_wav(self, path: Path) -> None:
        sample_rate = 16000
        sample_count = max(1, int(sample_rate * (self.wake_beep_duration_ms / 1000.0)))
        volume = max(0.0, min(1.0, self.wake_beep_volume))
        amplitude = int(32767 * volume)

        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)

            frames = bytearray()
            for i in range(sample_count):
                value = int(amplitude * math.sin(2.0 * math.pi * self.wake_beep_frequency_hz * i / sample_rate))
                frames.extend(struct.pack("<h", value))
            wav.writeframes(bytes(frames))

    def speak(self, text: str) -> None:
        if not text.strip():
            return

        if self.template:
            self._speak_with_template(text)
            return

        if self.auto_enabled:
            logger.info("TTS gestartet (auto mode).")
            self._speak_auto_all_sinks(text)
            return

        logger.info("TTS übersprungen (kein TTS_SHELL_COMMAND konfiguriert und TTS_AUTO_ENABLED=false).")
