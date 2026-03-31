from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np

from voice_pipeline.audio.recorder import AudioRecorder
from voice_pipeline.llm.client import LlmRestClient
from voice_pipeline.playback.player import AudioPlayer
from voice_pipeline.rules.engine import IntentRouter, RuleEngine
from voice_pipeline.stt.whisper_transcriber import WhisperTranscriber
from voice_pipeline.tts.piper_tts import PiperTtsService
from voice_pipeline.wakeword.service import WakeWordDetector


class VoiceOrchestrator:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.recorder = AudioRecorder(config, logger)
        self.detector = WakeWordDetector(config, logger)
        self.transcriber = WhisperTranscriber(config, logger)
        self.intent_router = IntentRouter()
        self.rule_engine = RuleEngine(logger)
        self.llm_client = LlmRestClient(config, logger)
        self.tts = PiperTtsService(config, logger)
        self.player = AudioPlayer(config, logger)

    def run_forever(self) -> None:
        self.logger.info("[WAKEWORD] Voice pipeline gestartet.")
        while True:
            if not self.detector.ensure_model():
                time.sleep(self.config.device_refresh_seconds)
                continue

            source = self._wait_for_wakeword()
            if not source:
                time.sleep(1)
                continue

            self._handle_command(source)

    def _wait_for_wakeword(self) -> str | None:
        sources = self.recorder.list_sources()
        if not sources:
            self.logger.warning("[AUDIO] Keine Eingabequellen gefunden.")
            return None

        source_name = sources[0]
        self.logger.info("[AUDIO] Wakeword-Quelle: %s", source_name)

        proc = self.recorder.stream_wake_audio(source_name)
        assert proc.stdout is not None
        chunk_samples = 1280
        chunk_bytes = chunk_samples * 2

        try:
            while True:
                data = proc.stdout.read(chunk_bytes)
                if not data or len(data) < chunk_bytes:
                    self.logger.warning("[AUDIO] Wake-Audio stream beendet.")
                    return None
                pcm16 = np.frombuffer(data, dtype=np.int16)
                event = self.detector.detect_from_pcm16(source_name, pcm16)
                if event:
                    self.logger.info("[WAKEWORD] Wake Word erkannt: source=%s score=%.3f", event.source_name, event.score)
                    return event.source_name
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _handle_command(self, source_name: str) -> None:
        recording = self.recorder.record_command(source_name)
        if not recording:
            self.logger.info("[AUDIO] Keine verwertbare Aufnahme vorhanden.")
            return

        try:
            transcript = self.transcriber.transcribe(recording)
        finally:
            recording.unlink(missing_ok=True)

        if not transcript:
            self.logger.info("[STT] Kein Text erkannt, LLM wird nicht aufgerufen.")
            return

        intent = self.intent_router.route(transcript)
        query_text = self.rule_engine.execute_tool(intent) if intent.name == "tool" else transcript

        answer = self.llm_client.chat(query_text)
        tts_file = self.tts.synthesize(answer)
        if not tts_file:
            self.logger.error("[TTS] Konnte Antwort nicht sprechen, Pipeline bleibt aktiv.")
            return

        try:
            self.player.play(tts_file)
        finally:
            Path(tts_file).unlink(missing_ok=True)
