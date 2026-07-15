"""Direct tool-use handler registry."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.context import AgentContext
from agent.main_agent.tool_result import remember_failed_action
from agent.main_agent.todos import write_todos

ToolHandler = Callable[[dict[str, Any], AgentContext], dict[str, Any]]


def todo_write(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return write_todos(context, args.get("todos") or [])


def casual_chat(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return {"answer": args.get("answer") or args.get("message") or "你好，我在。"}


def ask_user_clarification(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return {"answer": args.get("question") or "请再描述一下你的需求。"}


def sync_garmin_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.operations import sync_garmin_activities_tool

    result = sync_garmin_activities_tool(count=int(args.get("count", 5)))
    context.last_tool_result = {"step_name": "download_activities", "result": result}
    return result


def download_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return sync_garmin_activities(args, context)


def find_activity(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    scope = str(args.get("scope") or "").lower()
    if not scope:
        scope = _infer_find_activity_scope(args)

    if scope == "current":
        step_name = "resolve_current_activity"
        step_args: dict[str, Any] = {}
    elif scope == "range":
        step_name = "resolve_activity_range"
        step_args = args
    elif scope == "activity":
        step_name = "resolve_activity_by_date"
        step_args = args
    else:
        step_name = "resolve_recent_activities"
        step_args = args

    result = _resolve_activity(step_name, step_args, context)
    if isinstance(result, dict):
        result = {
            **result,
            "step": "find_activity",
            "resolution_step": step_name,
        }
    return result


def analyze_activity(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.report import show_selected_activity_report_tool
    from agent.main_agent.handlers import empty_activity_resolution_answer

    last = context.last_tool_result or {}
    last_result = last.get("result") if isinstance(last.get("result"), dict) else {}
    empty_answer = empty_activity_resolution_answer(str(last.get("step_name") or ""), last_result)
    if empty_answer:
        return {
            "step": "analyze_activity",
            "status": "completed",
            "answer": empty_answer,
            "result": {
                "schema_version": "activity_analysis_skipped.v1",
                "reason": "empty_activity_resolution",
            },
        }
    return show_selected_activity_report_tool(context, args=args, name="analyze_activity")


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


def generate_route_advice(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.route.advice import generate_route_advice_tool

    return generate_route_advice_tool(context, args=args, name="generate_route_advice")


def analyze_new_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.main_agent.handlers import execute_analyze_new_fit_files

    return execute_analyze_new_fit_files(context, args)


def upload_activity(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.main_agent.handlers import execute_upload_strava_activity

    return execute_upload_strava_activity("upload_activity", args, context)


def _resolve_activity(name: str, args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.activity.resolution.executor import execute_activity_resolution_tool

    return execute_activity_resolution_tool(name, args, context)


def _infer_find_activity_scope(args: dict[str, Any]) -> str:
    if args.get("start_date") or args.get("end_date") or args.get("relative_range") or args.get("range_type"):
        return "range"
    if str(args.get("range") or "").lower() == "all":
        return "range"
    if args.get("activity_key") or args.get("activity_index") or args.get("date") or args.get("date_local") or args.get("name"):
        return "activity"
    if args.get("current") is True:
        return "current"
    return "recent"


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "todo_write": todo_write,
    "casual_chat": casual_chat,
    "ask_user_clarification": ask_user_clarification,
    "find_activity": find_activity,
    "analyze_activity": analyze_activity,
    "summarize_activities": summarize_activities,
    "download_activities": download_activities,
    "analyze_new_activities": analyze_new_activities,
    "upload_activity": upload_activity,
    "compare_activities": compare_activities,
    "generate_training_advice": generate_training_advice,
    "summarize_recent_training_load": summarize_recent_training_load,
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

    context.permission_grants.clear()

    return {
        "answer": f"已执行 {tool_name}。\n{result_json[:200]}",
        "status": "completed",
        "context": context,
        "intent": intent,
        "steps": [{"tool": tool_name, "input": tool_input}],
    }
