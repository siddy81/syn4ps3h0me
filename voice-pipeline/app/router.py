import re
from dataclasses import dataclass
from enum import Enum


class RouteTarget(str, Enum):
    LLM = "llm"
    SHELLY = "shelly"


@dataclass(frozen=True)
class SmartHomeCommand:
    action: str
    room: str | None
    device: str | None
    raw: str


@dataclass(frozen=True)
class RoutedCommand:
    raw_text: str
    normalized_text: str
    target: RouteTarget
    smart_home: SmartHomeCommand | None = None


def normalize_command(text: str, wake_word: str = "Nova") -> str:
    normalized = text.strip()
    normalized = re.sub(r"^[\s,.;:!?-]+", "", normalized)
    wake_pattern = rf"^{re.escape(wake_word)}\b[\s,.;:!?-]*"
    normalized = re.sub(wake_pattern, "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


class CommandRouter:
    room_aliases: dict[str, tuple[str, ...]] = {
        "kueche": ("küche", "kueche", "küchen", "kuechen"),
        "wohnzimmer": ("wohnzimmer", "living room"),
        "schlafzimmer": ("schlafzimmer",),
    }

    device_aliases: dict[str, tuple[str, ...]] = {
        "licht": ("licht", "lampe", "beleuchtung", "lamp"),
        "lampe1": ("lampe 1", "lampe1"),
        "lampe2": ("lampe 2", "lampe2"),
    }

    def route(self, raw_text: str) -> RoutedCommand:
        normalized = normalize_command(raw_text)
        lowered = normalized.lower()

        action = self._extract_action(lowered)
        room = self._extract_alias(lowered, self.room_aliases)
        device = self._extract_alias(lowered, self.device_aliases)

        if action and (room or device) and re.search(r"\b(schalte|mache|mach|stell|schalt|an|aus|einschalten|ausschalten)\b", lowered):
            return RoutedCommand(
                raw_text=raw_text,
                normalized_text=normalized,
                target=RouteTarget.SHELLY,
                smart_home=SmartHomeCommand(action=action, room=room, device=device, raw=normalized),
            )

        return RoutedCommand(raw_text=raw_text, normalized_text=normalized, target=RouteTarget.LLM)

    def _extract_action(self, text: str) -> str | None:
        if re.search(r"\b(aus|ausschalten)\b", text):
            return "off"
        if re.search(r"\b(an|einschalten)\b", text):
            return "on"
        return None

    @staticmethod
    def _extract_alias(text: str, alias_map: dict[str, tuple[str, ...]]) -> str | None:
        for canonical, aliases in alias_map.items():
            for alias in aliases:
                escaped = re.escape(alias)
                if re.search(rf"\b{escaped}\b", text):
                    return canonical
                # Deutsche Komposita wie "wohnzimmerlicht" erkennen:
                # Prefix-/Suffix-Matches nur für längere Aliases erlauben.
                if len(alias) >= 4 and re.search(rf"\b{escaped}", text):
                    return canonical
                if len(alias) >= 4 and re.search(rf"{escaped}\b", text):
                    return canonical
        return None
