from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ALLOWED_TOOL_NAMES = {"switch_shelly_device", "answer_with_llm", "ask_for_clarification"}
SHELLY_ACTIONS = {"on", "off", "toggle"}


@dataclass(frozen=True)
class ToolCall:
    name: Literal["switch_shelly_device", "answer_with_llm", "ask_for_clarification"]
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ValidatedToolCall:
    name: str
    arguments: dict[str, Any]


def allowed_tools_schema() -> list[dict[str, Any]]:
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
                "description": "Antwortet auf allgemeine Wissens- oder Chat-Anfragen ohne Geräteaktion.",
                "parameters": {
                    "type": "object",
                    "properties": {"prompt": {"type": "string"}},
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_for_clarification",
                "description": "Fordert fehlende Informationen oder klärt Mehrdeutigkeiten.",
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


def validate_tool_call(tool_call: ToolCall) -> ValidatedToolCall:
    if tool_call.name not in ALLOWED_TOOL_NAMES:
        raise ValueError(f"Unbekanntes Tool: {tool_call.name}")

    args = dict(tool_call.arguments)
    if tool_call.name == "switch_shelly_device":
        action = str(args.get("action", "")).lower().strip()
        if action not in SHELLY_ACTIONS:
            raise ValueError("switch_shelly_device.action muss on|off|toggle sein")
        args["action"] = action

        selectors = [args.get("device_id"), args.get("room"), args.get("group"), args.get("alias")]
        if not any(str(v).strip() for v in selectors if v is not None):
            raise ValueError("switch_shelly_device benötigt mindestens device_id|room|group|alias")

    elif tool_call.name == "answer_with_llm":
        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("answer_with_llm.prompt fehlt")
        args["prompt"] = prompt

    elif tool_call.name == "ask_for_clarification":
        question = str(args.get("question", "")).strip()
        if not question:
            raise ValueError("ask_for_clarification.question fehlt")
        args["question"] = question

    return ValidatedToolCall(name=tool_call.name, arguments=args)
