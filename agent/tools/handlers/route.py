"""Agent adapter for route-advice generation."""

from __future__ import annotations

from typing import Any

from agent.main_agent.context import AgentContext
from integrations.llm import AnthropicMessagesClient, extract_text
from services.route.advice import generate_route_advice


def generate_route_advice_tool(
    context: AgentContext,
    *,
    args: dict[str, Any] | None = None,
    name: str = "generate_route_advice",
) -> dict[str, Any]:
    """Extract conversational inputs before calling the context-free service."""
    return generate_route_advice(
        args=args,
        training_load=_training_load(context),
        user_message=_latest_user_message(context),
        advisor=_request_route_advice,
        name=name,
    )


def _request_route_advice(system: str, user: str) -> str:
    """Own the LLM call at the Agent boundary and return only its text."""
    response = AnthropicMessagesClient().create_message(
        system=system,
        user=user,
        max_tokens=1200,
        temperature=0.4,
    )
    return extract_text(response)


def _training_load(context: AgentContext) -> dict[str, Any] | None:
    last = context.last_tool_result
    result = last.get("result") if isinstance(last, dict) else None
    if isinstance(result, dict) and result.get("schema_version") == "training_load_summary.v1":
        return result
    return None


def _latest_user_message(context: AgentContext) -> str:
    for message in reversed(context.messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""
