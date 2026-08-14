"""Thin Agent adapters for deterministic multi-activity services."""

from __future__ import annotations

from typing import Any

from agent.main_agent.context import AgentContext
from services.activity.comparison import compare_activities
from services.activity.history import calculate_history_metrics
from services.activity.training_history_analysis import analyze_training_history
from services.activity.training_load import summarize_training_load


def compare_selected_activities_tool(
    context: AgentContext,
    *,
    name: str = "compare_activities",
) -> dict[str, Any]:
    """Pass the current concrete selection to the comparison service."""
    return compare_activities(
        [item for item in context.selected_activities if isinstance(item, dict)],
        name=name,
    )


def calculate_history_metrics_tool(
    context: AgentContext,
    *,
    group_by: str = "week",
    name: str = "calculate_history_metrics",
) -> dict[str, Any]:
    """Pass selected activities and their frozen scope to history aggregation."""
    return calculate_history_metrics(
        context.selected_activities,
        scope=context.selected_activity_range,
        group_by=group_by,
        name=name,
    )


def summarize_recent_training_load_tool(
    context: AgentContext,
    *,
    name: str = "summarize_recent_training_load",
) -> dict[str, Any]:
    """Pass selected activities to the deterministic load service."""
    return summarize_training_load(
        context.selected_activities,
        scope=context.selected_activity_range,
        name=name,
    )


def analyze_training_history_tool(
    context: AgentContext,
    *,
    group_by: str = "week",
    sport_type: str | None = None,
    combine_sports_for_volume: bool = False,
    name: str = "analyze_training_history",
) -> dict[str, Any]:
    """Build the professional history artifact from the frozen selection."""
    return analyze_training_history(
        context.selected_activities,
        scope=context.selected_activity_range,
        group_by=group_by,
        sport_type=sport_type,
        combine_sports_for_volume=combine_sports_for_volume,
        name=name,
    )
