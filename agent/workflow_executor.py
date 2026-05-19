"""顺序执行已经通过规划的 WorkflowPlan.

Executor 只接收结构化计划,不再让 LLM 自由选择底层工具.它会先调用
validator 和 selector,再按 selector 给出的执行映射逐步调度.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.activity_comparison import compare_selected_activities
from agent.activity_report import show_selected_activity_report
from agent.activity_resolution import execute_activity_resolution_step
from agent.context import AgentContext
from agent.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.plan_validator import PlanValidationResult, validate_workflow_plan
from agent.step_selector import (
    SelectedWorkflowStep,
    StepSelectionResult,
    select_workflow_steps,
)
from core.workflow_tools import (
    analyze_fit_file_tool,
    sync_garmin_activities_tool,
    upload_to_strava_tool,
)


StepHandler = Callable[[WorkflowPlanStep, AgentContext], dict[str, Any]]


@dataclass(frozen=True)
class WorkflowStepExecutionResult:
    index: int
    step_name: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    message: str | None = None
    execution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "step_name": self.step_name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "message": self.message,
            "execution": self.execution,
        }


@dataclass(frozen=True)
class WorkflowExecutionResult:
    status: str
    validation: PlanValidationResult
    selection: StepSelectionResult | None = None
    step_results: list[WorkflowStepExecutionResult] = field(default_factory=list)
    final_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "validation": self.validation.to_dict(),
            "selection": self.selection.to_dict() if self.selection else None,
            "step_results": [result.to_dict() for result in self.step_results],
            "final_response": self.final_response,
        }


def execute_workflow_plan(
    plan: WorkflowPlan,
    context: AgentContext,
    *,
    handlers: dict[str, StepHandler] | None = None,
    stop_on_error: bool = True,
) -> WorkflowExecutionResult:
    """按顺序执行 WorkflowPlan.

    Args:
        plan: planner 产出的粗粒度计划.
        context: 本次 workflow 共享状态.
        handlers: 测试或上层应用可注入 handler_name -> callable.
        stop_on_error: 单步失败后是否停止后续步骤.

    Returns:
        WorkflowExecutionResult:包含校验、选择和每步执行结果.
    """
    validation = validate_workflow_plan(plan, context)
    if not validation.valid:
        return WorkflowExecutionResult(status="validation_failed", validation=validation)

    selection = select_workflow_steps(plan)
    if not selection.valid:
        return WorkflowExecutionResult(
            status="selection_failed",
            validation=validation,
            selection=selection,
        )

    step_results: list[WorkflowStepExecutionResult] = []
    final_response: str | None = None
    for index, selected in enumerate(selection.selected_steps):
        step_result = _execute_selected_step(
            selected,
            context,
            index=index,
            handlers=handlers or {},
        )
        step_results.append(step_result)
        context.last_tool_result = step_result.to_dict()
        if step_result.result and step_result.result.get("answer"):
            final_response = str(step_result.result["answer"])
        if selected.execution.executor_type == "response" and step_result.result:
            final_response = str(step_result.result.get("answer") or "")
        if step_result.status == "failed" and stop_on_error:
            return WorkflowExecutionResult(
                status="failed",
                validation=validation,
                selection=selection,
                step_results=step_results,
                final_response=final_response,
            )

    return WorkflowExecutionResult(
        status="completed",
        validation=validation,
        selection=selection,
        step_results=step_results,
        final_response=final_response,
    )


def _execute_selected_step(
    selected: SelectedWorkflowStep,
    context: AgentContext,
    *,
    index: int,
    handlers: dict[str, StepHandler],
) -> WorkflowStepExecutionResult:
    step = selected.plan_step
    execution = selected.execution
    handler = handlers.get(execution.handler_name) or handlers.get(step.name)
    try:
        if handler:
            result = handler(step, context)
        else:
            result = _execute_default_handler(selected, context)
    except Exception as exc:
        return WorkflowStepExecutionResult(
            index=index,
            step_name=step.name,
            status="failed",
            error=type(exc).__name__,
            message=str(exc),
            execution=execution.to_dict(),
        )

    if result.get("error"):
        return WorkflowStepExecutionResult(
            index=index,
            step_name=step.name,
            status="failed",
            result=result,
            error=str(result.get("error")),
            message=str(result.get("message") or ""),
            execution=execution.to_dict(),
        )
    return WorkflowStepExecutionResult(
        index=index,
        step_name=step.name,
        status=str(result.get("status") or "completed"),
        result=result,
        execution=execution.to_dict(),
    )


def _execute_default_handler(
    selected: SelectedWorkflowStep,
    context: AgentContext,
) -> dict[str, Any]:
    step = selected.plan_step
    executor_type = selected.execution.executor_type

    if executor_type == "activity_resolution":
        return execute_activity_resolution_step(step, context)
    if executor_type == "response":
        return _build_final_response(context)
    if step.name == "casual_chat":
        return _execute_casual_chat(step)
    if step.name == "ask_user_clarification":
        return _execute_user_clarification(step)
    if step.name == "sync_garmin_activities":
        return _execute_sync_garmin(step)
    if step.name == "analyze_new_fit_files":
        return _execute_analyze_new_fit_files(context)
    if step.name == "generate_summary_file":
        return _execute_generate_summary_file(step, context)
    if step.name == "ensure_activity_summaries":
        return _execute_ensure_activity_summaries(step, context)
    if step.name == "prepare_strava_upload":
        return _execute_prepare_strava_upload(context)
    if step.name == "confirm_strava_upload":
        return _execute_confirm_strava_upload(context)
    if step.name == "compare_activities":
        return compare_selected_activities(step, context)
    if step.name == "analyze_single_activity":
        return show_selected_activity_report(step, context)
    if executor_type in {"conversation", "analysis", "coaching", "subworkflow"}:
        return {
            "error": "handler_not_implemented",
            "message": f"{step.name} needs a dedicated handler before executor can run it.",
        }
    return {
        "error": "unsupported_executor_type",
        "message": f"Unsupported executor_type: {executor_type}",
    }


def _execute_sync_garmin(step: WorkflowPlanStep) -> dict[str, Any]:
    count = int(step.arguments.get("count") or 5)
    result = sync_garmin_activities_tool(count=count)
    return {"step": step.name, "result": result}


def _execute_casual_chat(step: WorkflowPlanStep) -> dict[str, Any]:
    answer = str(
        step.arguments.get("answer")
        or step.arguments.get("message")
        or "你好，我在。可以帮你分析活动、比较报告、规划训练，或者处理 Garmin / Strava 相关流程。"
    )
    return {
        "step": step.name,
        "status": "completed",
        "answer": answer,
    }


def _execute_user_clarification(step: WorkflowPlanStep) -> dict[str, Any]:
    question = str(
        step.arguments.get("question")
        or step.arguments.get("clarifying_question")
        or "我需要再确认一下你的活动范围或目标。"
    )
    return {
        "step": step.name,
        "status": "completed",
        "answer": question,
    }


def _execute_analyze_new_fit_files(context: AgentContext) -> dict[str, Any]:
    previous = (context.last_tool_result or {}).get("result") or {}
    sync_result = previous.get("result") if isinstance(previous.get("result"), dict) else previous
    items = sync_result.get("downloaded_items") or []
    fit_paths = _fit_paths_from_items(items)
    analyses = [
        analyze_fit_file_tool(str(path), force=False)
        for path in fit_paths
    ]
    return {
        "step": "analyze_new_fit_files",
        "result": {
            "count": len(analyses),
            "analyses": analyses,
        },
    }


def _execute_generate_summary_file(
    step: WorkflowPlanStep,
    context: AgentContext,
) -> dict[str, Any]:
    fit_path = _current_fit_path(context)
    result = analyze_fit_file_tool(str(fit_path), force=bool(step.arguments.get("force")))
    if result.get("fit_path"):
        context.current_fit_file = Path(str(result["fit_path"])).expanduser()
    return {"step": step.name, "result": result}


def _execute_ensure_activity_summaries(
    step: WorkflowPlanStep,
    context: AgentContext,
) -> dict[str, Any]:
    force = bool(step.arguments.get("force"))
    analyses = []
    for activity in context.selected_activities:
        fit_path = activity.get("fit_path") if isinstance(activity, dict) else None
        if not fit_path:
            continue
        summary_path = activity.get("summary_path") if isinstance(activity, dict) else None
        if summary_path and Path(str(summary_path)).expanduser().exists() and not force:
            analyses.append({
                "fit_path": str(fit_path),
                "summary_path": str(summary_path),
                "status": "skipped_existing_summary",
            })
            continue
        analyses.append(analyze_fit_file_tool(str(fit_path), force=force))
    return {
        "step": step.name,
        "result": {
            "count": len(analyses),
            "analyses": analyses,
        },
    }


def _execute_prepare_strava_upload(context: AgentContext) -> dict[str, Any]:
    fit_path = _current_fit_path(context)
    result = upload_to_strava_tool(str(fit_path), confirmed=False)
    if result.get("action_required") == "confirm_upload":
        context.pending_action = {
            "type": "upload_preview",
            "fit_path": str(fit_path),
            "preview": result.get("preview"),
        }
    return {"step": "prepare_strava_upload", "result": result}


def _execute_confirm_strava_upload(context: AgentContext) -> dict[str, Any]:
    fit_path = _current_fit_path(context)
    result = upload_to_strava_tool(str(fit_path), confirmed=True)
    if result.get("status") == "uploaded":
        context.pending_action = None
    return {"step": "confirm_strava_upload", "result": result}


def _build_final_response(context: AgentContext) -> dict[str, Any]:
    last = context.last_tool_result or {}
    return {
        "step": "final_response",
        "answer": _summarize_last_result(last),
        "last_tool_result": last,
    }


def _current_fit_path(context: AgentContext) -> Path:
    if not context.current_fit_file:
        raise ValueError("current_fit_file is required")
    return Path(context.current_fit_file).expanduser()


def _fit_paths_from_items(items: list[Any]) -> list[Path]:
    paths: list[Path] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for path in item.get("paths") or []:
            paths.append(Path(str(path)).expanduser())
    return paths


def _summarize_last_result(last: dict[str, Any]) -> str:
    step_name = last.get("step_name") or last.get("step") or "上一步"
    if last.get("status") == "failed":
        return f"{step_name} 执行失败:{last.get('message') or last.get('error')}"
    result = last.get("result") if isinstance(last.get("result"), dict) else {}
    if result.get("answer"):
        return str(result["answer"])
    return f"{step_name} 已完成."
