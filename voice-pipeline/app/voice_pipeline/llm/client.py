from __future__ import annotations

import time

import requests


class LlmRestClient:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def chat(self, prompt: str) -> str:
        payload = {"prompt": prompt, "model": self.config.llm_model_name}
        last_error: str | None = None

        for attempt in range(self.config.llm_retries + 1):
            try:
                self.logger.info("[LLM] Request -> %s (attempt %s)", self.config.llm_api_endpoint, attempt + 1)
                response = requests.post(
                    self.config.llm_api_endpoint,
                    json=payload,
                    timeout=self.config.llm_timeout_seconds,
                )
                response.raise_for_status()
                answer = self._extract_answer(response.json())
                if answer:
                    self.logger.info('[LLM] Response text: "%s"', answer)
                    return answer
                last_error = "empty_response"
                self.logger.warning("[LLM] Leere Antwort erhalten.")
            except (requests.RequestException, ValueError) as exc:
                last_error = str(exc)
                self.logger.error("[LLM] Request fehlgeschlagen: %s", exc)

            if attempt < self.config.llm_retries:
                time.sleep(0.4)

        self.logger.warning("[LLM] Fallback-Antwort wird verwendet (error=%s)", last_error)
        return "Ich konnte gerade keine Antwort erzeugen."

    @staticmethod
    def _extract_answer(payload: dict) -> str | None:
        for key in ("answer", "response", "text", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
