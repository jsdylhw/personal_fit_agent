"""Planner 输入构建辅助函数.

planner 层只描述应该选择哪些粗粒度工作流步骤,不执行工具,
也不暴露底层工具名.
"""

from __future__ import annotations

import json
from typing import Any

from agent.context import AgentContext
from agent.llm import AnthropicMessagesClient, extract_text
from agent.workflow.plan_schema import (
    PLAN_JSON_SCHEMA,
    WorkflowPlan,
    available_workflow_steps_catalog,
    workflow_plan_from_dict,
)
from core.file_workflow import _extract_json_object


PLANNER_SYSTEM_PROMPT = """你是 Personal FIT Agent 的工作流规划器.

你只能从 available_steps 中选择粗粒度工作流步骤.不要调用工具,不要假装
任何步骤已经执行.不要输出分析过程,只返回一个符合 plan_json_schema 的 JSON 对象.
如果用户明确说"所有历史活动"或"全部历史活动",这已经是明确范围,应按 all_history
规划,不要再追问时间范围.
如果用户说"重新分析","刷新报告","重新大模型分析",应先定位活动,再选择
ensure_activity_summaries 并设置 arguments.force=true,同时 plan.allow_side_effects=true.
如果用户只是要查看/总结多条活动,使用 summarize_activity_range;只有明确出现
"比较","对比","差异","哪次更好"等意图时才使用 compare_activities.
如果用户请求路线建议,可以直接选择 generate_route_advice;如果请求明显涉及
训练状态、恢复、强度安排,再先定位相关活动范围并选择 summarize_recent_training_load.
不要让 generate_route_advice 直接读取原始 FIT.
"""


def build_planner_payload(user_message: str, context: AgentContext) -> dict[str, Any]:
    """构建后续 LLM planner 使用的结构化输入."""
    return {
        "instruction": (
            "请为当前请求选择需要的粗粒度工作流步骤."
            "只能选择 available_steps 中存在的 name,不要执行任何步骤."
            "用户说所有历史活动/全部历史活动时表示 all_history,不要追问时间范围."
            "用户说重新分析/刷新报告/重新大模型分析时,要在解析活动后加入"
            "ensure_activity_summaries,arguments.force=true,并设置 allow_side_effects=true."
            "查看或总结多条活动时使用 summarize_activity_range;只有明确比较/对比/差异时"
            "才使用 compare_activities."
            "路线建议可以直接选择 generate_route_advice;只有涉及训练状态/恢复/强度安排时,"
            "才先选择 summarize_recent_training_load 生成结构化训练负荷."
        ),
        "user_message": user_message,
        "context": _planner_context(context),
        "available_steps": available_workflow_steps_catalog(),
        "plan_json_schema": PLAN_JSON_SCHEMA,
    }


def plan_initial_workflow(
    user_message: str,
    context: AgentContext,
    *,
    client: AnthropicMessagesClient | None = None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """调用 LLM 生成初始 WorkflowPlan,不执行任何步骤."""
    payload = build_planner_payload(user_message, context)
    llm_client = client or AnthropicMessagesClient()
    response = llm_client.create_message(
        system=PLANNER_SYSTEM_PROMPT,
        user=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        max_tokens=max_tokens,
        temperature=0,
    )
    raw_text = extract_text(response)
    if not raw_text:
        content_types = [
            str(part.get("type"))
            for part in response.get("content") or []
            if isinstance(part, dict)
        ]
        raise RuntimeError(
            "LLM planner returned no text content; "
            f"stop_reason={response.get('stop_reason')}; "
            f"content_types={content_types}; "
            "try increasing max_tokens or simplifying the planner payload."
        )
    plan = parse_workflow_plan_text(raw_text)
    return {
        "plan": plan,
        "plan_json": plan.to_dict(),
        "raw_text": raw_text,
        "response": response,
        "payload": payload,
    }


def parse_workflow_plan_text(text: str) -> WorkflowPlan:
    """从 LLM 文本响应中提取并解析 WorkflowPlan."""
    data = _extract_json_object(text)
    return workflow_plan_from_dict(data)


def _planner_context(context: AgentContext) -> dict[str, Any]:
    return {
        "session_id": context.session_id,
        "current_fit_file": str(context.current_fit_file) if context.current_fit_file else None,
        "current_activity_key": context.current_activity_key,
        "current_summary_path": str(context.current_summary_path) if context.current_summary_path else None,
        "history_enabled": context.history_enabled,
        "pending_action": context.pending_action,
        "has_last_tool_result": context.last_tool_result is not None,
    }
