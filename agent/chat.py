from __future__ import annotations

import json
from typing import Any

from .llm import AnthropicMessagesClient, extract_text
from .prompts import SYSTEM_PROMPT
from .tools import call_tool, tool_catalog


def build_chat_bootstrap() -> dict[str, Any]:
    return {
        "system_prompt": SYSTEM_PROMPT,
        "tool_catalog": tool_catalog(),
    }


def build_activity_chat_context(
    question: str,
    *,
    activity_id: int | str = "latest",
    history_days: int = 30,
) -> dict[str, Any]:
    activity = _compact_activity_for_prompt(call_tool("get_activity", {"activity_id": activity_id}))
    raw_analysis = call_tool("get_activity_raw_analysis", {"activity_id": activity_id})
    history = call_tool("get_recent_training_history", {"days": history_days})
    return {
        "question": question,
        "activity": activity,
        "raw_analysis": raw_analysis,
        "recent_training_history": history,
    }


def build_activity_chat_user_message(context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "请基于下面的本地运动数据回答用户问题。",
            "要求：先做客观摘要，再给训练观察和建议；如果数据质量不足，要明确说明。",
            "",
            f"用户问题：{context['question']}",
            "",
            "结构化数据：",
            "```json",
            json.dumps(
                {
                    "activity": context["activity"],
                    "raw_analysis": context["raw_analysis"],
                    "recent_training_history": context["recent_training_history"],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "```",
        ]
    )


def chat_about_activity(
    question: str,
    *,
    activity_id: int | str = "latest",
    history_days: int = 30,
    save_report: bool = False,
) -> dict[str, Any]:
    context = build_activity_chat_context(
        question,
        activity_id=activity_id,
        history_days=history_days,
    )
    client = AnthropicMessagesClient()
    response = client.create_message(
        system=SYSTEM_PROMPT,
        user=build_activity_chat_user_message(context),
    )
    answer = extract_text(response)
    result = {
        "activity_id": activity_id,
        "resolved_activity_id": context["activity"].get("id"),
        "history_days": history_days,
        "question": question,
        "answer": answer,
        "raw_response": response,
    }
    if save_report and context["activity"].get("id") is not None:
        result["report"] = call_tool(
            "save_activity_report",
            {
                "activity_id": int(context["activity"]["id"]),
                "markdown": answer,
                "report_type": "llm_chat",
                "summary": {
                    "question": question,
                    "history_days": history_days,
                    "model_response_id": response.get("id"),
                },
                "model": response.get("model"),
                "prompt_version": "activity_chat.v1",
            },
        )
    return result


def preview_activity_chat_payload(
    question: str,
    *,
    activity_id: int | str = "latest",
    history_days: int = 30,
) -> dict[str, Any]:
    context = build_activity_chat_context(
        question,
        activity_id=activity_id,
        history_days=history_days,
    )
    config = _preview_agent_config()
    client = AnthropicMessagesClient(config=config)
    payload = client.build_message_payload(
        system=SYSTEM_PROMPT,
        user=build_activity_chat_user_message(context),
    )
    return {
        "endpoint": client._messages_url(),
        "headers": {
            "content-type": "application/json",
            "x-api-key": "***",
            "anthropic-version": str(client.config["anthropic_version"]),
        },
        "payload": payload,
    }


class ActivityChatSession:
    def __init__(
        self,
        *,
        activity_id: int | str = "latest",
        history_days: int = 30,
        save_report: bool = False,
        client: AnthropicMessagesClient | None = None,
    ):
        self.activity_id = activity_id
        self.history_days = history_days
        self.save_report = save_report
        self.client = client or AnthropicMessagesClient()
        self.context: dict[str, Any] | None = None
        self.messages: list[dict[str, str]] = []
        self.turn_count = 0

    def ask(self, question: str) -> dict[str, Any]:
        self.turn_count += 1
        if self.context is None:
            self.context = build_activity_chat_context(
                question,
                activity_id=self.activity_id,
                history_days=self.history_days,
            )
            user_message = build_activity_chat_user_message(self.context)
        else:
            user_message = "\n".join(
                [
                    "继续基于同一份本地运动数据和上文对话回答。",
                    f"用户问题：{question}",
                ]
            )

        self.messages.append({"role": "user", "content": user_message})
        response = self.client.create_messages(
            system=SYSTEM_PROMPT,
            messages=self.messages,
        )
        answer = extract_text(response)
        self.messages.append({"role": "assistant", "content": answer})

        result = {
            "turn": self.turn_count,
            "activity_id": self.activity_id,
            "resolved_activity_id": (self.context or {}).get("activity", {}).get("id"),
            "history_days": self.history_days,
            "question": question,
            "answer": answer,
            "raw_response": response,
        }
        if self.save_report and result["resolved_activity_id"] is not None:
            result["report"] = call_tool(
                "save_activity_report",
                {
                    "activity_id": int(result["resolved_activity_id"]),
                    "markdown": answer,
                    "report_type": "llm_chat_turn",
                    "summary": {
                        "turn": self.turn_count,
                        "question": question,
                        "history_days": self.history_days,
                        "model_response_id": response.get("id"),
                    },
                    "model": response.get("model"),
                    "prompt_version": "activity_chat_session.v1",
                },
            )
        return result


def _compact_activity_for_prompt(activity: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "source",
        "source_activity_id",
        "file_name",
        "sport_type",
        "start_time",
        "duration_s",
        "distance_m",
        "fit_path",
    ]
    return {key: activity.get(key) for key in keys}


def _preview_agent_config() -> dict[str, Any]:
    return {
        "base_url": "https://example.invalid",
        "api_key": "preview-key",
        "model": "preview-model",
        "max_tokens": 1200,
        "temperature": 0.3,
        "anthropic_version": "2023-06-01",
    }
