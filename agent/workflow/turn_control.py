"""Conversation-turn control for confirmations and retries."""

from __future__ import annotations

from typing import Any

from agent.context import AgentContext
from agent.workflow.tool_runtime import execute_saved_action

CONFIRM_WORDS = {"确认", "yes", "y", "是", "继续", "ok", "confirm", "确定", "好", "可以"}
RETRY_WORDS = {"再试一次", "重试", "再试", "retry", "try again", "再来一次", "重新试一下"}


def handle_control_turn(message: str, context: AgentContext, *, verbose: bool = False) -> dict[str, Any] | None:
    """Handle short control replies before routing the message through the LLM."""
    if context.pending_action and is_confirm(message):
        pending = context.pending_action
        context.pending_action = None
        return execute_saved_action(pending, context, verbose=verbose, intent="confirmed", label="确认执行")

    if is_confirm(message):
        answer = "当前没有待确认的操作。请先告诉我要上传、同步，还是分析哪条活动。"
        context.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return {
            "answer": answer,
            "status": "no_pending_confirmation",
            "context": context,
            "intent": "confirmation",
            "steps": [],
        }

    if is_retry(message):
        if context.last_failed_action:
            return execute_saved_action(context.last_failed_action, context, verbose=verbose, intent="retry", label="重试执行")
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


def is_confirm(message: str) -> bool:
    return message.lower().strip() in CONFIRM_WORDS


def is_retry(message: str) -> bool:
    return message.lower().strip() in RETRY_WORDS
