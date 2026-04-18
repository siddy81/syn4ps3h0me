from dataclasses import dataclass

from app.device_registry import DeviceRegistry
from app.orchestration import CommandOrchestrator


@dataclass
class FakeShellyResponse:
    success: bool
    status_code: int
    message: str


class FakeShellyClient:
    def __init__(self) -> None:
        self.calls = []

    def send_action(self, device, action: str):
        self.calls.append((device.id, action))
        return FakeShellyResponse(success=True, status_code=200, message="ok")


class FakeLlmClient:
    def __init__(self, tool_call):
        self.tool_call = tool_call
        self.ready_checked = False

    def ensure_function_model_ready(self):
        self.ready_checked = True

    def chat_with_tools(self, user_text, tools, system_prompt, model=None):
        return self.tool_call

    def chat(self, prompt: str) -> str:
        return f"antwort:{prompt}"


def _registry() -> DeviceRegistry:
    registry = DeviceRegistry()
    registry.registration_token = "tok"
    registry.register(
        {
            "registration_token": "tok",
            "id": "wohnzimmer_licht",
            "type": "shelly_1pm",
            "room": "wohnzimmer",
            "group": "lichter",
            "aliases": ["wohnzimmerlicht"],
            "base_url": "http://192.168.1.50",
            "command_path": "/script/light-control",
            "capabilities": ["switch"],
        },
        source_ip="192.168.1.42",
    )
    return registry


def test_device_action_happy_path() -> None:
    llm = FakeLlmClient({"name": "switch_shelly_device", "arguments": {"room": "wohnzimmer", "action": "on"}})
    shelly = FakeShellyClient()
    orchestrator = CommandOrchestrator(llm=llm, shelly=shelly, registry=_registry())

    result = orchestrator.handle_text("Schalte Wohnzimmerlicht an")

    assert result.action_type == "device_action"
    assert shelly.calls == [("wohnzimmer_licht", "on")]


def test_ambiguous_request_returns_clarification() -> None:
    registry = _registry()
    registry.register(
        {
            "registration_token": "tok",
            "id": "wohnzimmer_licht_2",
            "type": "shelly_1pm",
            "room": "wohnzimmer",
            "group": "lichter",
            "aliases": ["deckenlicht"],
            "base_url": "http://192.168.1.51",
            "command_path": "/script/light-control",
            "capabilities": ["switch"],
        },
        source_ip="192.168.1.43",
    )
    llm = FakeLlmClient({"name": "switch_shelly_device", "arguments": {"room": "wohnzimmer", "action": "off"}})
    orchestrator = CommandOrchestrator(llm=llm, shelly=FakeShellyClient(), registry=registry)

    result = orchestrator.handle_text("Mach Wohnzimmerlicht aus")

    assert result.action_type == "clarification"
    assert result.tool_call.name == "ask_for_clarification"


def test_normal_chat_uses_answer_with_llm() -> None:
    llm = FakeLlmClient({"name": "answer_with_llm", "arguments": {"prompt": "Was ist 2+2?"}})
    orchestrator = CommandOrchestrator(llm=llm, shelly=FakeShellyClient(), registry=_registry())

    result = orchestrator.handle_text("Was ist 2+2?")

    assert result.action_type == "chat"
    assert "antwort" in result.speech_text


def test_invalid_model_answer_fallback() -> None:
    llm = FakeLlmClient({"name": "switch_shelly_device", "arguments": {"room": "wohnzimmer"}})
    orchestrator = CommandOrchestrator(llm=llm, shelly=FakeShellyClient(), registry=_registry())

    result = orchestrator.handle_text("Schalte an")

    assert result.action_type == "clarification"
    assert result.tool_call.name == "ask_for_clarification"
