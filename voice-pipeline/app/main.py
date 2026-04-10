import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .hailo_runtime import resolve_hailo_runtime_from_env, validate_hailo_runtime

import numpy as np
from openwakeword.model import Model


logging.basicConfig(
    level=os.getenv("VOICE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [voice-pipeline] %(message)s",
)
logger = logging.getLogger("voice_pipeline")


@dataclass
class ParsedCommand:
    raw_text: str
    normalized_text: str
    wake_word_detected: bool
    intent: str
    target_device: str | None
    action: str | None
    value: str | None


class RuleBasedParser:
    def parse(self, transcript: str, wake_word_detected: bool) -> ParsedCommand:
        normalized = re.sub(r"\s+", " ", transcript.strip().lower())
        target = "light" if re.search(r"\b(licht|lampe|beleuchtung)\b", normalized) else None
        if not target and re.search(r"\b(steckdose|socket|switch)\b", normalized):
            target = "switch"

        action: str | None = None
        value: str | None = None
        if re.search(r"\b(an|einschalten|ein)\b", normalized):
            action = "turn_on"
        elif re.search(r"\b(aus|ausschalten)\b", normalized):
            action = "turn_off"
        else:
            percentage_match = re.search(r"\b(\d{1,3})\s*(prozent|%)\b", normalized)
            if percentage_match:
                action = "set_value"
                value = percentage_match.group(1)

        intent = "unknown"
        if action in {"turn_on", "turn_off"}:
            intent = "device_control"
        elif action == "set_value":
            intent = "device_setting"

        return ParsedCommand(
            raw_text=transcript,
            normalized_text=normalized,
            wake_word_detected=wake_word_detected,
            intent=intent,
            target_device=target,
            action=action,
            value=value,
        )


class Transcriber:
    def __init__(self) -> None:
        self.mode = os.getenv("WHISPER_BACKEND", "hailo_local_cmd").lower()
        self.language = os.getenv("WHISPER_LANGUAGE", "de")
        self.cmd_timeout = int(os.getenv("HAILO_WHISPER_CMD_TIMEOUT", "120"))

        if self.mode != "hailo_local_cmd":
            raise ValueError("Nur WHISPER_BACKEND=hailo_local_cmd ist erlaubt.")

        self.runtime = resolve_hailo_runtime_from_env()
        validate_hailo_runtime(self.runtime)

        logger.info("Whisper-Modus: hailo_local_cmd.")
        logger.info("Hailo Whisper Kommando-Template: %s", self.runtime.whisper_cmd_template)
        logger.info("Hailo Venv Python: %s", self.runtime.hailo_python)

    def _extract_transcript(self, output: str) -> str | None:
        if not output.strip():
            return None

        lines = [line.strip() for line in output.splitlines() if line.strip()]

        for line in reversed(lines):
            if line.startswith("{") and line.endswith("}"):
                try:
                    payload = json.loads(line)
                    for key in ("text", "transcript", "result"):
                        value = payload.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()
                except json.JSONDecodeError:
                    pass

        for line in reversed(lines):
            normalized = line.lower()
            if normalized.startswith("transcript:"):
                return line.split(":", 1)[1].strip()

        return lines[-1]

    def _run_probe(self, label: str, cmd: str) -> None:
        result = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, check=False)
        output = (result.stdout or result.stderr or "").strip()
        logger.info("Hailo-Probe [%s] rc=%s output=%s", label, result.returncode, output)

    def _log_runtime_probe(self) -> None:
        escaped_dir = str(self.runtime.hailo_apps_dir)
        self._run_probe("pwd", f"cd {escaped_dir} && pwd")
        self._run_probe("ls_hailo_apps", f"ls -la {escaped_dir}")
        self._run_probe("ls_venv_bin", f"ls -la {self.runtime.hailo_python.parent}")
        self._run_probe("which_python", f"cd {escaped_dir} && source setup_env.sh && which python")
        self._run_probe("sys_executable", f'cd {escaped_dir} && source setup_env.sh && python -c "import sys; print(sys.executable)"')
        self._run_probe("hailo_platform_venv", f'{self.runtime.hailo_python} -c "import hailo_platform; print(hailo_platform.__file__)"')

    def transcribe(self, wav_path: Path) -> str | None:
        try:
            validate_hailo_runtime(self.runtime)
        except (FileNotFoundError, PermissionError) as exc:
            logger.error("Hailo-Runtime ungültig: %s", exc)
            return None

        self._log_runtime_probe()

        cmd = (
            self.runtime.whisper_cmd_template
            .replace("{audio_path}", str(wav_path))
            .replace("{language}", self.language)
            .replace("{hailo_apps_dir}", str(self.runtime.hailo_apps_dir))
            .replace("{hailo_python}", str(self.runtime.hailo_python))
        )
        logger.info("Starte Hailo-Whisper-Transkription über lokalen Command-Pfad.")

        try:
            result = subprocess.run(
                ["bash", "-lc", cmd],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.cmd_timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error("Hailo-Whisper Kommando lief in Timeout (%ss): %s", self.cmd_timeout, cmd)
            return None

        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        if result.returncode != 0:
            logger.error("Hailo-Whisper-Aufruf fehlgeschlagen (rc=%s).", result.returncode)
            logger.error("Whisper-Command: %s", cmd)
            logger.error("Whisper-Output: %s", combined_output.strip())
            return None

        transcript = self._extract_transcript(combined_output)
        if not transcript:
            logger.error("Hailo-Whisper lieferte leeres Ergebnis.")
            logger.error("Whisper-Output: %s", combined_output.strip())
            return None

        logger.info("Hailo-Whisper Transkription erfolgreich über lokalen Pfad.")
        return transcript


class VoicePipeline:
    def __init__(self) -> None:
        self.sample_rate = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
        self.wake_threshold = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
        self.wake_event_cooldown_seconds = float(os.getenv("WAKE_EVENT_COOLDOWN_SECONDS", "2.0"))
        self.post_wake_record_seconds = float(os.getenv("POST_WAKE_RECORD_SECONDS", "6"))
        self.wake_model_name = os.getenv("WAKEWORD_MODEL", "hey_jarvis")
        self.wake_model_path = os.getenv("WAKEWORD_MODEL_PATH", "").strip()
        self.device_refresh_seconds = int(os.getenv("AUDIO_DEVICE_REFRESH_SECONDS", "30"))

        self._stop_event = threading.Event()
        self._wake_events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=20)
        self._model: Model | None = None
        self._active_threads: dict[str, threading.Thread] = {}

        self._transcriber = Transcriber()
        self._parser = RuleBasedParser()

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
            is_monitor = name.endswith(".monitor")
            is_bluetooth = "bluez_input" in name
            sources.append(
                {
                    "index": parts[0],
                    "name": name,
                    "driver": parts[3] if len(parts) > 3 else "",
                    "is_monitor": is_monitor,
                    "is_bluetooth": is_bluetooth,
                    "accepted": not is_monitor,
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
        tmp = NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        wav_path = Path(tmp.name)

        timeout_seconds = max(2, int(self.post_wake_record_seconds + 1))
        cmd = [
            "timeout",
            str(timeout_seconds),
            "parecord",
            "--device", source_name,
            "--format=s16le",
            "--rate", str(self.sample_rate),
            "--channels", "1",
            "--file-format=wav",
            str(wav_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode not in (0, 124):
            logger.error("Folgeaufnahme fehlgeschlagen (rc=%s): %s", result.returncode, (result.stderr or result.stdout).strip())
            wav_path.unlink(missing_ok=True)
            return None

        if not wav_path.exists() or wav_path.stat().st_size < 2048:
            logger.error("Wake Word erkannt, aber Folgeaufnahme leer/zu klein für Source '%s'", source_name)
            wav_path.unlink(missing_ok=True)
            return None

        return wav_path

    def _handle_wake_event(self, event: dict[str, Any]) -> None:
        source_name = str(event["source_name"])
        recording = self._record_followup(source_name)
        if recording is None:
            return

        transcript = None
        try:
            transcript = self._transcriber.transcribe(recording)
        except Exception as exc:
            logger.exception("Hailo-Whisper-Transkription schlug fehl: %s", exc)
        finally:
            recording.unlink(missing_ok=True)

        if not transcript:
            logger.error("Hailo-Whisper nicht nutzbar oder leeres Ergebnis (source=%s).", source_name)
            return

        parsed = self._parser.parse(transcript, wake_word_detected=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_name": source_name,
            **asdict(parsed),
            "wake_score": float(event.get("score", 0.0)),
        }

        if parsed.intent == "unknown":
            logger.warning("Parser konnte keinen Befehl ableiten: '%s'", transcript)

        logger.info("Transkript: %s", transcript)
        logger.info("Parsed JSON: %s", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    VoicePipeline().run()
