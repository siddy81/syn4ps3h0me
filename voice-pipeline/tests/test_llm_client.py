import json
import os
from unittest.mock import patch
from urllib import error

from app.integrations.llm_client import OllamaClient


class FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_preload_requires_hailo_and_warmup() -> None:
    with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:8000", "LLM_EXPECT_HAILO": "true", "LLM_MODEL": "qwen2-1.5b-instruct-function-calling-v1"}, clear=False):
        client = OllamaClient()

    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if req.full_url.endswith("/hailo/v1/list"):
            return FakeResponse('{"models":["qwen2-1.5b-instruct-function-calling-v1"]}')
        return FakeResponse('{"message":{"tool_calls":[{"function":{"name":"ask_for_clarification","arguments":"{\\"question\\":\\"ok\\"}"}}]}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        status = client.preload()

    assert status.ready is True
    assert any(url.endswith("/api/chat") for url in calls)


def test_propose_tool_call_returns_first_tool() -> None:
    with patch.dict(os.environ, {"LLM_EXPECT_HAILO": "false"}, clear=False):
        client = OllamaClient()

    with patch.object(client, "_preload_status", object()):
        with patch("app.integrations.llm_client.request.urlopen", return_value=FakeResponse('{"message":{"tool_calls":[{"function":{"name":"answer_with_llm","arguments":{"prompt":"hi"}}}]}}')):
            call, raw = client.propose_tool_call("Hallo")

    assert call.name == "answer_with_llm"
    assert raw["message"]["tool_calls"]


def test_chat_falls_back_to_host_docker_internal() -> None:
    with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:8000", "LLM_EXPECT_HAILO": "false", "LLM_CHAT_MODEL": "llama3.2:3b"}, clear=False):
        client = OllamaClient()

    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if "127.0.0.1" in req.full_url:
            raise error.URLError("connection refused")
        return FakeResponse('{"message": {"content": "Hallo!"}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        response = client.chat("Erzähl einen Witz")

    assert response == "Hallo!"
    assert calls[0] == "http://127.0.0.1:8000/api/chat"
    assert calls[1] == "http://host.docker.internal:8000/api/chat"


def test_chat_uses_chat_model_not_function_model() -> None:
    with patch.dict(
        os.environ,
        {"LLM_EXPECT_HAILO": "false", "LLM_MODEL": "qwen2-1.5b-instruct-function-calling-v1", "LLM_CHAT_MODEL": "llama3.2:3b"},
        clear=False,
    ):
        client = OllamaClient()

    captured_body = {}

    def fake_urlopen(req, timeout=0):
        captured_body["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse('{"message": {"content": "Hallo!"}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        response = client.chat("Hi")

    assert response == "Hallo!"
    assert captured_body["payload"]["model"] == "llama3.2:3b"


def test_preload_pulls_model_when_missing_in_hailo_list() -> None:
    with patch.dict(
        os.environ,
        {
            "LLM_BASE_URL": "http://127.0.0.1:8000",
            "LLM_EXPECT_HAILO": "true",
            "LLM_PULL_ON_PRELOAD_MISS": "true",
            "LLM_MODEL": "qwen2-1.5b-instruct-function-calling-v1",
        },
        clear=False,
    ):
        client = OllamaClient()

    calls = []
    state = {"listed": False}

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if req.full_url.endswith("/hailo/v1/list"):
            if state["listed"]:
                return FakeResponse('{"models":[{"name":"qwen2-1.5b-instruct-function-calling-v1:latest"}]}')
            return FakeResponse('{"models":[]}')
        if req.full_url.endswith("/api/pull"):
            state["listed"] = True
            return FakeResponse('{"status":"success"}')
        return FakeResponse('{"message":{"tool_calls":[{"function":{"name":"ask_for_clarification","arguments":"{\\"question\\":\\"ok\\"}"}}]}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        status = client.preload()

    assert status.ready is True
    assert "http://127.0.0.1:8000/api/pull" in calls


def test_preload_accepts_model_name_with_latest_suffix() -> None:
    with patch.dict(
        os.environ,
        {"LLM_BASE_URL": "http://127.0.0.1:8000", "LLM_EXPECT_HAILO": "true", "LLM_MODEL": "qwen2-1.5b-instruct-function-calling-v1"},
        clear=False,
    ):
        client = OllamaClient()

    def fake_urlopen(req, timeout=0):
        if req.full_url.endswith("/hailo/v1/list"):
            return FakeResponse('{"models":[{"name":"qwen2-1.5b-instruct-function-calling-v1:latest"}]}')
        return FakeResponse('{"message":{"tool_calls":[{"function":{"name":"ask_for_clarification","arguments":"{\\"question\\":\\"ok\\"}"}}]}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        status = client.preload()

    assert status.ready is True


def test_preload_handles_ndjson_pull_response() -> None:
    with patch.dict(
        os.environ,
        {
            "LLM_BASE_URL": "http://127.0.0.1:8000",
            "LLM_EXPECT_HAILO": "true",
            "LLM_PULL_ON_PRELOAD_MISS": "true",
            "LLM_MODEL": "qwen2-1.5b-instruct-function-calling-v1",
        },
        clear=False,
    ):
        client = OllamaClient()

    state = {"listed": False}

    def fake_urlopen(req, timeout=0):
        if req.full_url.endswith("/hailo/v1/list"):
            if state["listed"]:
                return FakeResponse('{"models":["qwen2-1.5b-instruct-function-calling-v1"]}')
            return FakeResponse('{"models":[]}')
        if req.full_url.endswith("/api/pull"):
            state["listed"] = True
            return FakeResponse('{"status":"pulling"}\n{"status":"success"}\n')
        return FakeResponse('{"message":{"tool_calls":[{"function":{"name":"ask_for_clarification","arguments":"{\\"question\\":\\"ok\\"}"}}]}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        status = client.preload()

    assert status.ready is True


def test_preload_non_strict_mode_allows_missing_hailo_list_entry_after_pull() -> None:
    with patch.dict(
        os.environ,
        {
            "LLM_BASE_URL": "http://127.0.0.1:8000",
            "LLM_EXPECT_HAILO": "true",
            "LLM_PULL_ON_PRELOAD_MISS": "true",
            "LLM_STRICT_HAILO_LIST": "false",
            "LLM_MODEL": "qwen2-1.5b-instruct-function-calling-v1",
        },
        clear=False,
    ):
        client = OllamaClient()

    def fake_urlopen(req, timeout=0):
        if req.full_url.endswith("/hailo/v1/list"):
            return FakeResponse('{"models":[]}')
        if req.full_url.endswith("/api/pull"):
            return FakeResponse('{"status":"success"}')
        return FakeResponse('{"message":{"tool_calls":[{"function":{"name":"ask_for_clarification","arguments":"{\\"question\\":\\"ok\\"}"}}]}}')

    with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
        status = client.preload()

    assert status.ready is True
    assert status.hailo_runtime == "unknown"
