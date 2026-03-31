from __future__ import annotations

import subprocess
import time
import wave
from pathlib import Path
from tempfile import NamedTemporaryFile


class AudioRecorder:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    @staticmethod
    def _run_cmd(cmd: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return result.returncode, result.stdout.strip() or result.stderr.strip()
        except FileNotFoundError:
            return 127, "command not found"

    def list_sources(self) -> list[str]:
        rc, output = self._run_cmd(["pactl", "list", "sources", "short"])
        if rc != 0:
            self.logger.warning("[AUDIO] pactl Fehler rc=%s: %s", rc, output)
            return []

        sources: list[str] = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            source_name = parts[1]
            if source_name.endswith(".monitor"):
                continue
            if self.config.mic_device and self.config.mic_device not in source_name:
                continue
            sources.append(source_name)
        return sources

    def stream_wake_audio(self, source_name: str):
        cmd = [
            "parecord",
            "--raw",
            "--format=s16le",
            "--rate", str(self.config.sample_rate),
            "--channels", str(self.config.channels),
            "--device", source_name,
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def record_command(self, source_name: str) -> Path | None:
        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        wav_path = Path(tmp.name)

        cmd = [
            "parecord",
            "--device", source_name,
            "--format=s16le",
            "--rate", str(self.config.sample_rate),
            "--channels", str(self.config.channels),
            "--file-format=wav",
            str(wav_path),
        ]

        self.logger.info("[AUDIO] Starte Aufnahme auf %s", source_name)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        start = time.time()

        while True:
            time.sleep(0.2)
            elapsed = time.time() - start
            if elapsed >= self.config.max_recording_duration_seconds:
                self.logger.info("[AUDIO] Max recording duration erreicht (%.1fs)", elapsed)
                break
            if self._has_silence_tail(wav_path):
                self.logger.info("[AUDIO] Silence timeout erkannt, stoppe Aufnahme.")
                break

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        if not wav_path.exists() or wav_path.stat().st_size < 2048:
            self.logger.warning("[AUDIO] Aufnahme leer oder zu klein.")
            wav_path.unlink(missing_ok=True)
            return None
        return wav_path

    def _has_silence_tail(self, wav_path: Path) -> bool:
        if not wav_path.exists() or wav_path.stat().st_size < 4096:
            return False
        try:
            with wave.open(str(wav_path), "rb") as wf:
                frame_rate = wf.getframerate()
                window_s = min(self.config.silence_timeout_seconds, wf.getnframes() / float(frame_rate))
                if window_s <= 0.0:
                    return False
                frames = int(window_s * frame_rate)
                wf.setpos(max(wf.getnframes() - frames, 0))
                data = wf.readframes(frames)
        except Exception:
            return False

        if not data:
            return False

        import audioop

        rms = audioop.rms(data, 2)
        return rms < self.config.min_voice_energy
