from __future__ import annotations

import json
import logging
import re
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

        direct_intent = self._try_direct_shelly_intent(user_text)
        if direct_intent is not None:
            logger.info("Direkter Shelly-Intent erkannt (ohne LLM): %s", direct_intent)
            return self._execute_validated_call(direct_intent)

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

        return self._execute_validated_call(validated)

    def _execute_validated_call(self, validated: ValidatedToolCall) -> OrchestrationResult:
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

    def _try_direct_shelly_intent(self, user_text: str) -> ValidatedToolCall | None:
        text = user_text.strip().lower()
        if not text:
            return None

        if not re.search(r"\b(schalte|schalt|mache|mach|stelle|stell|toggle|umschalten)\b", text):
            return None

        action = None
        if re.search(r"\b(aus|ausschalten)\b", text):
            action = "off"
        elif re.search(r"\b(an|ein|einschalten)\b", text):
            action = "on"
        elif re.search(r"\b(toggle|umschalten)\b", text):
            action = "toggle"
        if action is None:
            return None

        matches = []
        for device in self._registry.all_devices():
            if device.room and device.room.lower() in text:
                matches.append(device)
                continue
            if device.group and device.group.lower() in text:
                matches.append(device)
                continue
            if any(alias.lower() in text for alias in device.aliases):
                matches.append(device)

        unique = {d.id: d for d in matches}
        if len(unique) == 1:
            device = next(iter(unique.values()))
            return ValidatedToolCall(name="switch_shelly_device", arguments={"device_id": device.id, "action": action})
        return None
