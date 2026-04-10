import re
from dataclasses import dataclass
from enum import Enum


class RouteTarget(str, Enum):
    LLM = "llm"
    SHELLY = "shelly"


@dataclass(frozen=True)
class SmartHomeCommand:
    action: str
    device: str
    room: str


@dataclass(frozen=True)
class RoutedCommand:
    raw_text: str
    normalized_text: str
    target: RouteTarget
    smart_home: SmartHomeCommand | None = None


def normalize_command(text: str, wake_word: str = "jarvis") -> str:
    normalized = text.strip()
    normalized = re.sub(r"^[\s,.;:!?-]+", "", normalized)
    wake_pattern = rf"^{re.escape(wake_word)}\b[\s,.;:!?-]*"
    normalized = re.sub(wake_pattern, "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


class CommandRouter:
    _kitchen_light_pattern = re.compile(
        r"\b(schalte|mach(?:e)?|küchenlicht|kuechenlicht)?\s*(das\s+)?(licht|lampe|küchenlicht|kuechenlicht)\b.*\b(aus|an)\b",
        re.IGNORECASE,
    )

    def route(self, raw_text: str) -> RoutedCommand:
        normalized = normalize_command(raw_text)
        lowered = normalized.lower()

        if self._is_kitchen_light_command(lowered):
            action = "off" if re.search(r"\baus\b", lowered) else "on"
            return RoutedCommand(
                raw_text=raw_text,
                normalized_text=normalized,
                target=RouteTarget.SHELLY,
                smart_home=SmartHomeCommand(action=action, device="licht", room="küche"),
            )

        return RoutedCommand(raw_text=raw_text, normalized_text=normalized, target=RouteTarget.LLM)

    def _is_kitchen_light_command(self, text: str) -> bool:
        if "küchenlicht" in text or "kuechenlicht" in text:
            return bool(re.search(r"\b(an|aus)\b", text))

        mentions_light = bool(re.search(r"\b(licht|lampe|beleuchtung)\b", text))
        mentions_kitchen = bool(re.search(r"\b(küche|kueche|küchen|kuechen)\b", text))
        mentions_state = bool(re.search(r"\b(an|aus|einschalten|ausschalten)\b", text))
        return mentions_light and mentions_kitchen and mentions_state
