from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .device_registry import DeviceRegistry
from .integrations.llm_client import OllamaClient
from .integrations.shelly_client import ShellyClient
from .tooling import build_tool_schemas, validate_tool_call, ToolValidationError, ValidatedToolCall


logger = logging.getLogger("voice_pipeline")


SYSTEM_PROMPT = (
    "Du bist ein strikt kontrollierter Function-Caller. "
    "Nutze ausschließlich bereitgestellte Tools aus der Whitelist. "
    "Keine URLs, keine HTTP-Methoden, keine Header, keine Tokens ausgeben. "
    "Bei unklaren/fehlenden Angaben verwende ask_for_clarification. "
    "Bei Geräteaktionen antworte nur als strukturierter Tool-Call."
)


@dataclass(frozen=True)
class OrchestrationResult:
    speech_text: str
    action_type: str
    tool_call: ValidatedToolCall


class CommandOrchestrator:
    def __init__(self, llm: OllamaClient, shelly: ShellyClient, registry: DeviceRegistry) -> None:
        self._llm = llm
        self._shelly = shelly
        self._registry = registry

    def handle_text(self, user_text: str) -> OrchestrationResult:
        self._llm.ensure_function_model_ready()

        raw_model = self._llm.chat_with_tools(user_text=user_text, tools=build_tool_schemas(), system_prompt=SYSTEM_PROMPT)
        logger.info("User-Text: %s", user_text)
        logger.info("Modellrohantwort: %s", json.dumps(raw_model, ensure_ascii=False))

        try:
            validated = validate_tool_call(raw_model)
        except (ToolValidationError, ValueError, TypeError) as exc:
            logger.warning("Modellantwort abgelehnt: %s", exc)
            fallback = ValidatedToolCall(
                name="ask_for_clarification",
                arguments={
                    "question": "Ich konnte den Befehl nicht sicher zuordnen. Kannst du das bitte präzisieren?",
                    "missing_fields": ["intent"],
                },
            )
            return OrchestrationResult(speech_text=fallback.arguments["question"], action_type="clarification", tool_call=fallback)

        logger.info("Validierter Tool-Call: %s", validated)

        if validated.name == "answer_with_llm":
            answer = self._llm.chat(validated.arguments["prompt"])
            return OrchestrationResult(speech_text=answer, action_type="chat", tool_call=validated)

        if validated.name == "ask_for_clarification":
            return OrchestrationResult(speech_text=str(validated.arguments["question"]), action_type="clarification", tool_call=validated)

        action = str(validated.arguments.get("action"))
        device_id = validated.arguments.get("device_id")
        room = validated.arguments.get("room")
        group = validated.arguments.get("group")
        alias = validated.arguments.get("alias")

        device, candidates = self._registry.resolve_device(
            device_id=str(device_id) if device_id else None,
            room=str(room) if room else None,
            group=str(group) if group else None,
            alias=str(alias) if alias else None,
        )

        if device is None:
            if len(candidates) > 1:
                question = "Ich habe mehrere passende Geräte gefunden. Welches meinst du genau?"
                return OrchestrationResult(
                    speech_text=question,
                    action_type="clarification",
                    tool_call=ValidatedToolCall(
                        name="ask_for_clarification",
                        arguments={
                            "question": question,
                            "candidates": [c.id for c in candidates],
                        },
                    ),
                )

            question = "Ich finde kein passendes Gerät. Nenne bitte Raum oder Gerätenamen."
            return OrchestrationResult(
                speech_text=question,
                action_type="clarification",
                tool_call=ValidatedToolCall(
                    name="ask_for_clarification",
                    arguments={"question": question, "missing_fields": ["device"]},
                ),
            )

        if not device.online:
            return OrchestrationResult(
                speech_text=f"Gerät {device.id} ist aktuell offline.",
                action_type="device_offline",
                tool_call=ValidatedToolCall(name="ask_for_clarification", arguments={"question": f"{device.id} ist offline. Soll ich ein anderes Gerät verwenden?"}),
            )

        response = self._shelly.send_action(device, action)
        if not response.success:
            raise RuntimeError(f"Geräteaktion fehlgeschlagen: {response.message}")

        spoken_action = {"on": "eingeschaltet", "off": "ausgeschaltet", "toggle": "umgeschaltet"}[action]
        speech = f"{device.id} wurde {spoken_action}."
        logger.info("Resultierende Aktion: %s", speech)
        return OrchestrationResult(speech_text=speech, action_type="device_action", tool_call=validated)
