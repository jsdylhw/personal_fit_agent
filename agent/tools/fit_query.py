"""FIT 数据查询工具:ToolDef 定义 + 路由实现.

这些是 LLM 在 tool loop 中可调用的只读工具.
"""

from __future__ import annotations

from typing import Any

from agent.tools.spec import CATEGORY_FIT_QUERY, ToolDef
from core.data_tools import (
    get_activity_overview_tool,
    get_activity_summary_tool,
    get_distance_intervals_tool,
    get_time_intervals_tool,
    llm_safe_history,
    scan_activity_segments_tool,
)
from core.stats import prune_empty_values

# -- 工具定义 ------------------------------------------------------------

FIT_DATA_TOOLS = (
    ToolDef(
        name="get_activity_overview",
        description="""Compact high-level activity overview.
Use for: lightweight inventory, listing activities in a period, quick profile questions.
Do NOT use as the first step for a full single-activity training report — use get_activity_summary instead.""",
        category=CATEGORY_FIT_QUERY,
    ),
    ToolDef(
        name="get_activity_summary",
        description="""Primary objective data for full single-activity reports. Return structured summary by sections. Core sections (power/heart_rate/cadence/speed/elevation) have available/stats/summary fields.
Use for: full training reports needing grouped objective data.
Use sections to pick specific ones, or 'all' for all 11.""",
        input_schema={
            "type": "object",
            "properties": {"sections": {"type": "array", "items": {"type": "string"}}},
        },
        category=CATEGORY_FIT_QUERY,
    ),
    ToolDef(
        name="scan_activity_segments",
        description="""Scan for continuous high-power intervals >= 30s. Each interval includes power/HR/cadence/speed/elevation context. Marks climb only when >= 30m gain. Returns data-quality warnings.
Use for: hard intervals, high-power sections, climbs with power, surges. This is a locator, not a report generator — after finding segments, use get_time_intervals or get_distance_intervals to inspect in detail.""",
        input_schema={
            "type": "object",
            "properties": {
                "window_seconds": {"type": "integer", "default": 30},
                "step_seconds": {"type": "integer", "default": 10},
                "max_segments": {"type": "integer", "default": 12},
            },
        },
        category=CATEGORY_FIT_QUERY,
    ),
    ToolDef(
        name="get_time_intervals",
        description="""Fixed time-window averages. bucket_seconds supports 1-600s. Use start_s/end_s for a focused window. Includes non-zero averages and zero fractions.
Use for: time-based averages (every 1min, 5min), inspecting a specific time window (e.g., 100-200s hard effort).
Prefer 30s/60s/5min for normal analysis. Use very small buckets like 3s only for focused short windows.""",
        input_schema={
            "type": "object",
            "properties": {
                "bucket_seconds": {"type": "integer", "default": 60},
                "start_s": {"type": ["integer", "null"], "default": None},
                "end_s": {"type": ["integer", "null"], "default": None},
            },
        },
        category=CATEGORY_FIT_QUERY,
    ),
    ToolDef(
        name="get_distance_intervals",
        description="""Fixed distance-window averages. Use bucket_distance_m for every 1km/3km/5km. Use start_d/end_d for a focused window. Includes non-zero averages and zero fractions.
Use for: distance-based averages (every 1km, 3km, 5km), inspecting a specific distance window (e.g., 2km-3km climb).
Prefer for climbs and pacing analysis.""",
        input_schema={
            "type": "object",
            "properties": {
                "bucket_distance_m": {"type": "integer", "default": 1000},
                "start_d": {"type": ["integer", "null"], "default": None},
                "end_d": {"type": ["integer", "null"], "default": None},
            },
        },
        category=CATEGORY_FIT_QUERY,
    ),
    ToolDef(
        name="get_history",
        description="""Prior compact training history, if enabled for this analysis.
Use for: user explicitly asked to reference history, or longitudinal comparison materially improves the answer.
Do NOT request if the user hasn't asked for history context.""",
        category=CATEGORY_FIT_QUERY,
    ),
)


# -- 兼容旧接口 ----------------------------------------------------------

def fit_data_tool_catalog() -> list[dict[str, Any]]:
    """返回可供 LLM 消费的工具目录(兼容旧接口,逐步迁移到 ToolRegistry)."""
    return [t.to_anthropic() for t in FIT_DATA_TOOLS]


fit_analysis_tool_catalog = fit_data_tool_catalog


# -- 工具 handler 工厂 -----------------------------------------------------

def build_tool_handlers(
    parsed: dict[str, Any],
    history_before: dict[str, Any] | None,
) -> dict[str, Any]:
    """构建 tool loop 使用的 handler 字典.

    每个 handler 接收 **block.input 作为参数,parsed/history_before 通过闭包注入.
    返回的 dict 可以直接用于 tool loop 分发:

        handler = handlers.get(block["name"])
        output = handler(**block.get("input", {})) if handler else ...
    """

    def _overview():
        return get_activity_overview_tool(parsed)

    def _summary(sections=None):
        return get_activity_summary_tool(parsed, sections=sections)

    def _segments(window_seconds=30, step_seconds=10, max_segments=12):
        return scan_activity_segments_tool(
            parsed,
            window_seconds=int(window_seconds),
            step_seconds=int(step_seconds),
            max_segments=int(max_segments),
        )

    def _time_intervals(bucket_seconds=60, start_s=None, end_s=None):
        return get_time_intervals_tool(
            parsed,
            bucket_seconds=int(bucket_seconds),
            start_s=start_s,
            end_s=end_s,
        )

    def _distance_intervals(bucket_distance_m=1000, start_d=None, end_d=None):
        return get_distance_intervals_tool(
            parsed,
            bucket_distance_m=int(bucket_distance_m),
            start_d=start_d,
            end_d=end_d,
        )

    def _history():
        return llm_safe_history(history_before) or {
            "schema_version": "file_training_history.v1",
            "count": 0,
            "activities": [],
            "note": "History was not enabled or no previous activities exist.",
        }

    return {
        "get_activity_overview": _overview,
        "get_activity_summary": _summary,
        "scan_activity_segments": _segments,
        "get_time_intervals": _time_intervals,
        "get_distance_intervals": _distance_intervals,
        "get_history": _history,
    }


# -- 兼容旧接口 ------------------------------------------------------------

def call_fit_analysis_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    parsed: dict[str, Any] | None = None,
    history_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将 LLM 的单活动 FIT 工具调用路由到对应只读实现(兼容旧接口)."""
    if parsed is None and name != "get_history":
        return {
            "tool": name,
            "arguments": arguments,
            "error": "missing_parsed",
            "message": "This tool requires a parsed FIT file.",
        }

    handlers = build_tool_handlers(parsed, history_before)
    handler = handlers.get(name)
    if handler is None:
        return {"tool": name, "arguments": arguments, "error": "unknown_tool"}

    try:
        result = handler(**{k: v for k, v in arguments.items() if v is not None})
        return {"tool": name, "arguments": arguments, "result": prune_empty_values(result)}
    except Exception as exc:
        return {
            "tool": name,
            "arguments": arguments,
            "error": type(exc).__name__,
            "message": str(exc),
        }
