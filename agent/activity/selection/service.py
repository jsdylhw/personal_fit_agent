"""活动选择服务。

把用户计划中的活动范围解析成本地活动记录，更新 AgentContext。
不分析 FIT，不生成 summary，也不上传。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from agent.activity.selection.context_update import (
    activity_from_context,
    update_context_from_activity_list,
    update_context_from_single_activity,
)
from agent.activity.selection.arguments import (
    activity_index_from_text,
    date_argument,
    date_range_arguments,
    is_all_activities_range,
    order_argument,
)
from agent.context import AgentContext
from core.activity_index import get_activities_in_range, list_activities, resolve_activity

ACTIVITY_SELECTION_MODES = {
    "current",
    "single",
    "range",
    "recent",
}


def select_activity_mode(arguments: dict[str, Any]) -> str:
    """Choose a deterministic activity-selection mode from facts.

    A caller may say "today" and "morning", or provide a date range.  Those
    facts are sufficient; accepting a model-selected ``scope`` made single-day
    queries accidentally enter the range parser.
    """
    if arguments.get("current") is True:
        return "current"
    if any(arguments.get(key) for key in ("activity_key", "activity_index", "date", "date_local", "name")):
        return "single"
    if any(
        arguments.get(key)
        for key in (
            "start_date", "end_date", "date_range", "time_range", "range_type",
            "range_description", "relative_range", "range", "days",
        )
    ):
        return "range"
    return "recent"


def execute_activity_selection(
    mode: str,
    arguments: dict[str, Any],
    context: AgentContext,
    *,
    reason: str = "tool_use",
    index_path: str | Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Select local activities and update the session selection once.

    This is the only ActivityContext mutation point for the chat-facing
    ``find_activity`` tool.  FIT analysis and durable workflow selection use
    their own explicit inputs rather than relying on this mutable context.
    """
    handler = _MODE_DISPATCH.get(mode)
    if handler is None:
        return {
            "selection_mode": mode,
            "error": "unsupported_activity_selection_mode",
            "message": f"{mode} is not an activity selection mode.",
        }

    return handler(mode, arguments, context, reason=reason, index_path=index_path, today=today)


def _select_current_activity(
    mode: str,
    arguments: dict[str, Any],
    context: AgentContext,
    **kwargs: Any,
) -> dict[str, Any]:
    activity = activity_from_context(context)
    if activity:
        context.set_single_activity(activity)
    else:
        context.clear_activities()
    return {
        "selection_mode": mode,
        "result": {
            "schema_version": "activity_selection_result.v1",
            "scope": {"type": "current_activity"},
            "count": len(context.selected_activities),
            "activities": context.selected_activities,
        },
    }


def _select_single_activity(
    mode: str,
    arguments: dict[str, Any],
    context: AgentContext,
    *,
    reason: str = "tool_use",
    index_path: str | Path | None = None,
    today: date | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    args = arguments
    date_local = date_argument(args, today=today)
    result = resolve_activity(
        activity_key=args.get("activity_key"),
        activity_index=args.get("activity_index") or activity_index_from_text(reason),
        date_local=date_local,
        name=args.get("name"),
        sport_type=args.get("sport_type"),
        time_of_day=args.get("time_of_day"),
        match=str(args.get("match") or "latest"),
        path=index_path,
    )
    activity = result.get("activity") if isinstance(result.get("activity"), dict) else None
    update_context_from_single_activity(context, activity)
    return {"selection_mode": mode, "result": result}


def _select_activity_range(
    mode: str,
    arguments: dict[str, Any],
    context: AgentContext,
    *,
    reason: str = "tool_use",
    index_path: str | Path | None = None,
    today: date | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    args = arguments
    resolved_range = date_range_arguments(args, today=today)
    if resolved_range is None:
        if not is_all_activities_range(args):
            return {
                "selection_mode": mode,
                "error": "missing_activity_range",
                "message": "range selection requires start/end date, relative range, or days.",
            }
        result = list_activities(
            limit=0,
            sport_type=args.get("sport_type"),
            time_of_day=args.get("time_of_day"),
            order=order_argument(args, reason=reason),
            path=index_path,
        )
        activities = result.get("activities") if isinstance(result.get("activities"), list) else []
        update_context_from_activity_list(
            context,
            activities,
            scope={
                "type": "unbounded_range",
                "sport_type": args.get("sport_type"),
                **({"time_of_day": args["time_of_day"]} if args.get("time_of_day") else {}),
            },
        )
        return {"selection_mode": mode, "result": result}
    start_date, end_date = resolved_range
    result = get_activities_in_range(
        start_date=start_date,
        end_date=end_date,
        sport_type=args.get("sport_type"),
        time_of_day=args.get("time_of_day"),
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
            **({"time_of_day": args["time_of_day"]} if args.get("time_of_day") else {}),
        },
    )
    return {"selection_mode": mode, "result": result}


def _select_recent_activities(
    mode: str,
    arguments: dict[str, Any],
    context: AgentContext,
    *,
    reason: str = "tool_use",
    index_path: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    args = arguments
    limit_raw = args.get("limit") if args.get("limit") is not None else args.get("count")
    limit = _positive_int_argument(limit_raw, default=5, max_value=50)
    if limit is None:
        return {
            "selection_mode": mode,
            "error": "invalid_recent_activity_limit",
            "message": "recent activity selection limit/count must be a positive integer.",
        }
    result = list_activities(
        limit=limit,
        sport_type=args.get("sport_type"),
        time_of_day=args.get("time_of_day"),
        order=order_argument(args, reason=reason),
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
            **({"time_of_day": args["time_of_day"]} if args.get("time_of_day") else {}),
            "order": order_argument(args, reason=reason),
        },
    )
    return {"selection_mode": mode, "result": result}


def _positive_int_argument(value: Any, *, default: int, max_value: int) -> int | None:
    """运行时兜底:即使 LLM 传错类型也不要让 int('latest') 直接抛异常。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > max_value:
        return None
    return value


_MODE_DISPATCH = {
    "current": _select_current_activity,
    "single": _select_single_activity,
    "range": _select_activity_range,
    "recent": _select_recent_activities,
}
