import json
import logging
import os
import time
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlparse

from ..tools import ToolCall, allowed_tools_schema

logger = logging.getLogger("voice_pipeline")

SYSTEM_INSTRUCTION = (
    "Du bist ein strikter Function-Calling Intent-Layer. "
    "Verwende ausschließlich bereitgestellte Tools. "
    "Erzeuge keine URLs, keine HTTP-Methoden, keine Header, keine Tokens und keine technischen Endpunkte. "
    "Bei unklaren/fehlenden Angaben nutze ask_for_clarification. "
    "Für Geräteaktionen nutze ausschließlich switch_shelly_device als strukturierten Tool-Call."
)


@dataclass(frozen=True)
class ModelPreloadStatus:
    ready: bool
    hailo_runtime: str
    preload_duration_ms: int
    warmup_ok: bool


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "http://host.docker.internal:8000")
        self.model = os.getenv("LLM_MODEL", "qwen2-1.5b-instruct-function-calling-v1")
        self.chat_model = os.getenv("LLM_CHAT_MODEL", "llama3.2:3b")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
        self.expect_hailo = os.getenv("LLM_EXPECT_HAILO", "true").lower() == "true"
        self._preload_status: ModelPreloadStatus | None = None

    def _candidate_base_urls(self) -> list[str]:
        primary = self.base_url.rstrip("/")
        candidates = [primary]
        parsed = urlparse(primary)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            fallback = primary.replace(parsed.hostname, "host.docker.internal", 1)
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def _post_json(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=self.timeout) as resp:
            response_text = resp.read().decode("utf-8", errors="replace")
        return json.loads(response_text)

    def _get_json(self, url: str) -> dict:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=self.timeout) as resp:
            response_text = resp.read().decode("utf-8", errors="replace")
        return json.loads(response_text)

    def preload(self) -> ModelPreloadStatus:
        if self._preload_status is not None and self._preload_status.ready:
            return self._preload_status

        started = time.monotonic()
        last_error: Exception | None = None

        for base_url in self._candidate_base_urls():
            try:
                hailo_runtime = "unknown"
                if self.expect_hailo:
                    list_payload = self._get_json(f"{base_url}/hailo/v1/list")
                    if self.model not in json.dumps(list_payload):
                        raise RuntimeError(f"Modell {self.model} nicht in hailo/v1/list vorhanden")
                    hailo_runtime = "hailo"

                warmup_payload = {
                    "model": self.model,
                    "stream": False,
                    "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}, {"role": "user", "content": "Warmup"}],
                    "tools": allowed_tools_schema(),
                    "tool_choice": {"type": "function", "function": {"name": "ask_for_clarification"}},
                }
                self._post_json(f"{base_url}/api/chat", warmup_payload)
                duration_ms = int((time.monotonic() - started) * 1000)
                self._preload_status = ModelPreloadStatus(True, hailo_runtime, duration_ms, True)
                logger.info(
                    "LLM Preload abgeschlossen model=%s hailo_runtime=%s dauer_ms=%s warmup_ok=true",
                    self.model,
                    hailo_runtime,
                    duration_ms,
                )
                return self._preload_status
            except Exception as exc:
                last_error = exc
                logger.warning("LLM Preload fehlgeschlagen für %s: %s", base_url, exc)

        raise RuntimeError(f"LLM preload fehlgeschlagen: {last_error}")

    def propose_tool_call(self, user_text: str, conversation_context: str | None = None) -> tuple[ToolCall, dict]:
        if self._preload_status is None:
            raise RuntimeError("LLM nicht vorgeladen. preload() muss beim Dienststart erfolgreich sein.")

        messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
        if conversation_context:
            messages.append({"role": "developer", "content": conversation_context})
        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.model,
            "stream": False,
            "messages": messages,
            "tools": allowed_tools_schema(),
        }

        last_error: Exception | None = None
        for base_url in self._candidate_base_urls():
            url = f"{base_url}/api/chat"
            try:
                raw = self._post_json(url, payload)
                message = raw.get("message", {})
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    raise RuntimeError("Modell lieferte keinen Tool-Call")
                first = tool_calls[0]
                function_data = first.get("function", {})
                name = function_data.get("name")
                args_raw = function_data.get("arguments", {})
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                if not isinstance(args, dict):
                    raise RuntimeError("Tool-Arguments sind kein Objekt")
                return ToolCall(name=name, arguments=args), raw
            except (error.URLError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                logger.warning("Function-Calling Request fehlgeschlagen (%s): %s", url, exc)
                continue

        raise RuntimeError(f"Function-Calling fehlgeschlagen: {last_error}")

    def chat(self, prompt: str) -> str:
        payload = {
            "model": self.chat_model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }

        last_error: Exception | None = None
        for base_url in self._candidate_base_urls():
            try:
                raw = self._post_json(f"{base_url}/api/chat", payload)
                content = str(raw.get("message", {}).get("content", "")).strip()
                if not content:
                    raise RuntimeError("LLM lieferte leeren Inhalt")
                return content
            except Exception as exc:
                last_error = exc
                continue

        raise RuntimeError(f"LLM-Aufruf fehlgeschlagen: {last_error}")
