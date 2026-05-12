from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import get_agent_config


class AnthropicMessagesClient:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = get_agent_config() if config is None else get_agent_config({"agent": config})
        self.base_url = str(self.config.get("base_url") or "").rstrip("/")
        self.api_key = str(self.config.get("api_key") or "")
        self.model = str(self.config.get("model") or "")
        if not self.base_url:
            raise RuntimeError("请在 config.yaml 配置 agent.base_url")
        if not self.api_key:
            raise RuntimeError("请在 config.yaml 配置 agent.api_key")
        if not self.model:
            raise RuntimeError("请在 config.yaml 配置 agent.model")

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        return f"{self.base_url}/v1/messages"

    def create_message(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.config["max_tokens"],
            "temperature": self.config["temperature"] if temperature is None else temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        return self._post_messages(payload)

    def build_message_payload(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": max_tokens or self.config["max_tokens"],
            "temperature": self.config["temperature"] if temperature is None else temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

    def create_messages(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.config["max_tokens"],
            "temperature": self.config["temperature"] if temperature is None else temperature,
            "system": system,
            "messages": messages,
        }
        return self._post_messages(payload)

    def build_messages_payload(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": max_tokens or self.config["max_tokens"],
            "temperature": self.config["temperature"] if temperature is None else temperature,
            "system": system,
            "messages": messages,
        }

    def _post_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self._messages_url(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": str(self.config["anthropic_version"]),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM 请求失败: HTTP {exc.code}; body={body[:1000]}") from exc
        except URLError as exc:
            raise RuntimeError(f"LLM 请求失败: {exc.reason}") from exc


def extract_text(message: dict[str, Any]) -> str:
    parts = message.get("content") or []
    texts = [
        str(part.get("text"))
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text") is not None
    ]
    return "\n".join(texts).strip()
