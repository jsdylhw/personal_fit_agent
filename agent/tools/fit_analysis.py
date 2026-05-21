"""单活动 FIT 分析的只读工具目录与路由."""

from __future__ import annotations

from typing import Any

from core.data_tools import (
    get_activity_overview_tool,
    get_activity_summary_tool,
    get_distance_intervals_tool,
    get_time_intervals_tool,
    llm_safe_history,
    scan_activity_segments_tool,
)
from core.stats import prune_empty_values


def fit_data_tool_catalog() -> list[dict[str, Any]]:
    """analyze-file hidden tool loop 使用的只读数据查询工具."""
    return [
        {
            "name": "get_activity_overview",
            "description": "Return a compact high-level activity overview for lightweight inventory or quick profile questions, such as listing what activities happened in a period. Do not use as the first step for a full single-activity training report; use get_activity_summary instead.",
            "arguments": {},
        },
        {
            "name": "get_activity_summary",
            "description": "Primary objective data tool for full single-activity analysis reports. Return structured activity summary by sections. Default returns 8 core sections. Use sections to pick specific ones, or 'all' for all 11. Core sections (power/heart_rate/cadence/speed/elevation) have available/stats/summary fields.",
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
            "name": "scan_activity_segments",
            "description": "Scan the full activity once and return concise continuous high-power intervals lasting at least 30s. Each interval includes power/HR/cadence/speed/elevation context and marks climb only when the interval gains at least 30m. Also returns data-quality/configuration warnings. This is deterministic local analysis, not a report generator.",
            "arguments": {"window_seconds": 30, "step_seconds": 10, "max_segments": 12},
        },
        {
            "name": "get_history",
            "description": "Return prior compact training history if history is enabled for this analysis.",
            "arguments": {},
        },
    ]


fit_analysis_tool_catalog = fit_data_tool_catalog


def call_fit_analysis_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    parsed: dict[str, Any] | None = None,
    history_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将 LLM 的单活动 FIT 工具调用路由到对应只读实现."""
    data_tool_names = {
        "get_activity_overview",
        "get_activity_summary",
        "get_time_intervals",
        "get_distance_intervals",
        "scan_activity_segments",
    }
    if name in data_tool_names and parsed is None:
        return {
            "tool": name,
            "arguments": arguments,
            "error": "missing_parsed",
            "message": "This tool requires a parsed FIT file.",
        }

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
        elif name == "scan_activity_segments":
            result = scan_activity_segments_tool(
                parsed,
                window_seconds=arguments.get("window_seconds", 30),
                step_seconds=arguments.get("step_seconds", 10),
                max_segments=arguments.get("max_segments", 12),
            )
        elif name == "get_history":
            result = llm_safe_history(history_before) or {
                "schema_version": "file_training_history.v1",
                "count": 0,
                "activities": [],
                "note": "History was not enabled or no previous activities exist.",
            }
        else:
            return {"tool": name, "arguments": arguments, "error": "unknown_tool"}

        return {"tool": name, "arguments": arguments, "result": prune_empty_values(result)}
    except Exception as exc:
        return {
            "tool": name,
            "arguments": arguments,
            "error": type(exc).__name__,
            "message": str(exc),
        }
