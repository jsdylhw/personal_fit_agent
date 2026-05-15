"""LLM API 客户端:Anthropic Messages API 兼容接口.

当前通过 DeepSeek 的 /anthropic 端点使用,兼容 Anthropic Messages API 格式.
重试仅针对 timeout/URLError,HTTP 错误直接抛出(不做无意义重试).
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import get_agent_config


class AnthropicMessagesClient:
    """Anthropic Messages API 兼容的 LLM 客户端.

    支持单条消息(create_message)和多轮对话(create_messages)两种模式.
    配置从 config.yaml 的 agent: 块读取.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = get_agent_config() if config is None else get_agent_config({"agent": config})
        self.base_url = str(self.config.get("base_url") or "").rstrip("/")
        self.api_key = str(self.config.get("api_key") or "")
        self.model = str(self.config.get("model") or "")
        if not self.base_url:
            raise RuntimeError("Please set agent.base_url in config.yaml")
        if not self.api_key:
            raise RuntimeError("Please set agent.api_key in config.yaml")
        if not self.model:
            raise RuntimeError("Please set agent.model in config.yaml")

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        return f"{self.base_url}/v1/messages"

    def create_message(
        self, *, system: str | None = None, user: str | list[dict[str, Any]],
        max_tokens: int | None = None, temperature: float | None = None,
    ) -> dict[str, Any]:
        """单条 user 消息调用(guided/direct 模式使用)."""
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.config["max_tokens"],
            "temperature": self.config["temperature"] if temperature is None else temperature,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            payload["system"] = system
        return self._post_messages(payload)

    def create_messages(
        self, *, system: str | None = None, messages: list[dict[str, Any]],
        max_tokens: int | None = None, temperature: float | None = None,
    ) -> dict[str, Any]:
        """多轮 messages 调用(tool loop 模式使用)."""
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.config["max_tokens"],
            "temperature": self.config["temperature"] if temperature is None else temperature,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        return self._post_messages(payload)

    def _post_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 POST 请求到 Messages API.

        HTTP 错误(4xx/5xx)直接抛出——说明 API key/参数有问题,重试无意义.
        仅对 timeout 和 URLError 做指数退避重试.
        """
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
        timeout = float(self.config.get("timeout_seconds") or 300)
        max_retries = max(1, int(self.config.get("max_retries") or 1))
        last_error: BaseException | None = None

        for attempt in range(1, max_retries + 1):
            try:
                with urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"LLM request failed: HTTP {exc.code}; body={body[:1000]}") from exc
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
            except URLError as exc:
                last_error = exc

            if attempt < max_retries:
                time.sleep(min(2 * attempt, 10))

        raise RuntimeError(
            f"LLM request timed out or failed after {max_retries} attempt(s); "
            f"timeout_seconds={timeout}; error={last_error}"
        ) from last_error


def extract_text(message: dict[str, Any]) -> str:
    """从 API 响应中提取 text content,跳过 tool_use 等非文本 block.

    Args:
        message: Anthropic Messages API 的响应 dict.

    Returns:
        str: 拼接所有 text block 的内容.
    """
    parts = message.get("content") or []
    texts = [
        str(part.get("text"))
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text") is not None
    ]
    return "\n".join(texts).strip()
