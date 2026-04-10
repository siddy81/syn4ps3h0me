import logging
import os
from pathlib import Path
from typing import Any


logger = logging.getLogger("voice_pipeline")


class WhisperHFTranscriber:
    def __init__(self) -> None:
        self.mode = os.getenv("WHISPER_MODE", "hf_local").lower()
        self.model_name = os.getenv("WHISPER_MODEL", "openai/whisper-base")
        self.language = os.getenv("WHISPER_LANGUAGE", "de")
        self.cache_dir = os.getenv("WHISPER_CACHE_DIR", "/models/huggingface")
        self._pipeline: Any = None

        if self.mode != "hf_local":
            raise ValueError("Nur WHISPER_MODE=hf_local wird unterstützt.")

        logger.info("STT-Modus: %s, Modell: %s, Sprache: %s, Cache: %s", self.mode, self.model_name, self.language, self.cache_dir)

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        logger.info("Lade Whisper-Modell lazy: %s", self.model_name)
        from transformers import pipeline

        self._pipeline = pipeline(
            task="automatic-speech-recognition",
            model=self.model_name,
            device=-1,
            model_kwargs={"cache_dir": self.cache_dir},
        )
        return self._pipeline

    def transcribe_file(self, audio_path: str, language: str | None = None) -> str:
        resolved_audio = Path(audio_path)
        if not resolved_audio.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {resolved_audio}")

        use_language = language or self.language
        asr = self._load_pipeline()
        logger.info("Starte Transkription: %s", resolved_audio)
        result = asr(
            str(resolved_audio),
            generate_kwargs={"language": use_language, "task": "transcribe"},
        )

        text = ""
        if isinstance(result, dict):
            text = str(result.get("text", "")).strip()

        if not text:
            raise RuntimeError("Whisper lieferte leeren Text.")

        logger.info("Rohtranskript: %s", text)
        print(f"[voice-pipeline] Transkript: {text}")
        return text
