from app.tools import ToolCall, validate_tool_call


def test_validate_switch_call_requires_action_and_selector():
    call = ToolCall(name="switch_shelly_device", arguments={"room": "wohnzimmer", "action": "on"})
    validated = validate_tool_call(call)
    assert validated.arguments["action"] == "on"


def test_validate_switch_call_rejects_without_selector():
    call = ToolCall(name="switch_shelly_device", arguments={"action": "off"})
    try:
        validate_tool_call(call)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_validate_chat_tool():
    call = ToolCall(name="answer_with_llm", arguments={"prompt": "Wie ist das Wetter?"})
    validated = validate_tool_call(call)
    assert validated.name == "answer_with_llm"


def test_validate_clarification_tool():
    call = ToolCall(name="ask_for_clarification", arguments={"question": "Welches Zimmer?"})
    validated = validate_tool_call(call)
    assert validated.name == "ask_for_clarification"
