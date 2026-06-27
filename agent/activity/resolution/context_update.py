"""对 AgentContext 的副作用更新 — 将解析出的活动写入 context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.activity.models import ActivityHandle
from agent.context import AgentContext


def activity_from_context(context: AgentContext) -> ActivityHandle | None:
    if context.current_fit_file or context.current_activity_key:
        return ActivityHandle(
            activity_key=context.current_activity_key or "",
            fit_path=str(context.current_fit_file) if context.current_fit_file else None,
            summary_path=str(context.current_summary_path) if context.current_summary_path else None,
        )
    return None


def update_context_from_single_activity(
    context: AgentContext,
    activity: dict[str, Any] | None,
) -> None:
    if not activity:
        context.clear_activities()
        return
    handle = ActivityHandle.from_index_entry(activity)
    context.set_single_activity(handle)


def update_context_from_activity_list(
    context: AgentContext,
    activities: list[Any],
    *,
    scope: dict[str, Any],
) -> None:
    handles = [
        ActivityHandle.from_index_entry(entry)
        for entry in activities
        if isinstance(entry, dict)
    ]
    context.set_selected_activities(handles, scope=scope)
