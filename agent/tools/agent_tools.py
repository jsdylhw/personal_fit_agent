"""Agent tool-use 工具定义.

统一使用 ToolDef 格式,与 fit_query / index_query 一致.
"""

from __future__ import annotations

from agent.tools.spec import (
    CATEGORY_ACTIVITY_SELECTION,
    CATEGORY_ANALYSIS,
    CATEGORY_COACHING,
    CATEGORY_CONVERSATION,
    CATEGORY_OPERATION,
    CATEGORY_WORKFLOW,
    ToolDef,
)

MAIN_AGENT_TOOLS: tuple[ToolDef, ...] = (
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
            "根据提供的事实条件自动选择单条、范围或最近活动；不要传 scope/mode。"
            "activity_key/activity_index/date/name 表示单条；start/end/relative_range/days 表示范围；"
            "没有这些条件时返回最近 N 条。activity_index 是时间正序编号,1 表示最早。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "current": {"type": "boolean", "description": "使用当前已定位活动"},
                "activity_key": {"type": "string"},
                "activity_index": {"type": "integer"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 1},
                "order": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
                "date_local": {"type": "string", "description": "ISO date, e.g. 2026-05-18"},
                "date": {"type": "string", "description": "相对或 ISO 日期,如 today/yesterday/2026-05-18"},
                "name": {"type": "string"},
                "sport_type": {"type": "string", "description": "可传 cycling/running/walking，也接受 Ride、骑行、run、跑步等常见别名。"},
                "time_of_day": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "evening", "night"],
                    "description": "按本地开始时间过滤；morning 为 04:00-11:59。",
                },
                "match": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
                "start_date": {"type": "string", "description": "ISO date"},
                "end_date": {"type": "string", "description": "ISO date"},
                "range_type": {"type": "string", "enum": ["week", "month", "days"]},
                "relative_range": {"type": "string", "enum": ["this_week", "this_month", "last_week", "last_month"]},
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3650,
                    "description": "最近 N 天（含今天），例如最近一个月可传 30。",
                },
                "range": {"type": "string", "description": "可传 all 表示全部历史活动"},
            },
        },
        category=CATEGORY_ACTIVITY_SELECTION,
    ),
    ToolDef(
        name="analyze_activity",
        description="读取已定位单条活动的完整报告；已有 summary 时直接返回，缺失时才生成。通常先调用 find_activity，且不能用于批量逐条分析。",
        input_schema={
            "type": "object",
            "properties": {
                "force": {"type": "boolean", "default": False, "description": "强制重新分析"},
            },
        },
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="query_activity_detail",
        description=(
            "回答单条活动必须读取 FIT 原始区间数据的定向问题，例如指定秒数、距离段、冲刺、爬升或分段。"
            "先定位且只能选中一条活动；此工具会优先确保已有完整报告，再启动只读子 Agent 做一次定向查询。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "需要 FIT 原始数据验证的具体问题"},
            },
            "required": ["question"],
        },
        category=CATEGORY_ANALYSIS,
    ),
    ToolDef(
        name="summarize_activities",
        description="汇总已定位的多条活动：优先读取已有 summary，仅对缺失 summary 的活动生成报告，然后一次性给出范围结论。",
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
    ToolDef(
        name="calculate_history_metrics",
        description=(
            "对已定位的多条活动计算确定性的历史指标和时间序列。"
            "用于周/月趋势、训练量变化、是否进步等问题；读取 activity_metrics，"
            "旧报告缺少结构化指标时只读解析 FIT，不从 LLM 报告文字提取数值。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "default": "week",
                    "description": "历史指标的时间分组粒度。",
                },
            },
        },
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
        description=(
            "只从 Garmin 下载最近活动并更新本地活动索引，然后结束。"
            "不会生成 summary、调用分析 Agent、上传 Strava 或创建 ActivityRun。"
            "用户只说同步/下载时使用此工具。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
        },
        category=CATEGORY_OPERATION,
    ),
    ToolDef(
        name="sync_and_run_activity_workflow",
        description=(
            "从 Garmin 同步最近活动后，严格只处理本次同步并成功索引的活动。"
            "可组合生成 summary、上传 Strava 和汇总；同步结果会冻结为持久化活动快照。"
            "仅在用户明确要求同步后继续分析、汇总或上传时使用；"
            "纯同步必须使用 sync_garmin_activities。不要把同步、分析和上传拆成对话中的多次调用。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "goals": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["ensure_summary", "upload_strava", "aggregate_report"]},
                },
                "force": {"type": "boolean", "default": False},
                "force_upload": {"type": "boolean", "default": False},
            },
        },
        category=CATEGORY_WORKFLOW,
    ),
    # -- persistent activity workflow --------------------------------
    ToolDef(
        name="run_activity_workflow",
        description=(
            "对本地已存在的多条活动创建并推进持久化工作流。"
            "可组合生成单条 summary、上传 Strava、汇总；任务状态会持久化，可在失败后重试。"
            "本地已有活动无需同步 Garmin。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
                "order": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
                "sport_type": {"type": "string"},
                "goals": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["ensure_summary", "upload_strava", "aggregate_report"]},
                    "description": "目标可组合；upload_strava 和 aggregate_report 会自动依赖 ensure_summary。",
                },
                "force": {"type": "boolean", "default": False, "description": "重新生成已有 summary"},
                "force_upload": {"type": "boolean", "default": False, "description": "重复活动时更新 Strava 描述"},
            },
        },
        category=CATEGORY_WORKFLOW,
    ),
    ToolDef(
        name="get_activity_workflow",
        description="读取持久化活动工作流的真实状态和任务结果；不执行操作。",
        input_schema={
            "type": "object",
            "properties": {"workflow_id": {"type": "string"}},
            "required": ["workflow_id"],
        },
        category=CATEGORY_WORKFLOW,
    ),
    ToolDef(
        name="retry_activity_workflow",
        description=(
            "重试一个工作流中失败的任务；会恢复因其失败被跳过的下游任务和旧的 partial 汇总。"
            "重试会直接推进可恢复的任务。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "task_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["workflow_id"],
        },
        category=CATEGORY_WORKFLOW,
    ),
)

# Backward-compatible export name for existing imports.
AGENT_TOOLS = MAIN_AGENT_TOOLS
