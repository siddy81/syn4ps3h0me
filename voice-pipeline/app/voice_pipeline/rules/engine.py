from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Intent:
    name: str
    text: str
    params: dict


class IntentRouter:
    def route(self, text: str) -> Intent:
        normalized = text.strip().lower()
        # vorbereitete Hook für spätere Rule/Tool-Mappings
        if normalized.startswith("licht "):
            return Intent(name="tool", text=text, params={"tool": "light_control", "raw": text})
        return Intent(name="free_chat", text=text, params={})


class RuleEngine:
    def __init__(self, logger):
        self.logger = logger

    def execute_tool(self, intent: Intent) -> str:
        self.logger.info("[RULES] Tool-Intent erkannt, derzeit fallback auf free_chat: %s", intent.params)
        return intent.text
