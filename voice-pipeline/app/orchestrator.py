from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .device_registry import DeviceRegistry
from .integrations.llm_client import OllamaClient
from .tools import ToolCall, ValidatedToolCall, validate_tool_call

logger = logging.getLogger("voice_pipeline")


@dataclass(frozen=True)
class OrchestrationResult:
    tool_call: ValidatedToolCall
    raw_model_response: dict[str, Any]
    rejected_reason: str | None = None


class FunctionCallingOrchestrator:
    def __init__(self, llm: OllamaClient, registry: DeviceRegistry) -> None:
        self._llm = llm
        self._registry = registry

    def plan(self, user_text: str) -> OrchestrationResult:
        tool_call, raw = self._llm.propose_tool_call(user_text)
        logger.info("Function calling raw response: %s", raw)
        try:
            validated = validate_tool_call(tool_call)
        except Exception as exc:
            logger.warning("Tool-Call verworfen: %s", exc)
            return OrchestrationResult(
                tool_call=ValidatedToolCall(
                    name="ask_for_clarification",
                    arguments={"question": "Ich konnte den Befehl nicht sicher auswerten. Kannst du ihn präzisieren?"},
                ),
                raw_model_response=raw,
                rejected_reason=str(exc),
            )

        if validated.name == "switch_shelly_device":
            resolved = self._registry.resolve_switch_target(validated.arguments)
            if resolved is None:
                return OrchestrationResult(
                    tool_call=ValidatedToolCall(
                        name="ask_for_clarification",
                        arguments={
                            "question": "Ich finde kein passendes Gerät. Welches Gerät meinst du genau?",
                            "missing_fields": ["device_id|room|group|alias"],
                        },
                    ),
                    raw_model_response=raw,
                    rejected_reason="unknown_device",
                )
            if isinstance(resolved, list):
                return OrchestrationResult(
                    tool_call=ValidatedToolCall(
                        name="ask_for_clarification",
                        arguments={
                            "question": "Ich habe mehrere Geräte gefunden. Welches davon soll geschaltet werden?",
                            "candidates": [x.id for x in resolved],
                        },
                    ),
                    raw_model_response=raw,
                    rejected_reason="ambiguous_device",
                )

            if not resolved.online:
                return OrchestrationResult(
                    tool_call=ValidatedToolCall(
                        name="ask_for_clarification",
                        arguments={"question": f"Gerät {resolved.id} ist aktuell offline."},
                    ),
                    raw_model_response=raw,
                    rejected_reason="device_offline",
                )

            args = dict(validated.arguments)
            args["device_id"] = resolved.id
            validated = ValidatedToolCall(name=validated.name, arguments=args)

        return OrchestrationResult(tool_call=validated, raw_model_response=raw)


def parse_tool_call_from_text(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(name=name, arguments=arguments)
