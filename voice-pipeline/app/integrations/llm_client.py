import json
import logging
import os
import re
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
        self.pull_on_preload_miss = os.getenv("LLM_PULL_ON_PRELOAD_MISS", "true").lower() == "true"
        self.strict_hailo_list = os.getenv("LLM_STRICT_HAILO_LIST", "false").lower() == "true"
        self._preload_status: ModelPreloadStatus | None = None
        self._native_tool_calling_available = True

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
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                response_text = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise RuntimeError(f"HTTP {exc.code} bei {url}: {err_body[:300]}") from exc
        return json.loads(response_text)

    def _post_json_or_ndjson(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=self.timeout) as resp:
            response_text = resp.read().decode("utf-8", errors="replace").strip()
        if not response_text:
            return {}
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            lines = [line.strip() for line in response_text.splitlines() if line.strip()]
            if not lines:
                return {}
            try:
                return json.loads(lines[-1])
            except json.JSONDecodeError:
                logger.warning("Konnte /api/pull Antwort nicht als JSON parsen, fahre mit Re-Check fort.")
                return {}

    def _get_json(self, url: str) -> dict:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=self.timeout) as resp:
            response_text = resp.read().decode("utf-8", errors="replace")
        return json.loads(response_text)

    @staticmethod
    def _model_matches(available_name: str, expected_model: str) -> bool:
        normalized = available_name.strip()
        return (
            normalized == expected_model
            or normalized.startswith(f"{expected_model}:")
            or normalized.endswith(f"/{expected_model}")
            or normalized.endswith(f"/{expected_model}:latest")
        )

    def _model_present_in_list(self, list_payload: dict) -> bool:
        if self.model in json.dumps(list_payload):
            return True
        models = list_payload.get("models")
        if not isinstance(models, list):
            return False
        for item in models:
            if isinstance(item, str) and self._model_matches(item, self.model):
                return True
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and self._model_matches(name, self.model):
                    return True
        return False

    @staticmethod
    def _extract_first_json_object(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json\n", "", 1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("Kein JSON-Objekt in Modellantwort gefunden")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise RuntimeError("JSON-Inhalt ist kein Objekt")
        return parsed

    @staticmethod
    def _heuristic_tool_call_from_text(user_text: str) -> ToolCall:
        text = user_text.lower().strip()
        text = re.sub(r"[^\wäöüß ]+", " ", text)

        action = None
        if any(token in text for token in (" einschalten", " schalte ", " an")):
            action = "on"
        if any(token in text for token in (" ausschalten", " aus")):
            action = "off"
        if any(token in text for token in (" um ", "toggle")):
            action = "toggle"

        if action and any(token in text for token in ("licht", "lampe", "schalte")):
            room = None
            room_match = re.search(r"\b([a-zäöüß]+)licht\b", text)
            if room_match:
                room = room_match.group(1)
            else:
                known_room = re.search(r"\b(wohnzimmer|küche|kueche|bad|flur|schlafzimmer|büro|buero)\b", text)
                if known_room:
                    room = known_room.group(1)
            if room:
                return ToolCall(name="switch_shelly_device", arguments={"room": room, "action": action})
            return ToolCall(
                name="ask_for_clarification",
                arguments={"question": "Welches Gerät oder welcher Raum soll geschaltet werden?", "missing_fields": ["room"]},
            )

        return ToolCall(name="answer_with_llm", arguments={"prompt": user_text})

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
                    if not self._model_present_in_list(list_payload):
                        if not self.pull_on_preload_miss:
                            raise RuntimeError(f"Modell {self.model} nicht in hailo/v1/list vorhanden")
                        logger.warning(
                            "Modell %s nicht in /hailo/v1/list gefunden. Versuche Pull über /api/pull.",
                            self.model,
                        )
                        self._post_json_or_ndjson(f"{base_url}/api/pull", {"model": self.model, "stream": False})
                        list_payload = self._get_json(f"{base_url}/hailo/v1/list")
                        if not self._model_present_in_list(list_payload):
                            msg = f"Modell {self.model} trotz /api/pull nicht in hailo/v1/list vorhanden"
                            if self.strict_hailo_list:
                                raise RuntimeError(msg)
                            logger.warning("%s; fahre im nicht-strikten Modus fort.", msg)
                            hailo_runtime = "unknown"
                        else:
                            hailo_runtime = "hailo"
                    else:
                        hailo_runtime = "hailo"

                warmup_payload = {
                    "model": self.model,
                    "stream": False,
                    "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}, {"role": "user", "content": "Warmup"}],
                    "tools": allowed_tools_schema(),
                    "tool_choice": {"type": "function", "function": {"name": "ask_for_clarification"}},
                }
                try:
                    self._post_json(f"{base_url}/api/chat", warmup_payload)
                    self._native_tool_calling_available = True
                except Exception:
                    fallback_payload = {
                        "model": self.model,
                        "stream": False,
                        "messages": [{"role": "user", "content": "Warmup: antworte nur mit ok."}],
                    }
                    self._post_json(f"{base_url}/api/chat", fallback_payload)
                    self._native_tool_calling_available = False
                    logger.warning("Native Tool-Calling Warmup fehlgeschlagen; Fallback-Warmup ohne Tools aktiv.")
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
        fallback_payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {
                    "role": "system",
                    "content": (
                        "Falls Tool-Calling technisch nicht verfügbar ist, antworte ausschließlich mit JSON im Format "
                        '{"name":"<tool_name>","arguments":{...}} ohne weitere Texte.'
                    ),
                },
                {"role": "user", "content": user_text},
            ],
        }

        last_error: Exception | None = None
        for base_url in self._candidate_base_urls():
            url = f"{base_url}/api/chat"
            try:
                if self._native_tool_calling_available:
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

                raw = self._post_json(url, fallback_payload)
                content = str(raw.get("message", {}).get("content", "")).strip()
                parsed = self._extract_first_json_object(content)
                name = parsed.get("name")
                args = parsed.get("arguments", {})
                if not isinstance(args, dict):
                    raise RuntimeError("Fallback-Tool-Arguments sind kein Objekt")
                return ToolCall(name=name, arguments=args), raw
            except (error.URLError, json.JSONDecodeError, RuntimeError) as exc:
                if self._native_tool_calling_available:
                    self._native_tool_calling_available = False
                    logger.warning("Tool-Calling API nicht verfügbar; wechsle auf JSON-Fallback (%s).", exc)
                    continue
                last_error = exc
                logger.warning("Function-Calling Request fehlgeschlagen (%s): %s", url, exc)
                continue

        logger.warning("Function-Calling komplett fehlgeschlagen, nutze heuristischen Fallback: %s", last_error)
        fallback_call = self._heuristic_tool_call_from_text(user_text)
        return fallback_call, {"fallback": "heuristic", "error": str(last_error)}

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
