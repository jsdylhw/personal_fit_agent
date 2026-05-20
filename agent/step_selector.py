"""把粗粒度 workflow step 映射到后续执行入口.

Selector 不执行任何步骤,只回答"这个业务步骤应该交给谁执行,允许使用
哪些底层工具或子流程".这样 executor 后续可以按这里的结果做严格调度.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.plan_schema import WorkflowPlan, WorkflowPlanStep, get_workflow_step


FIT_DATA_TOOLS = (
    "get_activity_overview",
    "get_activity_summary",
    "scan_activity_segments",
    "get_time_intervals",
    "get_distance_intervals",
    "get_history",
)

ACTIVITY_INDEX_TOOLS = (
    "list_activities",
    "resolve_activity",
    "get_activities_in_range",
)


@dataclass(frozen=True)
class StepExecutionSpec:
    step_name: str
    executor_type: str
    handler_name: str
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    requires: tuple[str, ...] = field(default_factory=tuple)
    produces: tuple[str, ...] = field(default_factory=tuple)
    side_effect: bool = False
    requires_confirmation: bool = False
    idempotent: bool = True
    max_retries: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "executor_type": self.executor_type,
            "handler_name": self.handler_name,
            "allowed_tools": list(self.allowed_tools),
            "requires": list(self.requires),
            "produces": list(self.produces),
            "side_effect": self.side_effect,
            "requires_confirmation": self.requires_confirmation,
            "idempotent": self.idempotent,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True)
class SelectedWorkflowStep:
    plan_step: WorkflowPlanStep
    execution: StepExecutionSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_step": self.plan_step.to_dict(),
            "execution": self.execution.to_dict(),
        }


@dataclass(frozen=True)
class StepSelectionResult:
    selected_steps: list[SelectedWorkflowStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "selected_steps": [step.to_dict() for step in self.selected_steps],
        }


_BASE_EXECUTION_SPECS: dict[str, StepExecutionSpec] = {
    "casual_chat": StepExecutionSpec(
        step_name="casual_chat",
        executor_type="conversation",
        handler_name="build_casual_chat_response",
    ),
    "ask_user_clarification": StepExecutionSpec(
        step_name="ask_user_clarification",
        executor_type="conversation",
        handler_name="build_clarifying_question",
    ),
    "resolve_current_activity": StepExecutionSpec(
        step_name="resolve_current_activity",
        executor_type="activity_resolution",
        handler_name="execute_activity_resolution_step",
        allowed_tools=ACTIVITY_INDEX_TOOLS,
    ),
    "resolve_activity_by_date": StepExecutionSpec(
        step_name="resolve_activity_by_date",
        executor_type="activity_resolution",
        handler_name="execute_activity_resolution_step",
        allowed_tools=ACTIVITY_INDEX_TOOLS,
    ),
    "resolve_activity_range": StepExecutionSpec(
        step_name="resolve_activity_range",
        executor_type="activity_resolution",
        handler_name="execute_activity_resolution_step",
        allowed_tools=ACTIVITY_INDEX_TOOLS,
    ),
    "resolve_recent_activities": StepExecutionSpec(
        step_name="resolve_recent_activities",
        executor_type="activity_resolution",
        handler_name="execute_activity_resolution_step",
        allowed_tools=ACTIVITY_INDEX_TOOLS,
    ),
    "analyze_single_activity": StepExecutionSpec(
        step_name="analyze_single_activity",
        executor_type="subworkflow",
        handler_name="run_single_activity_react_analysis",
        allowed_tools=FIT_DATA_TOOLS,
    ),
    "summarize_activity_range": StepExecutionSpec(
        step_name="summarize_activity_range",
        executor_type="analysis",
        handler_name="summarize_activity_range",
        allowed_tools=("read_activity_summary",),
    ),
    "compare_with_history": StepExecutionSpec(
        step_name="compare_with_history",
        executor_type="analysis",
        handler_name="compare_with_history",
        allowed_tools=("read_activity_summary", "get_history"),
    ),
    "compare_activities": StepExecutionSpec(
        step_name="compare_activities",
        executor_type="analysis",
        handler_name="compare_selected_activities",
        allowed_tools=("read_activity_summary",),
    ),
    "generate_training_advice": StepExecutionSpec(
        step_name="generate_training_advice",
        executor_type="coaching",
        handler_name="generate_training_advice",
        allowed_tools=("read_activity_summary", "get_history"),
    ),
    "generate_route_advice": StepExecutionSpec(
        step_name="generate_route_advice",
        executor_type="coaching",
        handler_name="generate_route_advice",
        allowed_tools=("read_activity_summary", "get_history"),
    ),
    "sync_garmin_activities": StepExecutionSpec(
        step_name="sync_garmin_activities",
        executor_type="tool",
        handler_name="sync_garmin_activities_tool",
        allowed_tools=("sync_garmin_activities",),
    ),
    "analyze_new_fit_files": StepExecutionSpec(
        step_name="analyze_new_fit_files",
        executor_type="tool",
        handler_name="analyze_fit_file_tool",
        allowed_tools=("analyze_fit_file",),
    ),
    "generate_summary_file": StepExecutionSpec(
        step_name="generate_summary_file",
        executor_type="tool",
        handler_name="analyze_fit_file_tool",
        allowed_tools=("analyze_fit_file",),
    ),
    "ensure_activity_summaries": StepExecutionSpec(
        step_name="ensure_activity_summaries",
        executor_type="tool",
        handler_name="ensure_activity_summaries",
        allowed_tools=("analyze_fit_file",),
    ),
    "prepare_strava_upload": StepExecutionSpec(
        step_name="prepare_strava_upload",
        executor_type="tool",
        handler_name="upload_to_strava_preview",
        allowed_tools=("upload_to_strava",),
    ),
    "confirm_strava_upload": StepExecutionSpec(
        step_name="confirm_strava_upload",
        executor_type="tool",
        handler_name="upload_to_strava_confirmed",
        allowed_tools=("upload_to_strava",),
    ),
    "final_response": StepExecutionSpec(
        step_name="final_response",
        executor_type="response",
        handler_name="build_final_response",
    ),
}


def step_execution_catalog() -> list[dict[str, Any]]:
    """返回所有 workflow step 的执行映射目录."""
    return [get_step_execution_spec(name).to_dict() for name in sorted(_BASE_EXECUTION_SPECS)]


def get_step_execution_spec(step_name: str) -> StepExecutionSpec:
    """获取单个 step 的执行映射,并合并 plan_schema 中的约束元数据."""
    execution = _BASE_EXECUTION_SPECS[step_name]
    workflow_spec = get_workflow_step(step_name)
    if workflow_spec is None:
        return execution
    return StepExecutionSpec(
        step_name=execution.step_name,
        executor_type=execution.executor_type,
        handler_name=execution.handler_name,
        allowed_tools=execution.allowed_tools,
        requires=tuple(workflow_spec.requires),
        produces=tuple(workflow_spec.produces),
        side_effect=workflow_spec.side_effect,
        requires_confirmation=workflow_spec.requires_confirmation,
        idempotent=workflow_spec.idempotent,
        max_retries=workflow_spec.max_retries,
    )


def select_workflow_steps(plan: WorkflowPlan) -> StepSelectionResult:
    """为 WorkflowPlan 中的每个 step 选择执行映射."""
    selected_steps: list[SelectedWorkflowStep] = []
    errors: list[str] = []

    for index, plan_step in enumerate(plan.steps):
        workflow_spec = get_workflow_step(plan_step.name)
        if workflow_spec is None:
            errors.append(f"step[{index}] {plan_step.name!r} 不在 WORKFLOW_STEP_SPECS 中")
            continue
        if plan_step.name not in _BASE_EXECUTION_SPECS:
            errors.append(f"step[{index}] {plan_step.name!r} 没有 StepExecutionSpec 映射")
            continue
        selected_steps.append(
            SelectedWorkflowStep(
                plan_step=plan_step,
                execution=get_step_execution_spec(plan_step.name),
            )
        )

    return StepSelectionResult(selected_steps=selected_steps, errors=errors)
