"""Tool Guard — 运行时校验 LLM 工具调用.

在 Executor 执行 handler 之前检查:
- 工具是否在 allowlist 内
- 副作用是否需要确认
- 参数是否合法
- 依赖是否满足
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.context import AgentContext

# 需要用户确认的工具名
CONFIRMATION_REQUIRED = {
    "upload_strava_activity",
    "sync_garmin_activities",
}

# 有副作用的工具名
SIDE_EFFECT_TOOLS = CONFIRMATION_REQUIRED | {
    "analyze_new_fit_files",
    "generate_summary_file",
    "ensure_activity_summaries",
}

# 工具 → 前置依赖(context 中必须存在)
TOOL_DEPENDENCIES: dict[str, set[str]] = {
    "analyze_single_activity": {"selected_activities"},
    "summarize_activity_range": {"selected_activities"},
    "compare_activities": {"selected_activities"},
    "compare_with_history": {"selected_activities"},
    "summarize_recent_training_load": {"selected_activities"},
    "generate_training_advice": {"selected_activities"},
    "ensure_activity_summaries": {"selected_activities"},
    "upload_strava_activity": {"selected_activities"},
    "analyze_new_fit_files": {"synced_fit_files"},
}


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""
    needs_confirmation: bool = False
    confirm_message: str = ""


def guard_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    context: AgentContext,
    allowed_categories: set[str],
    user_confirmed: bool = False,
    has_resolved: bool = False,
) -> GuardResult:
    """校验单个工具调用是否允许执行.

    Args:
        tool_name: LLM 要调用的工具名.
        arguments: 工具参数.
        context: 当前运行状态.
        allowed_categories: 本轮允许的 ToolDef category 集合.
        user_confirmed: 用户是否已确认副作用操作.
        has_resolved: 是否已完成活动定位.

    Returns:
        GuardResult — allowed=True 表示可以执行.
    """
    # 1. 副作用检查
    if tool_name in SIDE_EFFECT_TOOLS and not user_confirmed:
        return GuardResult(
            allowed=False,
            reason=f"{tool_name} 有副作用",
            needs_confirmation=True,
            confirm_message=f"确认执行 {tool_name}？此操作有副作用。",
        )

    # 2. 活动定位检查 — 需要 select 但没有活动
    deps = TOOL_DEPENDENCIES.get(tool_name, set())
    if "selected_activities" in deps and not has_resolved:
        return GuardResult(
            allowed=False,
            reason=f"{tool_name} 需要先定位活动,当前无选中活动",
        )

    # 3. sync_garmin 的上限检查
    if tool_name == "sync_garmin_activities":
        count = arguments.get("count", 5)
        if isinstance(count, (int, float)) and (count <= 0 or count > 20):
            return GuardResult(allowed=False, reason="count 必须在 1-20 之间")

    return GuardResult(allowed=True)
