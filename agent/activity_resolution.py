"""activity_resolution 步骤执行逻辑.

这一层只负责把用户计划中的活动范围解析成本地活动记录,并更新
AgentContext.它不分析 FIT,不生成 summary,也不上传.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from agent.context import AgentContext
from agent.plan_schema import WorkflowPlanStep
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
    if step.name not in ACTIVITY_RESOLUTION_STEPS:
        return {
            "step": step.name,
            "error": "unsupported_activity_resolution_step",
            "message": f"{step.name} is not an activity_resolution step.",
        }

    if step.name == "resolve_current_activity":
        return _resolve_current_activity(step, context)
    if step.name == "resolve_activity_by_date":
        return _resolve_activity_by_date(step, context, index_path=index_path, today=today)
    if step.name == "resolve_activity_range":
        return _resolve_activity_range(step, context, index_path=index_path, today=today)
    if step.name == "resolve_recent_activities":
        return _resolve_recent_activities(step, context, index_path=index_path)

    raise AssertionError(f"unhandled activity resolution step: {step.name}")


def _resolve_current_activity(step: WorkflowPlanStep, context: AgentContext) -> dict[str, Any]:
    activity = _activity_from_context(context)
    context.selected_activities = [activity] if activity else []
    context.selected_activity_range = {"type": "current_activity"} if activity else None
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
    index_path: str | Path | None,
    today: date | None,
) -> dict[str, Any]:
    args = step.arguments
    date_local = _date_argument(args, today=today)
    result = resolve_activity(
        activity_key=args.get("activity_key"),
        date_local=date_local,
        name=args.get("name"),
        sport_type=args.get("sport_type"),
        match=str(args.get("match") or "latest"),
        path=index_path,
    )
    activity = result.get("activity") if isinstance(result.get("activity"), dict) else None
    _update_context_from_single_activity(context, activity)
    return {
        "step": step.name,
        "result": result,
    }


def _resolve_activity_range(
    step: WorkflowPlanStep,
    context: AgentContext,
    *,
    index_path: str | Path | None,
    today: date | None,
) -> dict[str, Any]:
    args = step.arguments
    start_date, end_date = _date_range_arguments(args, today=today)
    result = get_activities_in_range(
        start_date=start_date,
        end_date=end_date,
        sport_type=args.get("sport_type"),
        path=index_path,
    )
    _update_context_from_activity_list(
        context,
        result.get("activities") if isinstance(result.get("activities"), list) else [],
        scope={
            "type": "date_range",
            "start_date": start_date,
            "end_date": end_date,
            "sport_type": args.get("sport_type"),
        },
    )
    return {
        "step": step.name,
        "result": result,
    }


def _resolve_recent_activities(
    step: WorkflowPlanStep,
    context: AgentContext,
    *,
    index_path: str | Path | None,
) -> dict[str, Any]:
    args = step.arguments
    result = list_activities(
        limit=int(args.get("limit") or args.get("count") or 5),
        sport_type=args.get("sport_type"),
        path=index_path,
    )
    _update_context_from_activity_list(
        context,
        result.get("activities") if isinstance(result.get("activities"), list) else [],
        scope={
            "type": "recent_activities",
            "limit": int(args.get("limit") or args.get("count") or 5),
            "sport_type": args.get("sport_type"),
        },
    )
    return {
        "step": step.name,
        "result": result,
    }


def _activity_from_context(context: AgentContext) -> dict[str, Any] | None:
    if not context.current_fit_file and not context.current_activity_key:
        return None
    return {
        "activity_key": context.current_activity_key,
        "fit_path": str(context.current_fit_file) if context.current_fit_file else None,
        "summary_path": str(context.current_summary_path) if context.current_summary_path else None,
    }


def _update_context_from_single_activity(context: AgentContext, activity: dict[str, Any] | None) -> None:
    context.selected_activities = [activity] if activity else []
    context.selected_activity_range = {"type": "single_activity"} if activity else None
    if not activity:
        return
    if activity.get("fit_path"):
        context.current_fit_file = Path(str(activity["fit_path"])).expanduser()
    if activity.get("activity_key"):
        context.current_activity_key = str(activity["activity_key"])
    if activity.get("summary_path"):
        context.current_summary_path = Path(str(activity["summary_path"])).expanduser()


def _update_context_from_activity_list(
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
        _update_context_from_single_activity(context, context.selected_activities[0])


def _date_argument(args: dict[str, Any], *, today: date | None) -> str | None:
    value = args.get("date_local") or args.get("date")
    if value:
        return _resolve_relative_date(str(value), today=today)
    date_range = _range_text_argument(args)
    if _mentions_today(date_range) or _mentions_yesterday(date_range):
        return _resolve_relative_date(date_range, today=today)
    return None


def _date_range_arguments(args: dict[str, Any], *, today: date | None) -> tuple[str, str]:
    current = today or date.today()
    if args.get("start_date") and args.get("end_date"):
        return str(args["start_date"]), str(args["end_date"])

    date_range = _range_text_argument(args)
    if _mentions_today(date_range) or _mentions_yesterday(date_range):
        resolved = _resolve_relative_date(date_range, today=current)
        return resolved, resolved

    days = args.get("days")
    if days is not None:
        count = max(1, int(days))
        start = current - timedelta(days=count - 1)
        return start.isoformat(), current.isoformat()

    return current.isoformat(), current.isoformat()


def _range_text_argument(args: dict[str, Any]) -> str:
    """兼容 LLM 对日期范围参数的几种常见写法."""
    return str(
        args.get("date_range")
        or args.get("range_type")
        or args.get("range_description")
        or args.get("relative_range")
        or ""
    ).strip().lower()


def _resolve_relative_date(value: str, *, today: date | None) -> str:
    current = today or date.today()
    normalized = value.strip().lower()
    if _mentions_today(normalized):
        return current.isoformat()
    if _mentions_yesterday(normalized):
        return (current - timedelta(days=1)).isoformat()
    return value


def _mentions_today(value: str) -> bool:
    return "today" in value or "今天" in value


def _mentions_yesterday(value: str) -> bool:
    return "yesterday" in value or "昨天" in value
