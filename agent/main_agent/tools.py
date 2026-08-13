"""Direct tool-use handler registry."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.context import AgentContext
from agent.main_agent.tool_result import remember_failed_action

ToolHandler = Callable[[dict[str, Any], AgentContext], dict[str, Any]]


def casual_chat(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return {"answer": args.get("answer") or args.get("message") or "你好，我在。"}


def ask_user_clarification(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return {"answer": args.get("question") or "请再描述一下你的需求。"}


def find_activity(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.selection import select_activity_mode

    selection_mode = select_activity_mode(args)
    selection_args: dict[str, Any] = {} if selection_mode == "current" else args

    result = _select_activities(selection_mode, selection_args, context)
    if isinstance(result, dict):
        result = {
            **result,
            "step": "find_activity",
            "selection_mode": selection_mode,
        }
    return result


def analyze_activity(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.report import show_selected_activity_report_tool
    from agent.main_agent.handlers import empty_activity_selection_answer

    last = context.last_tool_result or {}
    last_result = last.get("result") if isinstance(last.get("result"), dict) else {}
    empty_answer = empty_activity_selection_answer(
        str(last_result.get("selection_mode") or ""), last_result,
    )
    if empty_answer:
        return {
            "step": "analyze_activity",
            "status": "completed",
            "answer": empty_answer,
            "result": {
                "schema_version": "activity_analysis_skipped.v1",
                "reason": "empty_activity_selection",
            },
        }
    if len(context.selected_activities) != 1:
        return {
            "error": "single_activity_required",
            "message": "analyze_activity 只能读取一条已定位活动；多条活动请使用 summarize_activities。",
            "selected_count": len(context.selected_activities),
        }
    return show_selected_activity_report_tool(context, args=args, name="analyze_activity")


def query_activity_detail(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.report import query_selected_activity_detail_tool

    if len(context.selected_activities) != 1:
        return {
            "error": "single_activity_required",
            "message": "query_activity_detail 只能查询一条已定位活动；请先用 find_activity 精确定位。",
            "selected_count": len(context.selected_activities),
        }
    return query_selected_activity_detail_tool(
        context,
        question=str(args.get("question") or "").strip(),
        name="query_activity_detail",
    )


def summarize_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.main_agent.handlers import execute_summarize_activity_range

    return execute_summarize_activity_range("summarize_activities", args, context)


def compare_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.comparison import compare_selected_activities_tool

    return compare_selected_activities_tool(context, name="compare_activities")


def generate_training_advice(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return summarize_activities(args, context)


def summarize_recent_training_load(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.training_load import summarize_recent_training_load_tool

    return summarize_recent_training_load_tool(context, name="summarize_recent_training_load")


def calculate_history_metrics(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.history_metrics import calculate_history_metrics_tool

    return calculate_history_metrics_tool(
        context,
        group_by=str(args.get("group_by") or "week"),
        name="calculate_history_metrics",
    )


def generate_route_advice(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.route.advice import generate_route_advice_tool

    return generate_route_advice_tool(context, args=args, name="generate_route_advice")


def sync_garmin_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Pure Garmin sync: download/index only, with no analysis workflow."""
    from agent.activity.operations.garmin import sync_recent

    return sync_recent(count=int(args.get("count", 5)))


def sync_and_run_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """同步 Garmin，并把本次已索引活动冻结为一个持久化 Run。"""
    from agent.activity.workflow_service import sync_and_start_activity_workflow

    result = sync_and_start_activity_workflow(
        count=int(args.get("count", 5)),
        goals=args.get("goals") or ("ensure_summary",),
        force=bool(args.get("force")),
        force_upload=bool(args.get("force_upload")),
    )
    return result


def run_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.workflow_service import start_local_activity_workflow

    result = start_local_activity_workflow(
        limit=int(args.get("limit", 5)),
        order=str(args.get("order") or "latest"),
        sport_type=str(args["sport_type"]) if args.get("sport_type") else None,
        goals=args.get("goals") or ("ensure_summary",),
        force=bool(args.get("force")),
        force_upload=bool(args.get("force_upload")),
    )
    return result


def rebuild_activity_reports(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Submit a non-blocking, in-process rebuild of current V2 reports."""
    from agent.activity.report_jobs import submit_activity_report_rebuild

    return submit_activity_report_rebuild(scope=str(args.get("scope") or "all"))


def get_activity_report_job(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Read progress for a bulk report rebuild without starting new work."""
    from agent.activity.report_jobs import get_activity_report_job as get_job

    return get_job(str(args.get("job_id") or ""))


def get_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.workflow_service import get_activity_workflow as get_workflow

    return get_workflow(str(args.get("workflow_id") or ""))


def retry_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.workflow_service import retry_activity_workflow as retry_workflow

    task_ids = args.get("task_ids")
    result = retry_workflow(
        str(args.get("workflow_id") or ""),
        task_ids=task_ids if isinstance(task_ids, list) else None,
    )
    return result


def _select_activities(mode: str, args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    # Import the implementation module here so runtime instrumentation and
    # tests can replace the concrete service without a stale re-export.
    from agent.activity.selection.service import execute_activity_selection

    return execute_activity_selection(mode, args, context)


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "casual_chat": casual_chat,
    "ask_user_clarification": ask_user_clarification,
    "find_activity": find_activity,
    "analyze_activity": analyze_activity,
    "query_activity_detail": query_activity_detail,
    "summarize_activities": summarize_activities,
    "sync_garmin_activities": sync_garmin_activities,
    "sync_and_run_activity_workflow": sync_and_run_activity_workflow,
    "run_activity_workflow": run_activity_workflow,
    "rebuild_activity_reports": rebuild_activity_reports,
    "get_activity_report_job": get_activity_report_job,
    "get_activity_workflow": get_activity_workflow,
    "retry_activity_workflow": retry_activity_workflow,
    "compare_activities": compare_activities,
    "generate_training_advice": generate_training_advice,
    "summarize_recent_training_load": summarize_recent_training_load,
    "calculate_history_metrics": calculate_history_metrics,
    "generate_route_advice": generate_route_advice,
}


def execute_saved_action(
    action: dict[str, Any],
    context: AgentContext,
    *,
    verbose: bool = False,
    intent: str,
    label: str,
) -> dict[str, Any]:
    """Execute a saved pending/retry action outside the LLM loop."""
    tool_name = str(action.get("tool") or "")
    tool_input = action.get("input") if isinstance(action.get("input"), dict) else {}
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        answer = f"未知工具: {tool_name}"
        context.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return {"answer": answer, "status": "failed", "context": context, "intent": intent, "steps": []}

    try:
        output = handler(tool_input, context)
    except Exception as exc:
        output = {"error": type(exc).__name__, "message": str(exc)}

    context.last_tool_result = {"step_name": tool_name, "result": output}
    remember_failed_action(context, tool_name, tool_input, output)

    result_json = json.dumps(output, ensure_ascii=False, default=str)
    context.messages.append({"role": "user", "content": f"[{label}] {tool_name}"})
    context.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"已执行 {tool_name}:\n{result_json[:300]}"}]})
    if verbose:
        from agent.main_agent.hooks import _log
        _log(f"  [{label}] \033[1m{tool_name}\033[0m {result_json[:120]}")

    return {
        "answer": f"已执行 {tool_name}。\n{result_json[:200]}",
        "status": "completed",
        "context": context,
        "intent": intent,
        "steps": [{"tool": tool_name, "input": tool_input}],
    }
