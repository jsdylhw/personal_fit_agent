"""Planner step 工具定义 — 18 个粗粒度工作流步骤.

统一使用 ToolDef 格式,与 fit_query / index_query 一致.
"""

from __future__ import annotations

from agent.tools.spec import (
    CATEGORY_ACTIVITY_RESOLUTION,
    CATEGORY_ANALYSIS,
    CATEGORY_COACHING,
    CATEGORY_CONVERSATION,
    CATEGORY_OPERATION,
    CATEGORY_STRAVA,
    ToolDef,
)

PLANNER_TOOLS: tuple[ToolDef, ...] = (
    # -- conversation --------------------------------------------------
    ToolDef(
        name="casual_chat",
        description="处理不需要活动数据的问候或普通聊天。",
        input_schema={
            "type": "object",
            "properties": {"answer": {"type": "string", "description": "预设回答"}},
        },
        category=CATEGORY_CONVERSATION,
    ),
    ToolDef(
        name="ask_user_clarification",
        description="请求范围或意图不明确时追问聚焦问题。",
        input_schema={
            "type": "object",
            "properties": {"question": {"type": "string", "description": "追问的问题"}},
        },
        category=CATEGORY_CONVERSATION,
    ),
    # -- activity_resolution -------------------------------------------
    ToolDef(
        name="resolve_current_activity",
        description="以当前 FIT 或已选活动作为分析对象。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_ACTIVITY_RESOLUTION,
    ),
    ToolDef(
        name="resolve_activity_by_date",
        description="按日期/名称/key/index 定位一条活动。activity_index 是时间正序编号，1 表示最早。",
        input_schema={
            "type": "object",
            "properties": {
                "activity_key": {"type": "string"},
                "activity_index": {"type": "integer"},
                "date_local": {"type": "string", "description": "ISO date, e.g. 2026-05-18"},
                "name": {"type": "string"},
                "sport_type": {"type": "string"},
                "match": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
            },
        },
        category=CATEGORY_ACTIVITY_RESOLUTION,
    ),
    ToolDef(
        name="resolve_activity_range",
        description="按周/月/日期范围定位多条本地活动。",
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "ISO date"},
                "end_date": {"type": "string", "description": "ISO date"},
                "range_type": {"type": "string", "enum": ["week", "month", "days"]},
                "relative_range": {"type": "string", "enum": ["this_week", "this_month", "last_week", "last_month"]},
                "sport_type": {"type": "string"},
            },
        },
        category=CATEGORY_ACTIVITY_RESOLUTION,
    ),
    ToolDef(
        name="resolve_recent_activities",
        description="定位最近 N 条活动，可按最新或最早排序。",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
                "sport_type": {"type": "string"},
                "order": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
            },
        },
        category=CATEGORY_ACTIVITY_RESOLUTION,
    ),
    # -- analysis ------------------------------------------------------
    ToolDef(
        name="analyze_single_activity",
        description="基于 FIT 数据分析单条活动，生成报告。需要先 resolve 活动。",
        input_schema={
            "type": "object",
            "properties": {"force": {"type": "boolean", "default": False, "description": "强制重新分析"}},
        },
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="summarize_activity_range",
        description="汇总多条活动生成整体总结报告。",
        input_schema={
            "type": "object",
            "properties": {
                "response_mode": {"type": "string", "enum": ["ai_summary", "compact"], "default": "compact"},
                "detail_level": {"type": "string", "enum": ["normal", "detailed"], "default": "normal"},
                "force": {"type": "boolean", "default": False},
            },
        },
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="compare_with_history",
        description="将已选活动与近期训练历史对比。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="compare_activities",
        description="多条活动横向对比，仅用于明确比较意图。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="summarize_recent_training_load",
        description="提取 TSS/IF 等结构化训练负荷。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_ANALYSIS,
    ),
    # -- coaching ------------------------------------------------------
    ToolDef(
        name="generate_training_advice",
        description="根据活动数据和历史生成下一次训练或周训练建议。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_COACHING,
    ),
    ToolDef(
        name="generate_route_advice",
        description="按位置、时长/距离、目标和可选训练状态推荐路线类型。",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "位置/区域"},
                "duration": {"type": "integer", "description": "时长(分钟)"},
                "distance": {"type": "integer", "description": "距离(km)"},
                "goal": {"type": "string", "description": "骑行目标"},
                "terrain": {"type": "string", "description": "地形偏好"},
                "scenery": {"type": "string", "description": "风景偏好"},
                "preferences": {"type": "array", "items": {"type": "string"}},
            },
        },
        category=CATEGORY_COACHING,
    ),
    # -- operation -----------------------------------------------------
    ToolDef(
        name="sync_garmin_activities",
        description="下载最近的 Garmin 活动。有副作用，需要确认。",
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
        },
        category=CATEGORY_OPERATION,
    ),
    ToolDef(
        name="analyze_new_fit_files",
        description="对同步得到的新 FIT 运行保存型分析。需要 sync_garmin_activities 先执行。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_OPERATION,
    ),
    ToolDef(
        name="generate_summary_file",
        description="为指定 FIT 生成或刷新 summary JSON。",
        input_schema={
            "type": "object",
            "properties": {"force": {"type": "boolean", "default": False}},
        },
        category=CATEGORY_OPERATION,
    ),
    ToolDef(
        name="ensure_activity_summaries",
        description="检查已选活动 summary 缺失时生成；重新分析时 force=true。",
        input_schema={
            "type": "object",
            "properties": {"force": {"type": "boolean", "default": False}},
        },
        category=CATEGORY_OPERATION,
    ),
    # -- strava --------------------------------------------------------
    ToolDef(
        name="upload_strava_activity",
        description="直接上传 Strava，不额外分析或刷新报告。有副作用，需要确认。",
        input_schema={
            "type": "object",
            "properties": {"force": {"type": "boolean", "default": False, "description": "遇到重复时更新描述"}},
        },
        category=CATEGORY_STRAVA,
    ),
)
