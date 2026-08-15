"""Direct tool-use handler registry."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.main_agent.context import AgentContext
from agent.main_agent.tool_result import is_failed_tool_output, remember_failed_action
from agent.runtime.models import ToolExecution, TurnResult

ToolHandler = Callable[[dict[str, Any], AgentContext], dict[str, Any]]


def activate_skill(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Activate one registered Skill and return its complete bounded protocol."""
    from agent.skills import get_skill, load_skill_instructions
    from agent.main_agent.turn_policy import activation_note

    skill_id = str(args.get("skill_id") or "").strip()
    skill = get_skill(skill_id)
    if skill is None:
        return {
            "status": "failed",
            "error": "unknown_skill",
            "message": f"Unknown skill: {skill_id}",
        }
    context.active_skill_id = skill.skill_id
    context.active_skill_confidence = 1.0
    context.active_skill_reason = "activated_by_main_agent"
    latest_message = next((
        str(item.get("content") or "") for item in reversed(context.messages)
        if isinstance(item, dict) and item.get("role") == "user"
    ), "")
    note = activation_note(skill.skill_id, latest_message)
    instructions = load_skill_instructions(skill)
    if note:
        instructions = f"{instructions}\n\n{note}"
    return {
        "status": "activated",
        "skill_id": skill.skill_id,
        "instructions": instructions,
        "allowed_tools": list(skill.tool_names),
        "allow_side_effects": skill.allow_side_effects,
    }


def casual_chat(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return {"answer": args.get("answer") or args.get("message") or "你好，我在。"}


def ask_user_clarification(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return {"answer": args.get("question") or "请再描述一下你的需求。"}


def resolve_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_selection import resolve_activities as resolve

    return resolve(args, context)


def lookup_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Read an auxiliary activity selection without changing current focus."""
    from agent.tools.handlers.activity_selection import lookup_activities as lookup

    return lookup(args, context)


def find_segments(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_analysis import find_segments as find

    return find(args, context)


def inspect_selection(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_analysis import inspect_selection as inspect

    return inspect(args, context)


def analyze_selection(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_analysis import analyze_selection as analyze

    return analyze(args, context)


def navigate_selection(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_analysis import navigate_selection as navigate

    return navigate(args, context)


def analyze_activity(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_reporting import show_selected_activity_report_tool
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
    from agent.tools.handlers.activity_reporting import query_selected_activity_detail_tool

    if len(context.selected_activities) != 1:
        return {
            "error": "single_activity_required",
            "message": "query_activity_detail 只能查询一条已定位活动；请先用 resolve_activities 精确定位。",
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
    from agent.tools.handlers.activity_insights import compare_selected_activities_tool

    return compare_selected_activities_tool(context, name="compare_activities")


def generate_training_advice(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return summarize_activities(args, context)


def summarize_recent_training_load(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_insights import summarize_recent_training_load_tool

    return summarize_recent_training_load_tool(context, name="summarize_recent_training_load")


def calculate_history_metrics(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_insights import calculate_history_metrics_tool

    return calculate_history_metrics_tool(
        context,
        group_by=str(args.get("group_by") or "week"),
        name="calculate_history_metrics",
    )


def analyze_training_history(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.activity_insights import analyze_training_history_tool

    return analyze_training_history_tool(
        context,
        group_by=str(args.get("group_by") or "week"),
        sport_type=str(args.get("sport_type") or "") or None,
        combine_sports_for_volume=bool(args.get("combine_sports_for_volume")),
        name="analyze_training_history",
    )


def generate_route_advice(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from agent.tools.handlers.route import generate_route_advice_tool

    return generate_route_advice_tool(context, args=args, name="generate_route_advice")


def sync_garmin_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Pure Garmin sync: download/index only, with no analysis workflow."""
    from operations.activity.sync import sync_recent

    return sync_recent(count=int(args.get("count", 5)))


def sync_and_run_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """同步 Garmin，并把本次已索引活动冻结为一个持久化 Run。"""
    from operations.activity.workflow_service import sync_and_start_activity_workflow

    result = sync_and_start_activity_workflow(
        count=int(args.get("count", 5)),
        goals=args.get("goals") or ("ensure_summary",),
        force=bool(args.get("force")),
        force_upload=bool(args.get("force_upload")),
    )
    return result


def run_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import start_local_activity_workflow

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
    from operations.activity.report_batch import submit_activity_report_rebuild

    return submit_activity_report_rebuild(scope=str(args.get("scope") or "all"))


def get_activity_report_job(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """Read progress for a bulk report rebuild without starting new work."""
    from operations.activity.report_batch import get_activity_report_job as get_job

    return get_job(str(args.get("job_id") or ""))


def get_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import get_activity_workflow as get_workflow

    return get_workflow(str(args.get("workflow_id") or ""))


def retry_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import retry_activity_workflow as retry_workflow

    task_ids = args.get("task_ids")
    result = retry_workflow(
        str(args.get("workflow_id") or ""),
        task_ids=task_ids if isinstance(task_ids, list) else None,
    )
    return result


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "activate_skill": activate_skill,
    "casual_chat": casual_chat,
    "ask_user_clarification": ask_user_clarification,
    "resolve_activities": resolve_activities,
    "lookup_activities": lookup_activities,
    "find_segments": find_segments,
    "inspect_selection": inspect_selection,
    "analyze_selection": analyze_selection,
    "navigate_selection": navigate_selection,
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
    "analyze_training_history": analyze_training_history,
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
        return TurnResult(
            answer=answer, status="failed", context=context, intent=intent,
            skill_id=context.active_skill_id,
            selected_activities=context.selected_activities,
            current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
        ).to_dict()

    try:
        output = handler(tool_input, context)
    except Exception as exc:
        output = {"error": type(exc).__name__, "message": str(exc)}

    context.last_tool_result = {"step_name": tool_name, "result": output}
    remember_failed_action(context, tool_name, tool_input, output)

    failed = is_failed_tool_output(output)
    payload = output if isinstance(output, dict) else {"result": output}
    execution = ToolExecution(
        index=0,
        tool=tool_name,
        input=tool_input,
        status=str(payload.get("status") or ("failed" if failed else "completed")),
        message=str(payload["message"]) if payload.get("message") is not None else None,
        error=str(payload["error"]) if payload.get("error") is not None else None,
        result=output,
    )
    context.execution_trace = [execution.to_dict()]
    result_json = json.dumps(output, ensure_ascii=False, default=str)
    context.messages.append({"role": "user", "content": f"[{label}] {tool_name}"})
    context.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"已执行 {tool_name}:\n{result_json[:300]}"}]})
    if verbose:
        from agent.main_agent.hooks import _log
        _log(f"  [{label}] \033[1m{tool_name}\033[0m {result_json[:120]}")

    return TurnResult(
        answer=(
            f"重试 {tool_name} 仍未完成。\n{result_json[:200]}"
            if failed else f"已执行 {tool_name}。\n{result_json[:200]}"
        ),
        status="failed" if failed else "completed",
        context=context,
        intent=intent,
        skill_id=context.active_skill_id,
        executions=[execution],
        selected_activities=context.selected_activities,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
    ).to_dict()
