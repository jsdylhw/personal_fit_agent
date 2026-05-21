"""规划-校验-选择-执行的新 workflow 入口."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.context import AgentContext
from agent.guided_chat import resolve_fit_path
from agent.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.planner import plan_initial_workflow
from agent.workflow_executor import execute_workflow_plan


def run_planned_workflow(
    message: str,
    *,
    fit_path: str | Path | None = None,
    use_history: bool = True,
    max_tokens: int = 4096,
    include_details: bool = False,
) -> dict[str, Any]:
    """运行新规划执行链路:Planner -> Validator -> Selector -> Executor."""
    current_fit = resolve_fit_path(fit_path) if fit_path else None
    context = AgentContext(
        session_id="planned_workflow",
        current_fit_file=current_fit,
        history_enabled=use_history,
    )
    planner_result = plan_initial_workflow(
        message,
        context,
        max_tokens=max_tokens,
    )
    plan = normalize_workflow_plan(planner_result["plan"])
    execution = execute_workflow_plan(plan, context)
    output = {
        "answer": execution.final_response or _fallback_answer(execution),
        "status": execution.status,
        "plan": plan.to_dict(),
        "execution": execution.to_dict(),
        "selected_activities": context.selected_activities,
        "selected_activity_range": context.selected_activity_range,
        "current_fit_file": str(context.current_fit_file) if context.current_fit_file else None,
    }
    if include_details:
        output["raw_planner_text"] = planner_result["raw_text"]
        output["planner_payload"] = planner_result["payload"]
    return output


def normalize_workflow_plan(plan: WorkflowPlan) -> WorkflowPlan:
    """把 planner 放错层级的活动范围参数补回具体 step arguments."""
    scope = plan.activity_scope
    if not scope:
        return plan

    steps = [
        _normalize_step_arguments(step, scope)
        for step in plan.steps
    ]
    return WorkflowPlan(
        task_type=plan.task_type,
        steps=steps,
        activity_scope=plan.activity_scope,
        allow_side_effects=plan.allow_side_effects,
        requires_confirmation=plan.requires_confirmation,
        needs_user_clarification=plan.needs_user_clarification,
        clarifying_question=plan.clarifying_question,
        final_output=plan.final_output,
    )


def _normalize_step_arguments(
    step: WorkflowPlanStep,
    scope: dict[str, Any],
) -> WorkflowPlanStep:
    if step.name == "resolve_activity_range":
        return _normalize_activity_range_step(step, scope)
    if step.name != "resolve_recent_activities":
        return step

    arguments = dict(step.arguments)
    if "limit" not in arguments and "count" not in arguments:
        limit = scope.get("limit") or scope.get("count")
        scope_type = str(scope.get("scope_type") or scope.get("type") or "").lower()
        if limit is not None:
            arguments["limit"] = limit
        elif scope_type in {"recent", "latest", "last"} or "最后" in str(scope.get("description") or ""):
            arguments["limit"] = 1

    if "sport_type" not in arguments:
        sport_type = scope.get("sport_type") or scope.get("activity_type")
        if sport_type:
            arguments["sport_type"] = sport_type

    if "order" not in arguments and "match" not in arguments:
        order = _order_from_scope(scope, step.reason)
        if order:
            arguments["order"] = order

    if arguments == step.arguments:
        return step
    return WorkflowPlanStep(
        name=step.name,
        reason=step.reason,
        arguments=arguments,
    )


def _normalize_activity_range_step(
    step: WorkflowPlanStep,
    scope: dict[str, Any],
) -> WorkflowPlanStep:
    # planner 有时把时间范围写在 activity_scope；executor 只读取 step.arguments。
    arguments = dict(step.arguments)
    for key in ("start_date", "end_date", "date_range", "time_range", "range_type", "relative_range"):
        if key not in arguments and scope.get(key) is not None:
            arguments[key] = scope[key]

    if "sport_type" not in arguments:
        sport_type = scope.get("sport_type") or scope.get("activity_type")
        if sport_type:
            arguments["sport_type"] = sport_type

    if arguments == step.arguments:
        return step
    return WorkflowPlanStep(
        name=step.name,
        reason=step.reason,
        arguments=arguments,
    )


def _order_from_scope(scope: dict[str, Any], reason: str = "") -> str | None:
    text = " ".join(
        str(scope.get(key) or "")
        for key in ("order", "match", "position", "scope_type", "type", "description")
    ).lower()
    text = f"{text} {reason}".lower()
    if any(token in text for token in ("first", "earliest", "oldest", "第一个", "最早", "最前")):
        return "earliest"
    if any(token in text for token in ("last", "latest", "newest", "最后", "最新", "最晚")):
        return "latest"
    return None


def _fallback_answer(execution) -> str:
    if execution.status == "validation_failed":
        return "计划校验失败:\n" + "\n".join(execution.validation.errors)
    if execution.status == "selection_failed" and execution.selection:
        return "步骤选择失败:\n" + "\n".join(execution.selection.errors)
    if execution.step_results:
        last = execution.step_results[-1]
        if last.status == "failed":
            return f"{last.step_name} 执行失败:{last.message or last.error}"
    return f"workflow status: {execution.status}"
