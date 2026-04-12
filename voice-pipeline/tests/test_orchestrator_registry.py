import os
import time
from unittest.mock import Mock

from app.device_registry import DeviceRegistry
from app.integrations.llm_client import OllamaClient
from app.orchestrator import FunctionCallingOrchestrator
from app.tools import ToolCall


class FakeLLM:
    def __init__(self, call: ToolCall):
        self.call = call

    def propose_tool_call(self, user_text: str):
        return self.call, {"message": {"tool_calls": ["x"]}}


def _registry() -> DeviceRegistry:
    os.environ["SHELLY_DEVICE_MAP_FILE"] = "/tmp/does-not-exist.json"
    os.environ["DEVICE_REGISTRATION_TOKEN"] = "token-1"
    reg = DeviceRegistry()
    reg.register_device(
        {
            "id": "wohnzimmer_licht",
            "type": "shelly",
            "room": "wohnzimmer",
            "group": "lichter",
            "aliases": ["wohnzimmerlicht"],
            "base_url": "http://wz-licht.local",
            "command_path": "/script/light-control",
            "registration_token": "token-1",
        },
        client_ip="192.168.1.55",
    )
    return reg


def test_device_command_resolves_to_switch_tool() -> None:
    reg = _registry()
    orch = FunctionCallingOrchestrator(FakeLLM(ToolCall("switch_shelly_device", {"room": "wohnzimmer", "action": "on"})), reg)
    result = orch.plan("Schalte Wohnzimmerlicht an")
    assert result.tool_call.name == "switch_shelly_device"
    assert result.tool_call.arguments["device_id"] == "wohnzimmer_licht"


def test_ambiguous_command_returns_clarification() -> None:
    reg = _registry()
    reg.register_device(
        {
            "id": "wohnzimmer_licht_2",
            "room": "wohnzimmer",
            "group": "lichter",
            "aliases": ["wohnzimmerlicht"],
            "base_url": "http://wz-licht2.local",
            "registration_token": "token-1",
        },
        client_ip="192.168.1.56",
    )
    orch = FunctionCallingOrchestrator(FakeLLM(ToolCall("switch_shelly_device", {"room": "wohnzimmer", "action": "off"})), reg)
    result = orch.plan("mach licht aus")
    assert result.tool_call.name == "ask_for_clarification"


def test_chat_request_uses_answer_tool() -> None:
    reg = _registry()
    orch = FunctionCallingOrchestrator(FakeLLM(ToolCall("answer_with_llm", {"prompt": "Erkläre Quantenphysik"})), reg)
    result = orch.plan("Erkläre Quantenphysik")
    assert result.tool_call.name == "answer_with_llm"


def test_invalid_model_response_fallback() -> None:
    reg = _registry()
    orch = FunctionCallingOrchestrator(FakeLLM(ToolCall("switch_shelly_device", {"action": "off"})), reg)
    result = orch.plan("mach aus")
    assert result.tool_call.name == "ask_for_clarification"


def test_registration_rejects_invalid_token() -> None:
    reg = _registry()
    try:
        reg.register_device({"id": "x", "base_url": "http://x.local", "registration_token": "wrong"}, client_ip="192.168.1.3")
        assert False, "expected PermissionError"
    except PermissionError:
        pass


def test_registration_rejects_invalid_data() -> None:
    reg = _registry()
    try:
        reg.register_device({"id": "", "base_url": "bad-url", "registration_token": "token-1"}, client_ip="192.168.1.3")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_missing_heartbeat_marks_device_offline() -> None:
    os.environ["DEVICE_HEARTBEAT_TIMEOUT_SEC"] = "1"
    reg = _registry()
    device = reg.get_device("wohnzimmer_licht")
    assert device is not None
    device.last_seen = time.time() - 5
    changed = reg.mark_offline_devices()
    assert "wohnzimmer_licht" in changed
