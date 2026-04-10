import json
import logging
import os
from urllib import error, request
from urllib.parse import urlparse


logger = logging.getLogger("voice_pipeline")


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "http://host.docker.internal:8000")
        self.model = os.getenv("LLM_MODEL", "llama3.2:3b")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))

    def _candidate_base_urls(self) -> list[str]:
        primary = self.base_url.rstrip("/")
        candidates = [primary]
        parsed = urlparse(primary)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            fallback = primary.replace(parsed.hostname, "host.docker.internal", 1)
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def chat(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        body = json.dumps(payload).encode("utf-8")

        last_error: Exception | None = None
        for base_url in self._candidate_base_urls():
            url = f"{base_url}/api/chat"
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            logger.info("LLM-Request: model=%s url=%s", self.model, url)
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    response_text = resp.read().decode("utf-8", errors="replace")
                payload = json.loads(response_text)
                message = payload.get("message", {})
                content = str(message.get("content", "")).strip()
                if not content:
                    raise RuntimeError("LLM lieferte leeren Inhalt.")
                logger.info("LLM-Response: %s", content)
                print(f"[voice-pipeline] LLM-Antwort: {content}")
                return content
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"LLM lieferte kein valides JSON: {response_text}") from exc
            except error.URLError as exc:
                last_error = exc
                logger.warning("LLM endpoint nicht erreichbar (%s): %s", url, exc)
                continue

        raise RuntimeError(f"LLM-Aufruf fehlgeschlagen: {last_error}")
