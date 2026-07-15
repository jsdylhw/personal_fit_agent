"""Agent tool-use 工具定义.

统一使用 ToolDef 格式,与 fit_query / index_query 一致.
"""

from __future__ import annotations

from agent.tools.spec import (
    CATEGORY_ACTIVITY_RESOLUTION,
    CATEGORY_ANALYSIS,
    CATEGORY_COACHING,
    CATEGORY_CONVERSATION,
    CATEGORY_OPERATION,
    CATEGORY_PLANNING,
    CATEGORY_STRAVA,
    ToolDef,
)

MAIN_AGENT_TOOLS: tuple[ToolDef, ...] = (
    # -- planning ------------------------------------------------------
    ToolDef(
        name="todo_write",
        description=(
            "创建或更新当前会话的 TODO 计划。仅用于规划和跟踪状态,不执行任何业务操作。"
            "多步骤任务应先调用它,并在步骤状态变化时更新。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
        category=CATEGORY_PLANNING,
    ),
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
    # -- activity ------------------------------------------------------
    ToolDef(
        name="find_activity",
        description=(
            "定位活动并写入当前会话上下文。"
            "scope=current 使用当前活动; scope=recent 定位最近/最早 N 条;"
            "scope=activity 按 activity_key/activity_index/date/name 定位单条;"
            "scope=range 按日期范围定位多条。activity_index 是时间正序编号,1 表示最早。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["current", "recent", "activity", "range"],
                    "default": "recent",
                },
                "activity_key": {"type": "string"},
                "activity_index": {"type": "integer"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 1},
                "order": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
                "date_local": {"type": "string", "description": "ISO date, e.g. 2026-05-18"},
                "date": {"type": "string", "description": "相对或 ISO 日期,如 today/yesterday/2026-05-18"},
                "name": {"type": "string"},
                "sport_type": {"type": "string"},
                "match": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
                "start_date": {"type": "string", "description": "ISO date"},
                "end_date": {"type": "string", "description": "ISO date"},
                "range_type": {"type": "string", "enum": ["week", "month", "days"]},
                "relative_range": {"type": "string", "enum": ["this_week", "this_month", "last_week", "last_month"]},
                "range": {"type": "string", "description": "可传 all 表示全部历史活动"},
            },
        },
        category=CATEGORY_ACTIVITY_RESOLUTION,
    ),
    ToolDef(
        name="analyze_activity",
        description="分析已定位的单条活动,生成或读取活动报告。通常先调用 find_activity。",
        input_schema={
            "type": "object",
            "properties": {
                "force": {"type": "boolean", "default": False, "description": "强制重新分析"},
                "activity_key": {"type": "string"},
                "activity_index": {"type": "integer"},
                "user_request": {"type": "string"},
            },
        },
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="summarize_activities",
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
        name="download_activities",
        description="下载最近的 Garmin 活动。有副作用，需要确认。",
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
        },
        category=CATEGORY_OPERATION,
    ),
    ToolDef(
        name="analyze_new_activities",
        description="对刚下载得到的新 FIT 运行保存型分析。需要 download_activities 先执行。",
        input_schema={"type": "object", "properties": {}},
        category=CATEGORY_OPERATION,
    ),
    # -- strava --------------------------------------------------------
    ToolDef(
        name="upload_activity",
        description="直接上传 Strava，不额外分析或刷新报告。有副作用，需要确认。",
        input_schema={
            "type": "object",
            "properties": {"force": {"type": "boolean", "default": False, "description": "遇到重复时更新描述"}},
        },
        category=CATEGORY_STRAVA,
    ),
)

# Backward-compatible export name for existing imports.
AGENT_TOOLS = MAIN_AGENT_TOOLS
