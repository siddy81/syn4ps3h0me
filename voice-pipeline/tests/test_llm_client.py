import os
import unittest
from urllib import error
from unittest.mock import patch

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


class LlmClientTests(unittest.TestCase):
    def test_candidate_url_adds_host_docker_internal_for_localhost(self) -> None:
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:8000"}, clear=False):
            client = OllamaClient()
            candidates = client._candidate_base_urls()
        self.assertEqual(candidates[0], "http://127.0.0.1:8000")
        self.assertIn("http://host.docker.internal:8000", candidates)

    def test_chat_falls_back_to_host_docker_internal(self) -> None:
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:8000", "LLM_MODEL": "llama3.2:3b"}, clear=False):
            client = OllamaClient()

        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            if "127.0.0.1" in req.full_url:
                raise error.URLError("connection refused")
            return FakeResponse('{"message": {"content": "Hallo!"}}')

        with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
            response = client.chat("Erzähl einen Witz")

        self.assertEqual(response, "Hallo!")
        self.assertEqual(calls[0], "http://127.0.0.1:8000/api/chat")
        self.assertEqual(calls[1], "http://host.docker.internal:8000/api/chat")

    def test_chat_falls_back_to_v1_completion_on_api_500(self) -> None:
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:8000", "LLM_MODEL": "llama3.2:3b"}, clear=False):
            client = OllamaClient()

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/api/chat"):
                raise error.URLError("HTTP Error 500: Internal Server Error")
            if req.full_url.endswith("/v1/chat/completions"):
                return FakeResponse('{"choices":[{"message":{"content":"Hallo aus v1"}}]}')
            raise AssertionError(f"unexpected url {req.full_url}")

        with patch("app.integrations.llm_client.request.urlopen", side_effect=fake_urlopen):
            response = client.chat("Sag hallo")

        self.assertEqual(response, "Hallo aus v1")


if __name__ == "__main__":
    unittest.main()
