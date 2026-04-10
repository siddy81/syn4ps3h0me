import json
import logging
import os
from urllib import error, request


logger = logging.getLogger("voice_pipeline")


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "http://host.docker.internal:8000")
        self.model = os.getenv("LLM_MODEL", "llama3.2:3b")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))

    def chat(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        url = f"{self.base_url.rstrip('/')}/api/chat"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        logger.info("LLM-Request: model=%s url=%s", self.model, url)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                response_text = resp.read().decode("utf-8", errors="replace")
        except error.URLError as exc:
            raise RuntimeError(f"LLM-Aufruf fehlgeschlagen: {exc}") from exc

        try:
            payload = json.loads(response_text)
            message = payload.get("message", {})
            content = str(message.get("content", "")).strip()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM lieferte kein valides JSON: {response_text}") from exc

        if not content:
            raise RuntimeError("LLM lieferte leeren Inhalt.")

        logger.info("LLM-Response: %s", content)
        print(f"[voice-pipeline] LLM-Antwort: {content}")
        return content
