"""Tool Guard — 运行时校验 LLM 工具调用的前置条件.

只做依赖/参数/合法性检查，不介入工具的副作用审批。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.context import AgentContext

# 工具 → 前置依赖(context 中必须存在)
TOOL_DEPENDENCIES: dict[str, set[str]] = {
    "analyze_activity": {"selected_activities"},
    "query_activity_detail": {"selected_activities"},
    "summarize_activities": {"selected_activities"},
    "compare_activities": {"selected_activities"},
    "summarize_recent_training_load": {"selected_activities"},
    "generate_training_advice": {"selected_activities"},
}


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""


def guard_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    context: AgentContext,
    allowed_categories: set[str],
    has_resolved: bool = False,
) -> GuardResult:
    """校验工具调用的前置条件.

    - 依赖检查: analyze 需要 selected_activities
    - 参数检查: sync count 范围
    - 不涉及副作用审批
    """
    # 依赖检查
    deps = TOOL_DEPENDENCIES.get(tool_name, set())
    if "selected_activities" in deps and not has_resolved:
        return GuardResult(
            allowed=False,
            reason=f"{tool_name} 需要先定位活动,当前无选中活动",
        )

    # 参数检查
    if tool_name == "sync_and_run_activity_workflow":
        count = arguments.get("count", 5)
        if isinstance(count, (int, float)) and (count <= 0 or count > 20):
            return GuardResult(allowed=False, reason="count 必须在 1-20 之间")

    return GuardResult(allowed=True)
