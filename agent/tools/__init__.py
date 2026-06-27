"""Agent 工具包 — 所有 LLM 可调用工具的统一定义与导出.

按类型组织:
- spec.py          — ToolDef + ToolRegistry + renderers + 类别常量
- fit_query.py     — FIT 数据查询工具 (6 ToolDef + handler 工厂 + 路由)
- index_query.py   — 活动索引工具 (3 ToolDef)
- agent_tools.py   — Agent tool-use 工具

业务 handler 已移至 agent/workflow/handlers/，通过 tools/__init__ 保持兼容 re-export。
"""

from agent.tools.agent_tools import AGENT_TOOLS
from agent.tools.fit_query import (
    FIT_DATA_TOOLS,
    build_tool_handlers,
    call_fit_analysis_tool,
    fit_analysis_tool_catalog,
    fit_data_tool_catalog,
)
from agent.tools.index_query import INDEX_TOOLS, index_tool_catalog
from agent.tools.spec import (
    CATEGORY_ACTIVITY_INDEX,
    CATEGORY_ACTIVITY_RESOLUTION,
    CATEGORY_ANALYSIS,
    CATEGORY_COACHING,
    CATEGORY_CONVERSATION,
    CATEGORY_FIT_QUERY,
    CATEGORY_OPERATION,
    CATEGORY_PLANNING,
    CATEGORY_STRAVA,
    ToolDef,
    ToolRegistry,
    render_anthropic_tool,
    render_anthropic_tools,
)
# 兼容 re-export: 业务 handler 已移至 agent.workflow.handlers
from agent.workflow.handlers import (
    MAX_SYNC_COUNT,
    analyze_fit_file_tool,
    sync_garmin_activities_tool,
    upload_to_strava_tool,
)

__all__ = [
    # spec
    "CATEGORY_ACTIVITY_INDEX",
    "CATEGORY_ACTIVITY_RESOLUTION",
    "CATEGORY_ANALYSIS",
    "CATEGORY_COACHING",
    "CATEGORY_CONVERSATION",
    "CATEGORY_FIT_QUERY",
    "CATEGORY_OPERATION",
    "CATEGORY_PLANNING",
    "CATEGORY_STRAVA",
    "ToolDef",
    "ToolRegistry",
    "render_anthropic_tool",
    "render_anthropic_tools",
    # fit_query
    "FIT_DATA_TOOLS",
    "build_tool_handlers",
    "call_fit_analysis_tool",
    "fit_analysis_tool_catalog",
    "fit_data_tool_catalog",
    # index_query
    "INDEX_TOOLS",
    "index_tool_catalog",
    # agent_tools
    "AGENT_TOOLS",
    # handlers (兼容 re-export)
    "MAX_SYNC_COUNT",
    "analyze_fit_file_tool",
    "sync_garmin_activities_tool",
    "upload_to_strava_tool",
]
