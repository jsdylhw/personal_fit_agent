"""activity_resolution 步骤执行与分发。

把用户计划中的活动范围解析成本地活动记录，更新 AgentContext。
不分析 FIT，不生成 summary，也不上传。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from agent.activity.resolution.context_update import (
    activity_from_context,
    update_context_from_activity_list,
    update_context_from_single_activity,
)
from agent.activity.resolution.date_parser import (
    activity_index_from_text,
    date_argument,
    date_range_arguments,
    is_all_activities_range,
    order_argument,
)
from agent.context import AgentContext
from agent.workflow.plan_schema import WorkflowPlanStep
from core.activity_index import get_activities_in_range, list_activities, resolve_activity

ACTIVITY_RESOLUTION_STEPS = {
    "resolve_current_activity",
    "resolve_activity_by_date",
    "resolve_activity_range",
    "resolve_recent_activities",
}


def execute_activity_resolution_step(
    step: WorkflowPlanStep,
    context: AgentContext,
    *,
    index_path: str | Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """执行单个 activity_resolution 步骤."""
    handler = _STEP_DISPATCH.get(step.name)
    if handler is None:
        return {
            "step": step.name,
            "error": "unsupported_activity_resolution_step",
            "message": f"{step.name} is not an activity_resolution step.",
        }

    return handler(step, context, index_path=index_path, today=today)


def _resolve_current_activity(
    step: WorkflowPlanStep,
    context: AgentContext,
    **kwargs: Any,
) -> dict[str, Any]:
    activity = activity_from_context(context)
    if activity:
        context.set_single_activity(activity)
    else:
        context.clear_activities()
    return {
        "step": step.name,
        "result": {
            "schema_version": "activity_resolution_result.v1",
            "scope": {"type": "current_activity"},
            "count": len(context.selected_activities),
            "activities": context.selected_activities,
        },
    }


def _resolve_activity_by_date(
    step: WorkflowPlanStep,
    context: AgentContext,
    *,
    index_path: str | Path | None = None,
    today: date | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    args = step.arguments
    date_local = date_argument(args, today=today)
    result = resolve_activity(
        activity_key=args.get("activity_key"),
        activity_index=args.get("activity_index") or activity_index_from_text(step.reason),
        date_local=date_local,
        name=args.get("name"),
        sport_type=args.get("sport_type"),
        match=str(args.get("match") or "latest"),
        path=index_path,
    )
    activity = result.get("activity") if isinstance(result.get("activity"), dict) else None
    update_context_from_single_activity(context, activity)
    return {"step": step.name, "result": result}


def _resolve_activity_range(
    step: WorkflowPlanStep,
    context: AgentContext,
    *,
    index_path: str | Path | None = None,
    today: date | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    args = step.arguments
    resolved_range = date_range_arguments(args, today=today)
    if resolved_range is None:
        if not is_all_activities_range(args):
            return {
                "step": step.name,
                "error": "missing_activity_range",
                "message": "resolve_activity_range requires start/end date, relative range, or days.",
            }
        result = list_activities(
            limit=0,
            sport_type=args.get("sport_type"),
            order=order_argument(args, reason=step.reason),
            path=index_path,
        )
        activities = result.get("activities") if isinstance(result.get("activities"), list) else []
        update_context_from_activity_list(
            context,
            activities,
            scope={
                "type": "unbounded_range",
                "sport_type": args.get("sport_type"),
            },
        )
        return {"step": step.name, "result": result}
    start_date, end_date = resolved_range
    result = get_activities_in_range(
        start_date=start_date,
        end_date=end_date,
        sport_type=args.get("sport_type"),
        path=index_path,
    )
    activities = result.get("activities") if isinstance(result.get("activities"), list) else []
    update_context_from_activity_list(
        context,
        activities,
        scope={
            "type": "date_range",
            "start_date": start_date,
            "end_date": end_date,
            "sport_type": args.get("sport_type"),
        },
    )
    return {"step": step.name, "result": result}


def _resolve_recent_activities(
    step: WorkflowPlanStep,
    context: AgentContext,
    *,
    index_path: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    args = step.arguments
    limit_raw = args.get("limit") if args.get("limit") is not None else args.get("count")
    limit = _positive_int_argument(limit_raw, default=5, max_value=50)
    if limit is None:
        return {
            "step": step.name,
            "error": "invalid_recent_activity_limit",
            "message": "resolve_recent_activities.limit/count must be a positive integer.",
        }
    result = list_activities(
        limit=limit,
        sport_type=args.get("sport_type"),
        order=order_argument(args, reason=step.reason),
        path=index_path,
    )
    activities = result.get("activities") if isinstance(result.get("activities"), list) else []
    update_context_from_activity_list(
        context,
        activities,
        scope={
            "type": "recent_activities",
            "limit": limit,
            "sport_type": args.get("sport_type"),
            "order": order_argument(args, reason=step.reason),
        },
    )
    return {"step": step.name, "result": result}


def _positive_int_argument(value: Any, *, default: int, max_value: int) -> int | None:
    """执行层兜底:validator 被绕过时也不要让 int('latest') 直接抛异常。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > max_value:
        return None
    return value


_STEP_DISPATCH = {
    "resolve_current_activity": _resolve_current_activity,
    "resolve_activity_by_date": _resolve_activity_by_date,
    "resolve_activity_range": _resolve_activity_range,
    "resolve_recent_activities": _resolve_recent_activities,
}
