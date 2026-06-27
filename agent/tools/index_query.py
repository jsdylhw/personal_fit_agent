"""活动索引查询工具:ToolDef 定义.

这些工具由 activity_resolution executor 调用,对应 core/activity_index.py
中的 list_activities / resolve_activity / get_activities_in_range.
"""

from __future__ import annotations

from typing import Any

from agent.tools.spec import CATEGORY_ACTIVITY_INDEX, ToolDef

INDEX_TOOLS = (
    ToolDef(
        name="list_activities",
        description="列出本地活动索引中的活动,可按 sport_type/order/limit 过滤.",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "sport_type": {"type": ["string", "null"]},
                "order": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
            },
        },
        category=CATEGORY_ACTIVITY_INDEX,
    ),
    ToolDef(
        name="resolve_activity",
        description="按 activity_key / activity_index / date_local / name 定位一条活动.",
        input_schema={
            "type": "object",
            "properties": {
                "activity_key": {"type": ["string", "null"]},
                "activity_index": {"type": ["integer", "null"]},
                "date_local": {"type": ["string", "null"]},
                "name": {"type": ["string", "null"]},
                "sport_type": {"type": ["string", "null"]},
                "match": {"type": "string", "enum": ["latest", "earliest"], "default": "latest"},
            },
        },
        category=CATEGORY_ACTIVITY_INDEX,
    ),
    ToolDef(
        name="get_activities_in_range",
        description="按日期范围定位多条本地活动.",
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "sport_type": {"type": ["string", "null"]},
            },
            "required": ["start_date", "end_date"],
        },
        category=CATEGORY_ACTIVITY_INDEX,
    ),
)


def index_tool_catalog() -> list[dict[str, Any]]:
    """返回活动索引工具目录."""
    return [t.to_anthropic() for t in INDEX_TOOLS]
