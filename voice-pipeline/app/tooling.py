from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_TOOL_NAMES = {
    "switch_shelly_device",
    "answer_with_llm",
    "ask_for_clarification",
}


@dataclass(frozen=True)
class ValidatedToolCall:
    name: str
    arguments: dict[str, Any]


class ToolValidationError(ValueError):
    pass


def build_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "switch_shelly_device",
                "description": "Schaltet ein bekanntes Shelly-Gerät.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string"},
                        "room": {"type": "string"},
                        "group": {"type": "string"},
                        "alias": {"type": "string"},
                        "action": {"type": "string", "enum": ["on", "off", "toggle"]},
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "answer_with_llm",
                "description": "Beantwortet eine normale Wissens- oder Chat-Anfrage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_for_clarification",
                "description": "Fragt den Nutzer nach fehlenden oder mehrdeutigen Angaben.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "missing_fields": {"type": "array", "items": {"type": "string"}},
                        "candidates": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["question"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def validate_tool_call(raw: dict[str, Any]) -> ValidatedToolCall:
    name = str(raw.get("name", "")).strip()
    if name not in ALLOWED_TOOL_NAMES:
        raise ToolValidationError(f"Tool '{name}' ist nicht erlaubt.")

    arguments = raw.get("arguments")
    if not isinstance(arguments, dict):
        raise ToolValidationError("Tool-Argumente fehlen oder sind nicht vom Typ Objekt.")

    normalized = {str(k): v for k, v in arguments.items()}

    if name == "switch_shelly_device":
        action = str(normalized.get("action", "")).strip().lower()
        if action not in {"on", "off", "toggle"}:
            raise ToolValidationError("switch_shelly_device.action muss on/off/toggle sein.")
        normalized["action"] = action

    if name == "answer_with_llm":
        prompt = str(normalized.get("prompt", "")).strip()
        if not prompt:
            raise ToolValidationError("answer_with_llm.prompt ist erforderlich.")
        normalized["prompt"] = prompt

    if name == "ask_for_clarification":
        question = str(normalized.get("question", "")).strip()
        if not question:
            raise ToolValidationError("ask_for_clarification.question ist erforderlich.")
        if "missing_fields" in normalized and not isinstance(normalized["missing_fields"], list):
            raise ToolValidationError("ask_for_clarification.missing_fields muss ein Array sein.")
        if "candidates" in normalized and not isinstance(normalized["candidates"], list):
            raise ToolValidationError("ask_for_clarification.candidates muss ein Array sein.")

    return ValidatedToolCall(name=name, arguments=normalized)
