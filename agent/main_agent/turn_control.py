"""Conversation-turn control for retries."""

from __future__ import annotations

from typing import Any

from agent.context import AgentContext
from agent.main_agent.tools import execute_saved_action

RETRY_WORDS = {"再试一次", "重试", "再试", "retry", "try again", "再来一次", "重新试一下"}


def handle_control_turn(message: str, context: AgentContext, *, verbose: bool = False) -> dict[str, Any] | None:
    """Handle short control replies before routing the message through the LLM."""
    if is_retry(message):
        if context.last_failed_action:
            return execute_saved_action(context.last_failed_action, context, verbose=verbose, intent="retry", label="重试执行")
        if context.last_llm_error:
            # 不复放可能有副作用的工具，只重新进入 LLM 规划循环；已完成的
            # 工具状态仍由 context 和状态 preamble 提供。
            context.last_llm_error = None
            return None
        answer = "当前没有可重试的失败操作。请重新说明你想执行的操作。"
        context.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return {
            "answer": answer,
            "status": "no_retryable_action",
            "context": context,
            "intent": "retry",
            "steps": [],
        }

    return None


def is_retry(message: str) -> bool:
    return message.lower().strip() in RETRY_WORDS
