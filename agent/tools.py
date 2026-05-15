"""LLM 工具目录与路由.

fit_analysis_tool_catalog() 定义 LLM 可见的所有工具及其参数.
call_fit_analysis_tool() 将 LLM 的工具调用请求路由到 core/data_tools.py 中的实现.
"""

from __future__ import annotations

from typing import Any

from core.data_tools import (
    get_activity_overview_tool,
    get_activity_summary_tool,
    get_distance_intervals_tool,
    get_time_intervals_tool,
)
from core.stats import prune_empty_values


def fit_analysis_tool_catalog() -> list[dict[str, Any]]:
    """返回 LLM 可见的工具列表,每个工具包含 name,description,arguments.

    这是工具定义的唯一权威来源.System prompt 不重复列工具,
    payload 中的 available_tools 由 build_initial_loop_payload 从这里取.

    Returns:
        list[dict]: 5 个工具的定义.
    """
    return [
        {
            "name": "get_activity_overview",
            "description": "Return a compact high-level activity overview: sport, local start time, duration, distance, total ascent, calories, basic power/HR/cadence/speed metrics, TSS/IF, and data availability flags.",
            "arguments": {},
        },
        {
            "name": "get_activity_summary",
            "description": "Return structured objective activity summary by sections. Default returns 8 core sections. Use sections to pick specific ones, or 'all' for all 11. Core sections (power/heart_rate/cadence/speed/elevation) have available/stats/summary fields; other sections have their own shapes.",
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


def call_fit_analysis_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    parsed: dict[str, Any],
    history_before: dict[str, Any] | None,
) -> dict[str, Any]:
    """将 LLM 的工具调用路由到对应的数据工具实现.

    Args:
        name: 工具名,对应 fit_analysis_tool_catalog 中的 name.
        arguments: LLM 传入的参数 dict.
        parsed: parse_fit() 的返回值.
        history_before: 历史活动数据(可选).

    Returns:
        dict: {tool, arguments, result} 或 {tool, arguments, error, message}.
    """
    try:
        if name == "get_activity_overview":
            result = get_activity_overview_tool(parsed)
        elif name == "get_activity_summary":
            result = get_activity_summary_tool(parsed, sections=arguments.get("sections"))
        elif name == "get_time_intervals":
            result = get_time_intervals_tool(
                parsed,
                bucket_seconds=int(arguments.get("bucket_seconds", 60)),
                start_s=arguments.get("start_s"),
                end_s=arguments.get("end_s"),
            )
        elif name == "get_distance_intervals":
            result = get_distance_intervals_tool(
                parsed,
                bucket_distance_m=arguments.get("bucket_distance_m", 1000),
                start_d=arguments.get("start_d"),
                end_d=arguments.get("end_d"),
            )
        elif name == "get_history":
            result = history_before or {
                "schema_version": "file_training_history.v1",
                "count": 0,
                "activities": [],
                "note": "History was not enabled or no previous activities exist.",
            }
        else:
            return {"tool": name, "arguments": arguments, "error": "unknown_tool"}
        return {"tool": name, "arguments": arguments, "result": prune_empty_values(result)}
    except Exception as exc:
        return {"tool": name, "arguments": arguments, "error": type(exc).__name__, "message": str(exc)}
