from __future__ import annotations

import json
from typing import Any

from .llm import AnthropicMessagesClient, extract_text
from .prompts import ACTIVITY_ANALYSIS_SKILL_PROMPT, SYSTEM_PROMPT
from .tools import call_tool, tool_catalog


def build_chat_bootstrap() -> dict[str, Any]:
    return {
        "system_prompt": SYSTEM_PROMPT,
        "tool_catalog": tool_catalog(),
    }


def build_plain_chat_user_message(question: str) -> str:
    return "\n".join(
        [
            "请直接回答用户问题。",
            "如果用户没有要求分析运动数据，不要主动引用或分析本地活动。",
            "",
            f"用户问题：{question}",
        ]
    )


def chat_plain(question: str) -> dict[str, Any]:
    client = AnthropicMessagesClient()
    response = client.create_message(
        system=SYSTEM_PROMPT,
        user=build_plain_chat_user_message(question),
    )
    return {
        "mode": "plain",
        "question": question,
        "answer": extract_text(response),
        "raw_response": response,
    }


def build_activity_chat_context(
    question: str,
    *,
    activity_id: int | str = "latest",
    history_days: int = 30,
) -> dict[str, Any]:
    activity = _compact_activity_for_prompt(call_tool("get_activity", {"activity_id": activity_id}))
    resolved_activity_id = activity.get("id") or activity_id
    summary = call_tool("get_activity_summary", {"activity_id": resolved_activity_id})
    data_quality = call_tool("check_activity_data_quality", {"activity_id": resolved_activity_id})
    intensity_distribution = call_tool("analyze_intensity_distribution", {"activity_id": resolved_activity_id})
    workout_segments = call_tool(
        "detect_workout_segments",
        {"activity_id": resolved_activity_id, "bucket_seconds": 60},
    )
    fatigue_and_stability = call_tool("analyze_fatigue_and_stability", {"activity_id": resolved_activity_id})
    recommendation_context = call_tool(
        "generate_training_recommendation",
        {"activity_id": resolved_activity_id, "goal": _infer_goal_hint(question)},
    )
    history = call_tool("get_recent_training_history", {"days": history_days})
    return {
        "question": question,
        "activity": activity,
        "skill_prompt": ACTIVITY_ANALYSIS_SKILL_PROMPT,
        "standard_analysis": {
            "summary": summary,
            "data_quality": data_quality,
            "intensity_distribution": intensity_distribution,
            "workout_segments": workout_segments,
            "fatigue_and_stability": fatigue_and_stability,
            "recommendation_context": recommendation_context,
        },
        "recent_training_history": history,
    }


def build_activity_chat_user_message(context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "请基于下面的本地运动数据回答用户问题。",
            "要求：遵守 skill_prompt 的标准运动分析流程。后端提供的是指标和上下文，最终判断与训练建议由你生成。",
            "",
            f"用户问题：{context['question']}",
            "",
            "运动分析 Skill Prompt：",
            context["skill_prompt"],
            "",
            "结构化数据：",
            "```json",
            json.dumps(
                {
                    "activity": context["activity"],
                    "standard_analysis": context["standard_analysis"],
                    "recent_training_history": context["recent_training_history"],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "```",
        ]
    )


def build_activity_chat_user_content(context: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "type": "text",
            "text": "\n".join(
                [
                    "请基于本地运动数据回答用户问题。",
                    "要求：遵守后续 skill prompt 的标准运动分析流程。后端提供的是指标和上下文，最终判断与训练建议由你生成。",
                    "",
                    f"用户问题：{context['question']}",
                ]
            ),
        },
        {
            "type": "text",
            "text": "运动分析 Skill Prompt：\n" + context["skill_prompt"],
        },
        {
            "type": "text",
            "text": "结构化数据：\n"
            + json.dumps(
                {
                    "activity": context["activity"],
                    "standard_analysis": context["standard_analysis"],
                    "recent_training_history": context["recent_training_history"],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        },
    ]


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
        user=build_activity_chat_user_content(context),
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


def chat(
    question: str,
    *,
    mode: str = "auto",
    activity_id: int | str = "latest",
    history_days: int = 30,
    save_report: bool = False,
) -> dict[str, Any]:
    resolved_mode = resolve_chat_mode(question, mode)
    if resolved_mode == "plain":
        return chat_plain(question)
    return chat_about_activity(
        question,
        activity_id=activity_id,
        history_days=history_days,
        save_report=save_report,
    )


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
        user=build_activity_chat_user_content(context),
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


def preview_plain_chat_payload(question: str) -> dict[str, Any]:
    config = _preview_agent_config()
    client = AnthropicMessagesClient(config=config)
    payload = client.build_message_payload(
        system=SYSTEM_PROMPT,
        user=build_plain_chat_user_message(question),
    )
    return {
        "mode": "plain",
        "endpoint": client._messages_url(),
        "headers": {
            "content-type": "application/json",
            "x-api-key": "***",
            "anthropic-version": str(client.config["anthropic_version"]),
        },
        "payload": payload,
    }


def preview_chat_payload(
    question: str,
    *,
    mode: str = "auto",
    activity_id: int | str = "latest",
    history_days: int = 30,
) -> dict[str, Any]:
    resolved_mode = resolve_chat_mode(question, mode)
    if resolved_mode == "plain":
        return preview_plain_chat_payload(question)
    payload = preview_activity_chat_payload(
        question,
        activity_id=activity_id,
        history_days=history_days,
    )
    payload["mode"] = "activity"
    return payload


def resolve_chat_mode(question: str, mode: str) -> str:
    if mode not in {"auto", "plain", "activity"}:
        raise ValueError("mode 只支持 auto、plain、activity")
    if mode != "auto":
        return mode
    return "activity" if _looks_like_activity_question(question) else "plain"


def _looks_like_activity_question(question: str) -> bool:
    text = question.lower().strip()
    activity_keywords = [
        "fit",
        "骑行",
        "跑步",
        "运动",
        "训练",
        "活动",
        "功率",
        "心率",
        "踏频",
        "配速",
        "tss",
        "if",
        "ftp",
        "分析",
        "建议",
        "恢复",
        "间歇",
        "强度",
        "最后一条",
        "最近一次",
    ]
    greeting_only = text in {"你好", "hello", "hi", "嗨", "您好"}
    return not greeting_only and any(keyword in text for keyword in activity_keywords)


def _infer_goal_hint(question: str) -> str:
    text = question.lower()
    if any(word in text for word in ["ftp", "阈值", "甜区"]):
        return "ftp_improvement"
    if any(word in text for word in ["vo2", "vo2max", "最大摄氧", "间歇"]):
        return "vo2max"
    if any(word in text for word in ["恢复", "休息"]):
        return "recovery"
    if any(word in text for word in ["减脂", "燃脂", "瘦"]):
        return "fat_loss"
    if any(word in text for word in ["有氧", "耐力", "基础"]):
        return "base_endurance"
    return "general_review"


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
        self.messages: list[dict[str, Any]] = []
        self.turn_count = 0

    def ask(self, question: str) -> dict[str, Any]:
        self.turn_count += 1
        if self.context is None:
            self.context = build_activity_chat_context(
                question,
                activity_id=self.activity_id,
                history_days=self.history_days,
            )
            user_message = build_activity_chat_user_content(self.context)
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
