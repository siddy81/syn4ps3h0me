import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol

from .hailo_runtime import resolve_hailo_runtime_from_env, validate_hailo_runtime


logger = logging.getLogger("voice_pipeline")


class WhisperTranscriber(Protocol):
    def preload(self) -> None:
        ...

    def transcribe_file(self, audio_path: str, language: str | None = None) -> str:
        ...


class WhisperHFTranscriber:
    def __init__(self) -> None:
        self.model_name = os.getenv("WHISPER_MODEL", "openai/whisper-base")
        self.language = os.getenv("WHISPER_LANGUAGE", "de")
        self.cache_dir = os.getenv("WHISPER_CACHE_DIR", "/models/huggingface")
        self._pipeline: Any = None
        logger.info("STT (HF): Modell=%s Sprache=%s Cache=%s", self.model_name, self.language, self.cache_dir)

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        logger.info("Lade Whisper-Modell lazy (HF): %s", self.model_name)
        from transformers import pipeline

        self._pipeline = pipeline(
            task="automatic-speech-recognition",
            model=self.model_name,
            device=-1,
            model_kwargs={"cache_dir": self.cache_dir},
        )
        return self._pipeline

    def preload(self) -> None:
        self._load_pipeline()

    def transcribe_file(self, audio_path: str, language: str | None = None) -> str:
        resolved_audio = Path(audio_path)
        if not resolved_audio.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {resolved_audio}")

        use_language = language or self.language
        asr = self._load_pipeline()
        logger.info("Starte Transkription (HF): %s", resolved_audio)
        result = asr(
            str(resolved_audio),
            generate_kwargs={"language": use_language, "task": "transcribe"},
        )

        text = ""
        if isinstance(result, dict):
            text = str(result.get("text", "")).strip()

        if not text:
            raise RuntimeError("Whisper (HF) lieferte leeren Text.")

        logger.info("Rohtranskript (HF): %s", text)
        print(f"[voice-pipeline] Transkript: {text}")
        return text


class WhisperHailoTranscriber:
    def __init__(self) -> None:
        self.language = os.getenv("WHISPER_LANGUAGE", "de")
        self._runtime = resolve_hailo_runtime_from_env()
        validate_hailo_runtime(self._runtime)
        logger.info(
            "STT (Hailo): apps_dir=%s python=%s language=%s",
            self._runtime.hailo_apps_dir,
            self._runtime.hailo_python,
            self.language,
        )

    def preload(self) -> None:
        # Runtime-Validation passiert bereits im ctor.
        return None

    def _build_cmd(self, audio_path: Path, language: str) -> str:
        return self._runtime.whisper_cmd_template.format(
            hailo_apps_dir=shlex.quote(str(self._runtime.hailo_apps_dir)),
            hailo_python=shlex.quote(str(self._runtime.hailo_python)),
            audio_path=shlex.quote(str(audio_path)),
            language=shlex.quote(language),
        )

    @staticmethod
    def _extract_transcript(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Whisper (Hailo) lieferte keine Ausgabe.")

        patterns = (
            re.compile(r"^(?:transcript|transcription|text)\s*[:=]\s*(.+)$", re.IGNORECASE),
            re.compile(r"^\[voice-pipeline\]\s*transkript\s*:\s*(.+)$", re.IGNORECASE),
        )
        for line in reversed(lines):
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    text = match.group(1).strip()
                    if text:
                        return text

        # Fallback: letzte sinnvolle Zeile nehmen, die nicht wie Log-Metadaten aussieht.
        for line in reversed(lines):
            if line.startswith("[") and "]" in line:
                continue
            if re.search(r"\b(info|debug|warn|error)\b", line, re.IGNORECASE):
                continue
            return line

        return lines[-1]

    def transcribe_file(self, audio_path: str, language: str | None = None) -> str:
        resolved_audio = Path(audio_path)
        if not resolved_audio.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {resolved_audio}")

        use_language = language or self.language
        cmd = self._build_cmd(resolved_audio, use_language)
        logger.info("Starte Transkription (Hailo): %s", resolved_audio)
        result = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, check=False)

        output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        if result.returncode != 0:
            raise RuntimeError(f"Whisper (Hailo) fehlgeschlagen (rc={result.returncode}): {output}")

        text = self._extract_transcript(output)
        if not text:
            raise RuntimeError("Whisper (Hailo) lieferte leeren Text.")

        logger.info("Rohtranskript (Hailo): %s", text)
        print(f"[voice-pipeline] Transkript: {text}")
        return text


def create_transcriber() -> WhisperTranscriber:
    mode = os.getenv("WHISPER_MODE", "hf_local").strip().lower()
    logger.info("STT-Modus konfiguriert: %s", mode)

    if mode in {"hailo", "hailo_local", "hailo_whisper"}:
        return WhisperHailoTranscriber()

    if mode == "auto":
        try:
            return WhisperHailoTranscriber()
        except Exception as exc:
            logger.warning("STT auto: Hailo nicht nutzbar, fallback auf HF. Grund: %s", exc)
            return WhisperHFTranscriber()

    if mode == "hf_local":
        return WhisperHFTranscriber()

    raise ValueError("Ungültiger WHISPER_MODE. Erlaubt: hf_local, hailo_local, auto")
