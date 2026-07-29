"""FIT 分析子 Agent 的数据查询与完成协议工具定义."""

from __future__ import annotations

from agent.tools.spec import CATEGORY_ANALYSIS, CATEGORY_FIT_QUERY, ToolDef

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
        description="""Primary objective data for full single-activity reports. Return structured summary by sections. Core sections include power/heart_rate/cadence/speed/pace/elevation; running_dynamics is returned only when the FIT device recorded it.
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
        description="""Scan for sustained effort segments >= 30s. Cycling uses high power; running uses faster-than-baseline pace. Each interval includes available power/HR/cadence/speed/elevation context. Marks climb only when >= 30m gain. Returns data-quality warnings.
Use for: hard intervals, fast running segments, climbs, surges. This is a locator, not a report generator — after finding segments, use get_time_intervals or get_distance_intervals to inspect in detail.""",
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
        name="get_running_efficiency",
        description="""Compare the first and last active 30% of a running activity. Returns pace, heart-rate, cadence and available running-dynamics changes, plus data-quality limits.
Use for: running-form stability, late-run pace change, or heart-rate response. Only use for running activities; it is descriptive and does not normalize terrain, weather, or stops.""",
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


SUBMIT_ANALYSIS_TOOL = ToolDef(
    name="submit_analysis",
    description=(
        "Submit the final activity analysis and end the ActivityAnalysisAgent session. "
        "Call this exactly once after you have enough data. Do not call any data tools after it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "markdown_report": {
                "type": "string",
                "description": "Complete Chinese Markdown activity report that explicitly answers user_request when present.",
            },
            "strava_summary": {
                "type": "string",
                "description": "About 200 Chinese characters for Strava, following strava_summary_style.",
            },
            "history_entry": {
                "type": "object",
                "description": "Compact structured entry for future activity comparisons.",
            },
        },
        "required": ["markdown_report", "strava_summary", "history_entry"],
    },
    category=CATEGORY_ANALYSIS,
)


# The child agent receives both read-only FIT tools and the explicit completion
# tool. Keeping FIT_DATA_TOOLS separate preserves its read-only data contract.
FIT_ANALYSIS_TOOLS = (*FIT_DATA_TOOLS, SUBMIT_ANALYSIS_TOOL)
