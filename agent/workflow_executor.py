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
    if step.name == "summarize_activity_range":
        return _execute_summarize_activity_range(step, context)
    if step.name == "compare_activities":
        return compare_selected_activities(step, context)
    if step.name == "analyze_single_activity":
        empty_answer = _empty_activity_resolution_answer(
            str((context.last_tool_result or {}).get("step_name") or ""),
            (context.last_tool_result or {}).get("result") if isinstance((context.last_tool_result or {}).get("result"), dict) else {},
        )
        if empty_answer:
            return {
                "step": step.name,
                "status": "completed",
                "answer": empty_answer,
                "result": {
                    "schema_version": "activity_analysis_skipped.v1",
                    "reason": "empty_activity_resolution",
                },
            }
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


def _execute_summarize_activity_range(
    step: WorkflowPlanStep,
    context: AgentContext,
) -> dict[str, Any]:
    # 范围汇总只做索引层面的轻量概览，避免为“上个月有哪些活动”触发逐个 FIT 深度分析。
    activities = [
        activity
        for activity in context.selected_activities
        if isinstance(activity, dict)
    ]
    scope = context.selected_activity_range or {}
    if not activities:
        answer = _empty_range_answer(scope)
        return {
            "step": step.name,
            "status": "completed",
            "answer": answer,
            "result": {
                "schema_version": "activity_range_summary.v1",
                "count": 0,
                "scope": scope,
                "activities": [],
            },
        }

    normalized = [_compact_range_activity(activity) for activity in activities]
    total_distance = round(sum(float(item.get("distance_km") or 0) for item in normalized), 2)
    total_duration = round(sum(float(item.get("duration_min") or 0) for item in normalized), 1)
    result = {
        "schema_version": "activity_range_summary.v1",
        "count": len(normalized),
        "scope": scope,
        "totals": {
            "distance_km": total_distance,
            "duration_min": total_duration,
        },
        "activities": normalized,
    }
    return {
        "step": step.name,
        "status": "completed",
        "answer": _format_range_summary_answer(result),
        "result": result,
    }


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
    empty_answer = _empty_activity_resolution_answer(step_name, result)
    if empty_answer:
        return empty_answer
    return f"{step_name} 已完成."


def _compact_range_activity(activity: dict[str, Any]) -> dict[str, Any]:
    # 输出给 final_response 和日志的字段保持紧凑，避免把索引里的完整路径等细节塞进回答。
    return {
        "activity_index": activity.get("activity_index"),
        "activity_key": activity.get("activity_key"),
        "file_name": activity.get("file_name"),
        "start_time_local": activity.get("start_time_local"),
        "date_local": activity.get("date_local"),
        "sport_type": activity.get("sport_type"),
        "duration_min": activity.get("duration_min"),
        "distance_km": activity.get("distance_km"),
        "has_summary": activity.get("has_summary"),
        "summary_label": activity.get("summary_label"),
        "main_stimulus": activity.get("main_stimulus"),
        "training_load": activity.get("training_load"),
    }


def _format_range_summary_answer(summary: dict[str, Any]) -> str:
    scope = summary.get("scope") if isinstance(summary.get("scope"), dict) else {}
    title = _range_title(scope)
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    lines = [
        f"{title}找到 {summary.get('count')} 条已索引活动。",
        f"总量: {totals.get('distance_km', 0)} km, {totals.get('duration_min', 0)} 分钟。",
    ]
    for activity in summary.get("activities") or []:
        label = activity.get("summary_label") or activity.get("file_name") or activity.get("activity_key")
        lines.append(
            f"- #{activity.get('activity_index') or '?'} "
            f"{activity.get('start_time_local') or activity.get('date_local') or '未知时间'}: "
            f"{label}, {activity.get('distance_km') or 0} km / {activity.get('duration_min') or 0} 分钟"
        )
    return "\n".join(lines)


def _empty_range_answer(scope: dict[str, Any]) -> str:
    return f"{_range_title(scope)}没有找到已索引的活动。你可以先重建索引，或同步 Garmin 活动后再试。"


def _range_title(scope: dict[str, Any]) -> str:
    start = scope.get("start_date")
    end = scope.get("end_date")
    if start and end:
        return f"{start} 到 {end} "
    return ""


def _empty_activity_resolution_answer(step_name: str, result: dict[str, Any]) -> str | None:
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(payload, dict):
        return None

    matched_count = payload.get("matched_count")
    count = payload.get("count")
    is_empty = matched_count == 0 or count == 0
    if not is_empty:
        return None

    if step_name == "resolve_activity_range":
        start = payload.get("start_date")
        end = payload.get("end_date")
        if start and end:
            return f"{start} 到 {end} 没有找到已索引的活动。"
        return "这个时间范围内没有找到已索引的活动。"
    if step_name == "resolve_recent_activities":
        return "没有找到已索引的最近活动。你可以先重建索引或同步 Garmin 活动。"
    return "没有找到符合条件的活动。你可以先重建索引，或确认日期、序号、活动名称是否正确。"
