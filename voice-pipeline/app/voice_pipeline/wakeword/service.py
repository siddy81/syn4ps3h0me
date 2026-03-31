from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from openwakeword.model import Model

from voice_pipeline.config import VoiceConfig


@dataclass
class WakeEvent:
    source_name: str
    score: float
    timestamp: float


class WakeWordDetector:
    def __init__(self, config: VoiceConfig, logger):
        self.config = config
        self.logger = logger
        self.model: Optional[Model] = None
        self._last_trigger_ts = 0.0

    def ensure_model(self) -> bool:
        if self.model is not None:
            return True
        try:
            if self.config.wake_model_path:
                self.model = Model(wakeword_model_paths=[self.config.wake_model_path])
            else:
                self.model = Model(wakeword_models=[self.config.wake_model_name])
            self.logger.info("[WAKEWORD] Model geladen.")
            return True
        except Exception as exc:
            self.logger.error("[WAKEWORD] Laden fehlgeschlagen: %s", exc)
            return False

    def detect_from_pcm16(self, source_name: str, pcm16: np.ndarray) -> WakeEvent | None:
        if self.model is None:
            return None
        scores = self.model.predict(pcm16)
        score = max(scores.values()) if scores else 0.0
        if score < self.config.wake_threshold:
            return None

        now = time.time()
        if now - self._last_trigger_ts < self.config.wake_event_cooldown_seconds:
            self.logger.debug("[WAKEWORD] Cooldown aktiv: source=%s score=%.3f", source_name, score)
            return None

        self._last_trigger_ts = now
        return WakeEvent(source_name=source_name, score=float(score), timestamp=now)
