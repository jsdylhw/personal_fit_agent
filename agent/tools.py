"""LLM 工具目录与路由.

两个 catalog:
- fit_data_tool_catalog(): 5 个只读数据查询工具,给 analyze-file 的 hidden tool loop 用
- agent_workflow_tool_catalog(): 8 个工具(数据查询 + 下载/分析/上传),给 agent 模式用

call_fit_analysis_tool() 统一路由,根据 name 分发到 core/data_tools 或 core/workflow_tools.
"""

from __future__ import annotations

from typing import Any

from core.activity_index import (
    get_activities_in_range,
    list_activities,
    resolve_activity,
)
from core.data_tools import (
    get_activity_overview_tool,
    get_activity_summary_tool,
    get_distance_intervals_tool,
    get_time_intervals_tool,
    llm_safe_history,
)
from core.stats import prune_empty_values
from core.workflow_tools import (
    _parse_strict_bool,
    analyze_fit_file_tool,
    sync_garmin_activities_tool,
    upload_to_strava_tool,
)


def fit_data_tool_catalog() -> list[dict[str, Any]]:
    """analyze-file 的 hidden tool loop 使用的只读数据查询工具."""
    return [
        {
            "name": "get_activity_overview",
            "description": "Return a compact high-level activity overview: sport, local start time, duration, distance, total ascent, calories, basic power/HR/cadence/speed metrics, TSS/IF, and data availability flags.",
            "arguments": {},
        },
        {
            "name": "get_activity_summary",
            "description": "Return structured objective activity summary by sections. Default returns 8 core sections. Use sections to pick specific ones, or 'all' for all 11. Core sections (power/heart_rate/cadence/speed/elevation) have available/stats/summary fields.",
            "arguments": {"sections": ["all"]},
        },
        {
            "name": "get_time_intervals",
            "description": "Return fixed time-window averages. bucket_seconds supports 1-600 seconds; prefer 30s/60s/5min for normal analysis. Use start_s/end_s for a focused window. Power/cadence/speed include non-zero averages and zero fractions.",
            "arguments": {"bucket_seconds": 60, "start_s": None, "end_s": None},
        },
        {
            "name": "get_distance_intervals",
            "description": "Return fixed distance-window averages. Use bucket_distance_m for every 1km/3km/5km; use start_d/end_d for a focused window. Power/cadence/speed include non-zero averages and zero fractions.",
            "arguments": {"bucket_distance_m": 1000, "start_d": None, "end_d": None},
        },
        {
            "name": "get_history",
            "description": "Return prior compact training history if history is enabled for this analysis.",
            "arguments": {},
        },
    ]


def agent_workflow_tool_catalog() -> list[dict[str, Any]]:
    """agent 模式使用的完整工具集(数据查询 + 下载/分析/上传)."""
    return fit_data_tool_catalog() + [
        {
            "name": "list_activities",
            "description": "List indexed local activities from data/activity_index.json. Use this before selecting activities by date or finding recent activities. Arguments: limit, sport_type.",
            "arguments": {"limit": 20, "sport_type": None},
        },
        {
            "name": "resolve_activity",
            "description": "Resolve one indexed activity by activity_key, date_local (YYYY-MM-DD), name/file stem, and optional sport_type. Returns selected activity and candidates if multiple match.",
            "arguments": {"activity_key": None, "date_local": None, "name": None, "sport_type": None, "match": "latest"},
        },
        {
            "name": "get_activities_in_range",
            "description": "Return indexed activities in a local date range for weekly/monthly summaries. Arguments: start_date, end_date, sport_type.",
            "arguments": {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "sport_type": None},
        },
        {
            "name": "sync_garmin_activities",
            "description": "Download recent FIT files from Garmin China. Auto-skips already-downloaded activities by filename comparison. Count is capped at 20.",
            "arguments": {"count": 5},
        },
        {
            "name": "analyze_fit_file",
            "description": "Batch-generate or refresh data/summaries/*.summary.json and Strava summary for a FIT file using the hidden analysis loop. Do NOT use for detailed conversational analysis when current_fit_file is already available; use data query tools instead. Use after sync_garmin_activities or when the user explicitly asks to generate/refresh the saved summary.",
            "arguments": {"fit_path": "/path/to/file.fit", "force": False},
        },
        {
            "name": "upload_to_strava",
            "description": "Upload a FIT file to Strava with the generated Strava summary as description. REQUIRES CONFIRMATION: first call without confirmed returns preview, then call again with confirmed=true to execute. WARNING: confirmed ONLY accepts Python True, not strings.",
            "arguments": {"fit_path": "/path/to/file.fit", "confirmed": False},
        },
    ]


# 向后兼容:analyze-file 仍在用
fit_analysis_tool_catalog = fit_data_tool_catalog


def call_fit_analysis_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    parsed: dict[str, Any] | None = None,
    history_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将 LLM 的工具调用路由到对应的实现.

    Args:
        name: 工具名.
        arguments: LLM 传入的参数 dict.
        parsed: parse_fit() 的返回值(数据查询工具需要).
        history_before: 历史活动数据(数据查询工具需要).

    Returns:
        dict: {tool, arguments, result} 或 {tool, arguments, error, message}.
    """
    _data_tool_names = {"get_activity_overview", "get_activity_summary", "get_time_intervals", "get_distance_intervals"}
    if name in _data_tool_names and parsed is None:
        return {"tool": name, "arguments": arguments, "error": "missing_parsed", "message": "This tool requires a parsed FIT file."}

    try:
        # -- 工作流工具(副作用,仅 agent 模式) --
        if name == "list_activities":
            result = list_activities(limit=int(arguments.get("limit", 20)), sport_type=arguments.get("sport_type"))
        elif name == "resolve_activity":
            result = resolve_activity(
                activity_key=arguments.get("activity_key"),
                date_local=arguments.get("date_local"),
                name=arguments.get("name"),
                sport_type=arguments.get("sport_type"),
                match=str(arguments.get("match") or "latest"),
            )
        elif name == "get_activities_in_range":
            result = get_activities_in_range(
                start_date=str(arguments.get("start_date") or ""),
                end_date=str(arguments.get("end_date") or ""),
                sport_type=arguments.get("sport_type"),
            )
        elif name == "sync_garmin_activities":
            result = sync_garmin_activities_tool(count=int(arguments.get("count", 5)))
        elif name == "analyze_fit_file":
            result = analyze_fit_file_tool(str(arguments.get("fit_path", "")), force=_parse_strict_bool(arguments.get("force")))
        elif name == "upload_to_strava":
            result = upload_to_strava_tool(str(arguments.get("fit_path", "")), confirmed=_parse_strict_bool(arguments.get("confirmed")))

        # -- 只读数据查询工具 --
        elif name == "get_activity_overview":
            result = get_activity_overview_tool(parsed)
        elif name == "get_activity_summary":
            result = get_activity_summary_tool(parsed, sections=arguments.get("sections"))
        elif name == "get_time_intervals":
            result = get_time_intervals_tool(parsed, bucket_seconds=int(arguments.get("bucket_seconds", 60)), start_s=arguments.get("start_s"), end_s=arguments.get("end_s"))
        elif name == "get_distance_intervals":
            result = get_distance_intervals_tool(parsed, bucket_distance_m=arguments.get("bucket_distance_m", 1000), start_d=arguments.get("start_d"), end_d=arguments.get("end_d"))
        elif name == "get_history":
            result = llm_safe_history(history_before) or {"schema_version": "file_training_history.v1", "count": 0, "activities": [], "note": "History was not enabled or no previous activities exist."}
        else:
            return {"tool": name, "arguments": arguments, "error": "unknown_tool"}

        return {"tool": name, "arguments": arguments, "result": prune_empty_values(result)}
    except Exception as exc:
        return {"tool": name, "arguments": arguments, "error": type(exc).__name__, "message": str(exc)}
