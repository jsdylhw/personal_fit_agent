"""ActivityAnalysisAgent 的写入权限."""

from __future__ import annotations

from typing import Any

from agent.context import AgentContext

ANALYSIS_WRITE_MESSAGE = "生成/刷新 summary 文件 (会写入本地磁盘)"
ANALYSIS_WRITE_PERMISSION = "activity_analysis_write"


def request_analysis_write_confirmation(
    context: AgentContext,
    *,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    """需要 ActivityAnalysisAgent 写 summary/history 前请求确认.

    这个权限属于分析子 agent:main agent 只负责把 pending action 交给现有
    确认控制流,不维护具体"分析会写文件"的规则。
    """
    if _is_confirmed(args):
        context.permission_grants.add(ANALYSIS_WRITE_PERMISSION)
        return None
    if ANALYSIS_WRITE_PERMISSION in context.permission_grants:
        return None

    context.pending_action = {
        "tool": tool_name,
        "input": {**args, "_confirmed": True},
        "message": ANALYSIS_WRITE_MESSAGE,
    }
    return {
        "step": tool_name,
        "status": "needs_confirmation",
        "answer": f"⚠ {ANALYSIS_WRITE_MESSAGE}\n\n请回复 '确认' 或 'yes' 来执行。",
        "result": {
            "schema_version": "activity_analysis_permission.v1",
            "reason": "writes_summary_files",
        },
    }


def _is_confirmed(args: dict[str, Any]) -> bool:
    return bool(args.get("_confirmed") or args.get("confirmed"))
