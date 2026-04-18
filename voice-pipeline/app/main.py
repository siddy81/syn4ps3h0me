import json
import logging
import os
import queue
import subprocess
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np
from openwakeword.model import Model

from .error_messages import build_shelly_unavailable_message
from .integrations.llm_client import OllamaClient
from .integrations.shelly_client import ShellyClient
from .router import CommandRouter, RouteTarget
from .stt_whisper import create_transcriber
from .tts import TTSClient


logging.basicConfig(
    level=os.getenv("VOICE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [voice-pipeline] %(message)s",
)
logger = logging.getLogger("voice_pipeline")


class VoicePipeline:
    def __init__(self) -> None:
        self.sample_rate = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
        self.wake_threshold = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
        self.wake_event_cooldown_seconds = float(os.getenv("WAKE_EVENT_COOLDOWN_SECONDS", "2.0"))
        self.post_wake_record_max_seconds = float(os.getenv("POST_WAKE_RECORD_SECONDS", "6"))
        self.post_wake_record_min_seconds = float(os.getenv("POST_WAKE_MIN_RECORD_SECONDS", "0.45"))
        self.post_wake_silence_seconds = float(os.getenv("POST_WAKE_SILENCE_SECONDS", "0.35"))
        self.post_wake_silence_rms_threshold = float(os.getenv("POST_WAKE_SILENCE_RMS_THRESHOLD", "550"))
        self.wake_model_name = os.getenv("WAKEWORD_MODEL", "Nova")
        self.wake_model_path = os.getenv("WAKEWORD_MODEL_PATH", "").strip()
        self.device_refresh_seconds = int(os.getenv("AUDIO_DEVICE_REFRESH_SECONDS", "30"))
        self.whisper_preload = os.getenv("WHISPER_PRELOAD", "true").lower() == "true"

        self._stop_event = threading.Event()
        self._wake_events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=20)
        self._model: Model | None = None
        self._active_threads: dict[str, threading.Thread] = {}
        self._ready_announced = False

        self._transcriber = create_transcriber()
        self._router = CommandRouter()
        self._llm = OllamaClient()
        self._shelly = ShellyClient()
        self._tts = TTSClient()

        if self.whisper_preload:
            try:
                logger.info("Whisper-Preload aktiviert, lade Modell beim Start.")
                self._transcriber.preload()
            except Exception as exc:
                logger.warning("Whisper-Preload fehlgeschlagen, fallback auf lazy loading: %s", exc)

    @staticmethod
    def _run_cmd(cmd: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return result.returncode, result.stdout.strip() or result.stderr.strip()
        except FileNotFoundError:
            return 127, "command not found"

    def _list_pulse_sources(self) -> list[dict[str, Any]]:
        rc, output = self._run_cmd(["pactl", "list", "sources", "short"])
        if rc != 0:
            logger.warning("Konnte Pulse/PipeWire Sources nicht lesen (pactl rc=%s): %s", rc, output)
            return []

        sources: list[dict[str, Any]] = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1]
            sources.append(
                {
                    "index": parts[0],
                    "name": name,
                    "driver": parts[3] if len(parts) > 3 else "",
                    "is_monitor": name.endswith(".monitor"),
                    "is_bluetooth": "bluez_input" in name,
                    "accepted": not name.endswith(".monitor"),
                }
            )
        return sources

    def _log_audio_context(self) -> None:
        runtime_dir = os.getenv("XDG_RUNTIME_DIR", "")
        pulse_server = os.getenv("PULSE_SERVER", "")
        logger.info("Audio runtime: XDG_RUNTIME_DIR=%s PULSE_SERVER=%s PIPEWIRE_REMOTE=%s", runtime_dir, pulse_server, os.getenv("PIPEWIRE_REMOTE", ""))

        if runtime_dir:
            logger.info("PipeWire socket %s erreichbar=%s", f"{runtime_dir}/pipewire-0", Path(runtime_dir, "pipewire-0").exists())
            logger.info("Pulse socket %s erreichbar=%s", f"{runtime_dir}/pulse/native", Path(runtime_dir, "pulse/native").exists())

        rc, arecord_out = self._run_cmd(["arecord", "-l"])
        logger.info("ALSA Capture Devices (arecord -l, rc=%s): %s", rc, arecord_out if arecord_out else "<leer>")

    def _ensure_wake_model(self) -> bool:
        if self._model is not None:
            return True

        try:
            if self.wake_model_path:
                path = Path(self.wake_model_path)
                if not path.exists():
                    logger.error("WAKEWORD_MODEL_PATH existiert nicht: %s", path)
                    return False
                self._model = Model(wakeword_model_paths=[str(path)])
                logger.info("Wakeword über Model-Path geladen: %s", path)
                return True

            self._model = Model(wakeword_models=[self.wake_model_name])
            logger.info("Wakeword über Modellname geladen: %s", self.wake_model_name)
            return True
        except Exception as exc:
            logger.error("Wakeword-Laden fehlgeschlagen: %s", exc)
            return False

    def run(self) -> None:
        logger.info(
            "Starte Voice-Pipeline (wake model=%s, threshold=%.3f, cooldown=%.2fs)",
            self.wake_model_name,
            self.wake_threshold,
            self.wake_event_cooldown_seconds,
        )
        self._log_audio_context()

        while not self._stop_event.is_set():
            if not self._ensure_wake_model():
                time.sleep(self.device_refresh_seconds)
                continue

            all_sources = self._list_pulse_sources()
            accepted_sources = [s for s in all_sources if s["accepted"]]
            bluetooth_sources = [s for s in accepted_sources if s["is_bluetooth"]]

            logger.info("PipeWire/Pulse Sources (%d): %s", len(all_sources), json.dumps(all_sources, ensure_ascii=False))
            logger.info("Bluetooth Sources erkannt: %s", json.dumps(bluetooth_sources, ensure_ascii=False))

            if not accepted_sources:
                logger.error("Keine nutzbaren PipeWire/Pulse-Input-Sources gefunden.")
                time.sleep(self.device_refresh_seconds)
                continue

            known = {s["name"] for s in accepted_sources}
            for source in accepted_sources:
                name = source["name"]
                existing = self._active_threads.get(name)
                if existing and existing.is_alive():
                    continue
                t = threading.Thread(target=self._listen_on_source, args=(source,), daemon=True)
                self._active_threads[name] = t
                t.start()
                logger.info("Aktive Input-Quelle gewählt: %s", name)

            for stale in list(self._active_threads):
                if stale not in known:
                    logger.warning("Source nicht mehr vorhanden: %s", stale)
                    self._active_threads.pop(stale, None)

            if not self._ready_announced:
                self._tts.announce_ready()
                self._ready_announced = True

            try:
                event = self._wake_events.get(timeout=self.device_refresh_seconds)
                self._handle_wake_event(event)
            except queue.Empty:
                continue

    def _listen_on_source(self, source: dict[str, Any]) -> None:
        source_name = str(source["name"])
        cmd = [
            "parecord",
            "--raw",
            "--format=s16le",
            "--rate", str(self.sample_rate),
            "--channels", "1",
            "--device", source_name,
        ]
        logger.info("Starte Wake-Listener auf Pulse-Source: %s", source_name)

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None
        last_trigger_ts = 0.0

        try:
            chunk_samples = 1280
            chunk_bytes = chunk_samples * 2
            while not self._stop_event.is_set():
                data = proc.stdout.read(chunk_bytes)
                if not data or len(data) < chunk_bytes:
                    break

                pcm16 = np.frombuffer(data, dtype=np.int16)
                if self._model is None:
                    continue

                scores = self._model.predict(pcm16)
                score = max(scores.values()) if scores else 0.0
                if score >= self.wake_threshold:
                    now = time.time()
                    if now - last_trigger_ts < self.wake_event_cooldown_seconds:
                        logger.debug("Wake-Event wegen Cooldown verworfen (source=%s, score=%.3f)", source_name, score)
                        continue
                    last_trigger_ts = now
                    try:
                        self._wake_events.put_nowait(
                            {
                                "source_name": source_name,
                                "score": float(score),
                                "wake_word_detected": True,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        logger.info("Wake Word erkannt auf '%s' (score=%.3f)", source_name, score)
                    except queue.Full:
                        logger.warning("Wake-Event-Queue voll, Event verworfen.")
        finally:
            proc.kill()
            proc.wait(timeout=3)
            err = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
            if err.strip():
                logger.warning("parecord beendet (%s): %s", source_name, err.strip())

    def _record_followup(self, source_name: str) -> Path | None:
        logger.info("Aufnahme Folgekommando gestartet (source=%s)", source_name)
        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        wav_path = Path(tmp.name)

        cmd = [
            "parecord",
            "--device", source_name,
            "--raw",
            "--format=s16le",
            "--rate", str(self.sample_rate),
            "--channels", "1",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None

        frames: list[bytes] = []
        chunk_samples = 1024
        chunk_bytes = chunk_samples * 2
        start_ts = time.time()
        silent_since: float | None = None
        min_duration = max(0.2, self.post_wake_record_min_seconds)
        max_duration = max(min_duration + 0.2, self.post_wake_record_max_seconds)
        silence_seconds = max(0.15, self.post_wake_silence_seconds)

        try:
            while True:
                data = proc.stdout.read(chunk_bytes)
                if not data:
                    break
                frames.append(data)

                elapsed = time.time() - start_ts
                if elapsed >= max_duration:
                    break

                pcm16 = np.frombuffer(data, dtype=np.int16)
                if pcm16.size == 0:
                    continue

                rms = float(np.sqrt(np.mean(np.square(pcm16.astype(np.float32)))))
                speaking = rms >= self.post_wake_silence_rms_threshold

                if speaking:
                    silent_since = None
                    continue

                if elapsed < min_duration:
                    continue

                if silent_since is None:
                    silent_since = time.time()
                    continue

                if time.time() - silent_since >= silence_seconds:
                    break
        finally:
            proc.kill()
            proc.wait(timeout=3)
            if proc.stderr:
                err = proc.stderr.read().decode("utf-8", errors="ignore").strip()
                if err:
                    logger.debug("parecord stderr (followup, %s): %s", source_name, err)

        pcm = b"".join(frames)
        if len(pcm) < 2048:
            logger.error("Wake Word erkannt, aber Folgeaufnahme leer/zu klein für Source '%s'", source_name)
            wav_path.unlink(missing_ok=True)
            return None

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)

        if not wav_path.exists() or wav_path.stat().st_size < 2048:
            logger.error("Wake Word erkannt, aber Folgeaufnahme leer/zu klein für Source '%s'", source_name)
            wav_path.unlink(missing_ok=True)
            return None

        logger.info("Aufnahme Folgekommando beendet (source=%s, bytes=%s)", source_name, wav_path.stat().st_size)
        return wav_path

    def _handle_wake_event(self, event: dict[str, Any]) -> None:
        source_name = str(event["source_name"])
        self._tts.beep()
        recording = self._record_followup(source_name)
        if recording is None:
            return

        try:
            transcript = self._transcriber.transcribe_file(str(recording))
        except Exception as exc:
            logger.exception("Whisper-Transkription fehlgeschlagen: %s", exc)
            recording.unlink(missing_ok=True)
            return
        finally:
            recording.unlink(missing_ok=True)

        routed = self._router.route(transcript)
        logger.info("Normalisierter Befehl: %s", routed.normalized_text)
        logger.info("Erkannter Intent / Routing-Ziel: %s", routed.target.value)

        if routed.target == RouteTarget.SHELLY and routed.smart_home is not None:
            try:
                response = self._shelly.send(routed.smart_home)
                if response.success:
                    label = routed.smart_home.room or routed.smart_home.device or "Gerät"
                    confirmation = f"{label} ausgeschaltet" if routed.smart_home.action == "off" else f"{label} eingeschaltet"
                    logger.info("Smart-Home-Befehl erfolgreich: %s", response.message)
                    self._tts.speak(confirmation)
                else:
                    logger.error("Smart-Home-Befehl fehlgeschlagen: %s", response.message)
                    self._tts.speak(build_shelly_unavailable_message(response.message))
            except Exception as exc:
                logger.exception("Shelly-Integration fehlgeschlagen: %s", exc)
                self._tts.speak(build_shelly_unavailable_message(str(exc)))
            return

        try:
            llm_response = self._llm.chat(routed.normalized_text)
            self._tts.speak(llm_response)
        except Exception as exc:
            logger.exception("LLM-Integration fehlgeschlagen: %s", exc)


if __name__ == "__main__":
    VoicePipeline().run()
