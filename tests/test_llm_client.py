from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.llm import AnthropicMessagesClient, extract_text


class TestExtractText:
    def test_extracts_text_parts(self):
        message = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ]
        }
        result = extract_text(message)
        assert result == "Hello\nWorld"

    def test_skips_non_text_parts(self):
        message = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "tool_use", "name": "get_history"},
                {"type": "text", "text": "World"},
            ]
        }
        result = extract_text(message)
        assert result == "Hello\nWorld"

    def test_empty_content_returns_empty_string(self):
        assert extract_text({"content": []}) == ""
        assert extract_text({}) == ""

    def test_handles_none_text_value(self):
        message = {
            "content": [
                {"type": "text", "text": None},
                {"type": "text", "text": "valid"},
            ]
        }
        result = extract_text(message)
        assert "valid" in result


class TestAnthropicMessagesClientInit:
    """The constructor wraps config in {"agent": config} before calling get_agent_config,
    so we pass flat config dicts to match how callers actually use it."""

    def test_raises_without_base_url(self):
        with pytest.raises(RuntimeError, match="base_url"):
            AnthropicMessagesClient({"api_key": "sk", "model": "m", "base_url": ""})

    def test_raises_without_api_key(self):
        with pytest.raises(RuntimeError, match="api_key"):
            AnthropicMessagesClient({"base_url": "https://api.test.com", "model": "m", "api_key": ""})

    def test_raises_without_model(self):
        with pytest.raises(RuntimeError, match="model"):
            AnthropicMessagesClient({"base_url": "https://api.test.com", "api_key": "sk", "model": ""})

    def test_normalizes_base_url(self):
        client = AnthropicMessagesClient({"base_url": "https://api.test.com/anthropic/", "api_key": "sk", "model": "m"})
        assert client.base_url == "https://api.test.com/anthropic"

    def test_already_ends_with_v1_messages(self):
        client = AnthropicMessagesClient(
            {"base_url": "https://api.test.com/anthropic/v1/messages", "api_key": "sk", "model": "m"}
        )
        assert client._messages_url() == "https://api.test.com/anthropic/v1/messages"


class TestAnthropicMessagesClient:
    @pytest.fixture
    def client(self):
        return AnthropicMessagesClient(
            {"base_url": "https://api.test.com/anthropic", "api_key": "sk-test", "model": "test-model"}
        )

    def test_build_messages_payload(self, client):
        payload = client.build_messages_payload(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=500,
            temperature=0.7,
        )
        assert payload["model"] == "test-model"
        assert payload["max_tokens"] == 500
        assert payload["temperature"] == 0.7
        assert payload["system"] == "You are helpful."
        assert len(payload["messages"]) == 1

    def test_build_message_payload_single_message(self, client):
        payload = client.build_message_payload(
            system="System prompt",
            user="Hello single user",
        )
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "Hello single user"

    @patch("agent.llm.urlopen")
    def test_create_messages_http(self, mock_urlopen, client):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "id": "msg_123",
            "content": [{"type": "text", "text": "Hello back"}],
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = client.create_messages(
            system="System prompt",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result["id"] == "msg_123"

    @patch("agent.llm.urlopen")
    def test_create_message_single(self, mock_urlopen, client):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "id": "msg_single",
            "content": [{"type": "text", "text": "Response"}],
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = client.create_message(
            system="System prompt",
            user="Hello",
        )
        assert result["id"] == "msg_single"
