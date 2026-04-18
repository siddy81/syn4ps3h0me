import json
import logging
import os
import time
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


logger = logging.getLogger("voice_pipeline")


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "http://host.docker.internal:8000")
        self.model = os.getenv("LLM_MODEL", "llama3.2:3b")
        self.function_model = os.getenv("FUNCTION_CALLING_MODEL", "qwen2-1.5b-instruct-function-calling-v1")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
        self.require_hailo = os.getenv("FUNCTION_CALLING_REQUIRE_HAILO", "true").lower() == "true"
        self._fc_ready = False

    def _candidate_base_urls(self) -> list[str]:
        primary = self.base_url.rstrip("/")
        candidates = [primary]
        parsed = urlparse(primary)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            fallback = primary.replace(parsed.hostname, "host.docker.internal", 1)
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        raw_response = ""

        for base_url in self._candidate_base_urls():
            url = f"{base_url}{path}"
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    raw_response = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw_response)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"LLM lieferte kein valides JSON: {raw_response}") from exc
            except error.URLError as exc:
                last_error = exc
                logger.warning("LLM endpoint nicht erreichbar (%s): %s", url, exc)

        raise RuntimeError(f"LLM-Aufruf fehlgeschlagen: {last_error}")

    def _get_json(self, path: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for base_url in self._candidate_base_urls():
            url = f"{base_url}{path}"
            req = request.Request(url, method="GET")
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
            except Exception as exc:
                last_error = exc
                logger.warning("GET %s fehlgeschlagen: %s", url, exc)
        raise RuntimeError(f"GET {path} fehlgeschlagen: {last_error}")

    def preload_function_model(self) -> None:
        start = time.time()
        logger.info("Beginne Preload Function-Calling-Modell: %s", self.function_model)

        model_list = self._get_json("/api/tags")
        names = {m.get("name") for m in model_list.get("models", []) if isinstance(m, dict)}
        if self.function_model not in names:
            raise RuntimeError(
                f"Function-Calling-Modell fehlt: {self.function_model}. Bitte vorab installieren (kein Lazy Loading erlaubt)."
            )

        if self.require_hailo:
            hailo_info = self._get_json("/hailo/v1/list")
            text = json.dumps(hailo_info).lower()
            if "hailo" not in text or "10h" not in text:
                raise RuntimeError("Hailo Runtime/Hardware nicht wie erwartet erkannt (Hailo-10H erforderlich).")
            logger.info("Hailo Runtime erkannt: %s", hailo_info)

        warmup = self.chat_with_tools(
            user_text="Schalte das Licht an.",
            tools=[],
            system_prompt="Gib nur JSON zurück: {\"name\":\"ask_for_clarification\",\"arguments\":{\"question\":\"ok?\"}}",
            model=self.function_model,
        )
        logger.info("Function-Calling Warmup erfolgreich: %s", warmup)
        self._fc_ready = True
        logger.info("Ende Modell-Preload, Dauer=%.2fs", time.time() - start)

    def ensure_function_model_ready(self) -> None:
        if not self._fc_ready:
            raise RuntimeError("Function-Calling-Modell nicht ready (Preload/Warmup fehlt).")

    def chat(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = self._post_json("/api/chat", payload)
        message = response.get("message", {})
        content = str(message.get("content", "")).strip()
        if not content:
            raise RuntimeError("LLM lieferte leeren Inhalt.")
        logger.info("LLM-Response: %s", content)
        return content

    def chat_with_tools(self, user_text: str, tools: list[dict[str, Any]], system_prompt: str, model: str | None = None) -> dict[str, Any]:
        payload = {
            "model": model or self.function_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "tools": tools,
        }
        response = self._post_json("/api/chat", payload)
        message = response.get("message", {}) if isinstance(response, dict) else {}

        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            first = tool_calls[0]
            function = first.get("function", {}) if isinstance(first, dict) else {}
            return {
                "name": function.get("name"),
                "arguments": function.get("arguments", {}),
                "raw_message": message,
            }

        content = str(message.get("content", "")).strip()
        if not content:
            raise RuntimeError("Function-Calling-Modell lieferte weder Tool-Call noch Content.")

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise RuntimeError("Function-Calling Content ist kein JSON-Objekt.")
        parsed["raw_message"] = message
        return parsed
