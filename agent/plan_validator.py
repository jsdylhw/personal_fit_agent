"""WorkflowPlan 的程序侧校验.

Planner 只负责理解用户意图并写出业务步骤.真正执行前,这里负责检查
步骤是否存在、依赖是否满足、以及副作用和确认逻辑是否安全.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.context import AgentContext
from agent.plan_schema import WorkflowPlan, get_workflow_step


LOW_LEVEL_TOOL_NAMES = {
    # 单活动分析子流程内部工具,不应该出现在外层 workflow plan 中.
    "get_activity_overview",
    "get_activity_summary",
    "get_time_intervals",
    "get_distance_intervals",
    "get_history",
    "analyze_fit_file",
    "upload_to_strava",
}


@dataclass(frozen=True)
class PlanValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_workflow_plan(
    plan: WorkflowPlan,
    context: AgentContext,
) -> PlanValidationResult:
    """校验 WorkflowPlan 是否适合进入 selector/executor."""
    errors: list[str] = []
    warnings: list[str] = []
    available_state = _context_state(context)
    produced_state: set[str] = set()

    if plan.needs_user_clarification and not _has_step(plan, "ask_user_clarification"):
        errors.append(
            "plan.needs_user_clarification=true 时必须包含 ask_user_clarification 步骤"
        )

    if not plan.steps:
        errors.append("workflow plan must contain at least one step")

    for index, step in enumerate(plan.steps):
        if step.name in LOW_LEVEL_TOOL_NAMES:
            errors.append(
                f"step[{index}] {step.name!r} 是底层工具名,planner 只能选择粗粒度 workflow step"
            )
            continue

        spec = get_workflow_step(step.name)
        if spec is None:
            errors.append(f"step[{index}] {step.name!r} 不在 WORKFLOW_STEP_SPECS 中")
            continue

        if spec.side_effect and not plan.allow_side_effects:
            errors.append(
                f"step[{index}] {step.name!r} 有副作用,但 plan.allow_side_effects=false"
            )

        if spec.requires_confirmation and not plan.requires_confirmation:
            errors.append(
                f"step[{index}] {step.name!r} 需要用户确认,但 plan.requires_confirmation=false"
            )

        missing = [
            requirement
            for requirement in spec.requires
            if not _requirement_satisfied(requirement, available_state, produced_state)
        ]
        if missing:
            errors.append(
                f"step[{index}] {step.name!r} 缺少前置状态: {', '.join(missing)}"
            )

        _validate_step_arguments(step.name, step.arguments, index, errors, warnings)
        produced_state.update(spec.produces)

    _validate_confirmation_flow(plan, context, errors)
    _validate_final_response(plan, warnings)
    return PlanValidationResult(errors=errors, warnings=warnings)


def _requirement_satisfied(
    requirement: str,
    available_state: set[str],
    produced_state: set[str],
) -> bool:
    if requirement in available_state or requirement in produced_state:
        return True
    if requirement == "current_fit_file":
        return "selected_activities" in available_state or "selected_activities" in produced_state
    return False


def _context_state(context: AgentContext) -> set[str]:
    state: set[str] = set()
    if context.current_fit_file:
        state.add("current_fit_file")
    if context.selected_activities:
        state.add("selected_activities")
    if context.selected_activity_range:
        state.add("activity_range")
    if context.current_summary_path:
        state.add("activity_summary")
    if context.pending_action:
        state.add("pending_action")
        if context.pending_action.get("type") in {"upload_preview", "strava_upload_preview"}:
            state.add("upload_preview")
    return state


def _has_step(plan: WorkflowPlan, step_name: str) -> bool:
    return any(step.name == step_name for step in plan.steps)


def _validate_confirmation_flow(
    plan: WorkflowPlan,
    context: AgentContext,
    errors: list[str],
) -> None:
    if not _has_step(plan, "confirm_strava_upload"):
        return

    # 上传确认必须来自上一轮 prepare 的 pending_action,不能在同一轮规划里自造确认.
    if not context.pending_action:
        errors.append("confirm_strava_upload 需要已有 pending_action 上传预览")
    elif context.pending_action.get("type") not in {"upload_preview", "strava_upload_preview"}:
        errors.append("confirm_strava_upload 的 pending_action 不是上传预览")


def _validate_final_response(plan: WorkflowPlan, warnings: list[str]) -> None:
    if not _has_step(plan, "final_response"):
        warnings.append("计划没有 final_response,后续 executor 需要自行组织最终回答")
        return

    first_step = plan.steps[0].name if plan.steps else None
    if first_step == "final_response" and plan.task_type not in {"casual_chat", "unknown"}:
        warnings.append("final_response 是第一个步骤,请确认前面不需要分析或操作步骤")


def _validate_step_arguments(
    name: str,
    arguments: dict[str, Any],
    index: int,
    errors: list[str],
    warnings: list[str],
) -> None:
    if name == "sync_garmin_activities":
        count = arguments.get("count")
        if count is not None and (not isinstance(count, int) or count <= 0 or count > 50):
            errors.append(f"step[{index}] sync_garmin_activities.count 必须是 1 到 50 的整数")

    if name == "resolve_recent_activities":
        count = arguments.get("count")
        if count is not None and (not isinstance(count, int) or count <= 0 or count > 50):
            errors.append(f"step[{index}] resolve_recent_activities.count 必须是 1 到 50 的整数")

    if name == "resolve_activity_range":
        days = arguments.get("days")
        if days is not None and (not isinstance(days, int) or days <= 0 or days > 366):
            errors.append(f"step[{index}] resolve_activity_range.days 必须是 1 到 366 的整数")

    if name == "ask_user_clarification" and not arguments:
        warnings.append(f"step[{index}] ask_user_clarification 最好带上 question 参数")
