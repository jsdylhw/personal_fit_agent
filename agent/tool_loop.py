from __future__ import annotations

import json
import re
from typing import Any

from .chat_logger import append_chat_log, new_session_id
from .llm import AnthropicMessagesClient, extract_text
from .prompts import TOOL_LOOP_SYSTEM_PROMPT
from .tools import call_tool, tool_catalog


class ToolLoopSession:
    def __init__(
        self,
        *,
        max_steps: int = 8,
        client: AnthropicMessagesClient | None = None,
        session_id: str | None = None,
    ):
        self.max_steps = max_steps
        self.client = client or AnthropicMessagesClient()
        self.session_id = session_id or new_session_id("chat_tools")
        self.messages: list[dict[str, str]] = []
        self.logs: list[dict[str, Any]] = []

    def ask(self, question: str) -> dict[str, Any]:
        self.messages.append(
            {
                "role": "user",
                "content": _initial_user_message(question),
            }
        )
        for step in range(1, self.max_steps + 1):
            response = self.client.create_messages(
                system=TOOL_LOOP_SYSTEM_PROMPT,
                messages=self.messages,
            )
            response_text = extract_text(response)
            action = parse_tool_loop_action(response_text)
            self.logs.append(
                {
                    "step": step,
                    "type": "llm_response",
                    "raw_text": response_text,
                    "parsed": action,
                    "response": response,
                    "response_id": response.get("id"),
                    "model": response.get("model"),
                }
            )
            self.messages.append({"role": "assistant", "content": response_text})

            if action.get("action") == "final":
                answer = str(action.get("answer", ""))
                log_path = self._write_session_log(question, answer=answer)
                return {
                    "answer": answer,
                    "session_id": self.session_id,
                    "log_path": str(log_path),
                    "logs": self.logs,
                    "messages": self.messages,
                }

            if action.get("action") != "tool":
                tool_result = {
                    "error": "invalid_action",
                    "message": "Model must return a JSON object with action=tool or action=final.",
                    "parsed": action,
                }
            else:
                tool_name = str(action.get("tool") or "")
                arguments = action.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}
                try:
                    result = call_tool(tool_name, arguments)
                    tool_result = {
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result,
                    }
                except Exception as exc:
                    tool_result = {
                        "tool": tool_name,
                        "arguments": arguments,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }

            self.logs.append(
                {
                    "step": step,
                    "type": "tool_result",
                    **tool_result,
                }
            )
            self.messages.append(
                {
                    "role": "user",
                    "content": "Tool result:\n"
                    + json.dumps(tool_result, ensure_ascii=False, indent=2, default=str)
                    + "\nContinue. Return tool JSON if more data is needed, otherwise return final JSON.",
                }
            )

        error = f"exceeded max tool loop steps: {self.max_steps}"
        log_path = self._write_session_log(question, error=error)
        return {
            "answer": "",
            "session_id": self.session_id,
            "log_path": str(log_path),
            "error": error,
            "logs": self.logs,
            "messages": self.messages,
        }

    def _write_session_log(
        self,
        question: str,
        *,
        answer: str | None = None,
        error: str | None = None,
    ):
        return append_chat_log(
            self.session_id,
            {
                "event": "chat_tools_session",
                "question": question,
                "max_steps": self.max_steps,
                "system": TOOL_LOOP_SYSTEM_PROMPT,
                "logs": self.logs,
                "messages": self.messages,
                "answer": answer,
                "error": error,
            },
        )


def run_tool_loop(question: str, *, max_steps: int = 8) -> dict[str, Any]:
    return ToolLoopSession(max_steps=max_steps).ask(question)


def parse_tool_loop_action(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return {"action": "invalid", "raw_text": text}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"action": "invalid", "raw_text": text}
    return parsed if isinstance(parsed, dict) else {"action": "invalid", "raw_text": text}


def _initial_user_message(question: str) -> str:
    return "\n".join(
        [
            "User question:",
            question,
            "",
            "Available tool catalog:",
            json.dumps(tool_catalog(), ensure_ascii=False, indent=2, default=str),
            "",
            "Choose tools based on the question. Return exactly one JSON object each turn.",
        ]
    )
