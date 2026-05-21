"""对 AgentContext 的副作用更新工具。

将解析出的活动信息写回 context 的 selected_activities /
current_fit_file / current_activity_key / current_summary_path 等字段。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.context import AgentContext


def activity_from_context(context: AgentContext) -> dict[str, Any] | None:
    if not context.current_fit_file and not context.current_activity_key:
        return None
    return {
        "activity_key": context.current_activity_key,
        "fit_path": str(context.current_fit_file) if context.current_fit_file else None,
        "summary_path": str(context.current_summary_path) if context.current_summary_path else None,
    }


def update_context_from_single_activity(context: AgentContext, activity: dict[str, Any] | None) -> None:
    context.selected_activities = [activity] if activity else []
    context.selected_activity_range = {"type": "single_activity"} if activity else None
    if not activity:
        return
    _update_current_activity_fields(context, activity)


def update_context_from_activity_list(
    context: AgentContext,
    activities: list[Any],
    *,
    scope: dict[str, Any],
) -> None:
    context.selected_activities = [
        activity
        for activity in activities
        if isinstance(activity, dict)
    ]
    context.selected_activity_range = scope
    if len(context.selected_activities) == 1:
        _update_current_activity_fields(context, context.selected_activities[0])


def _update_current_activity_fields(context: AgentContext, activity: dict[str, Any]) -> None:
    if activity.get("fit_path"):
        context.current_fit_file = Path(str(activity["fit_path"])).expanduser()
    if activity.get("activity_key"):
        context.current_activity_key = str(activity["activity_key"])
    if activity.get("summary_path"):
        context.current_summary_path = Path(str(activity["summary_path"])).expanduser()
