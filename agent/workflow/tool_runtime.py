"""Runtime adapters for tools used by the LLM tool loop."""

from __future__ import annotations

import json
from typing import Any

from agent.context import AgentContext
from agent.workflow.tool_result import remember_failed_action
from agent.workflow.todos import write_todos


def build_tool_handlers(context: AgentContext) -> dict[str, Any]:
    def _casual_chat(answer=None, message=None, **kw):
        return {"answer": answer or message or "你好，我在。"}

    def _ask_user_clarification(question=None, **kw):
        return {"answer": question or "请再描述一下你的需求。"}

    def _todo_write(todos, **kw):
        return write_todos(context, todos)

    def _sync_garmin_activities(count=5, **kw):
        from agent.workflow.handlers.ops import sync_garmin_activities_tool
        result = sync_garmin_activities_tool(count=int(count))
        context.last_tool_result = {"step_name": "sync_garmin_activities", "result": result}
        return result

    def _step(name, **kw):
        return run_tool_step(name, kw, context)

    return {
        "todo_write": _todo_write,
        "casual_chat": _casual_chat,
        "ask_user_clarification": _ask_user_clarification,
        "resolve_current_activity": lambda **kw: _step("resolve_current_activity", **kw),
        "resolve_activity_by_date": lambda **kw: _step("resolve_activity_by_date", **kw),
        "resolve_activity_range": lambda **kw: _step("resolve_activity_range", **kw),
        "resolve_recent_activities": lambda **kw: _step("resolve_recent_activities", **kw),
        "analyze_single_activity": lambda force=False, **kw: _step("analyze_single_activity", force=force, **kw),
        "summarize_activity_range": lambda **kw: _step("summarize_activity_range", **kw),
        "compare_activities": lambda **kw: _step("compare_activities", **kw),
        "compare_with_history": lambda **kw: _step("summarize_activity_range", **kw),
        "generate_training_advice": lambda **kw: _step("summarize_activity_range", **kw),
        "summarize_recent_training_load": lambda **kw: _step("summarize_recent_training_load", **kw),
        "generate_route_advice": lambda **kw: _step("generate_route_advice", **kw),
        "sync_garmin_activities": _sync_garmin_activities,
        "analyze_new_fit_files": lambda **kw: _step("analyze_new_fit_files", **kw),
        "generate_summary_file": lambda force=False, **kw: _step("generate_summary_file", force=force, **kw),
        "ensure_activity_summaries": lambda force=False, **kw: _step("ensure_activity_summaries", force=force, **kw),
        "upload_strava_activity": lambda force=False, **kw: _step("upload_strava_activity", force=force, **kw),
    }


def run_tool_step(name: str, args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Execute one tool-use step directly."""
    from agent.activity.comparison import compare_selected_activities_tool
    from agent.activity.report import show_selected_activity_report_tool
    from agent.activity.resolution.executor import execute_activity_resolution_tool
    from agent.activity.training_load import summarize_recent_training_load_tool
    from agent.route.advice import generate_route_advice_tool
    from agent.workflow.tool_handlers import (
        empty_activity_resolution_answer,
        execute_analyze_new_fit_files,
        execute_ensure_activity_summaries,
        execute_generate_summary_file,
        execute_summarize_activity_range,
        execute_upload_strava_activity,
    )

    if name.startswith("resolve_"):
        return execute_activity_resolution_tool(name, args, context)
    if name == "analyze_new_fit_files":
        return execute_analyze_new_fit_files(context)
    if name == "generate_summary_file":
        return execute_generate_summary_file(name, args, context)
    if name == "ensure_activity_summaries":
        return execute_ensure_activity_summaries(name, args, context)
    if name == "upload_strava_activity":
        return execute_upload_strava_activity(name, args, context)
    if name == "summarize_activity_range":
        return execute_summarize_activity_range(name, args, context)
    if name == "compare_activities":
        return compare_selected_activities_tool(context, name=name)
    if name == "summarize_recent_training_load":
        return summarize_recent_training_load_tool(context, name=name)
    if name == "analyze_single_activity":
        empty_answer = empty_activity_resolution_answer(
            str((context.last_tool_result or {}).get("step_name") or ""),
            (context.last_tool_result or {}).get("result") if isinstance((context.last_tool_result or {}).get("result"), dict) else {},
        )
        if empty_answer:
            return {
                "step": name,
                "status": "completed",
                "answer": empty_answer,
                "result": {
                    "schema_version": "activity_analysis_skipped.v1",
                    "reason": "empty_activity_resolution",
                },
            }
        return show_selected_activity_report_tool(context, args=args, name=name)
    if name == "generate_route_advice":
        return generate_route_advice_tool(context, args=args, name=name)
    if name in {"compare_with_history", "generate_training_advice"}:
        return {
            "error": "handler_not_implemented",
            "message": f"{name} needs a dedicated direct tool handler before it can run.",
        }
    return {"error": "unknown_tool", "name": name}


def execute_saved_action(
    action: dict[str, Any],
    context: AgentContext,
    *,
    verbose: bool = False,
    intent: str,
    label: str,
) -> dict[str, Any]:
    """Execute a saved pending/retry action outside the LLM loop."""
    handlers = build_tool_handlers(context)
    tool_name = str(action.get("tool") or "")
    tool_input = action.get("input") if isinstance(action.get("input"), dict) else {}
    handler = handlers.get(tool_name)
    if not handler:
        answer = f"未知工具: {tool_name}"
        context.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return {"answer": answer, "status": "failed", "context": context, "intent": intent, "steps": []}

    try:
        output = handler(**tool_input)
    except Exception as exc:
        output = {"error": type(exc).__name__, "message": str(exc)}

    context.last_tool_result = {"step_name": tool_name, "result": output}
    remember_failed_action(context, tool_name, tool_input, output)

    result_json = json.dumps(output, ensure_ascii=False, default=str)
    context.messages.append({"role": "user", "content": f"[{label}] {tool_name}"})
    context.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"已执行 {tool_name}:\n{result_json[:300]}"}]})
    if verbose:
        from agent.workflow.hooks import _log
        _log(f"  [{label}] \033[1m{tool_name}\033[0m {result_json[:120]}")

    return {
        "answer": f"已执行 {tool_name}。\n{result_json[:200]}",
        "status": "completed",
        "context": context,
        "intent": intent,
        "steps": [{"tool": tool_name, "input": tool_input}],
    }
