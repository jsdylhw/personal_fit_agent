"""WorkflowPlan 的程序侧校验.

Planner 只负责理解用户意图并写出业务步骤.真正执行前,这里负责检查
步骤是否存在、依赖是否满足、以及副作用和确认逻辑是否安全.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.context import AgentContext
from agent.workflow.plan_schema import WorkflowPlan, get_workflow_step
from agent.workflow.handlers.ops import MAX_SYNC_COUNT


LOW_LEVEL_TOOL_NAMES = {
    # 单活动分析子流程内部工具,不应该出现在外层 workflow plan 中.
    "get_activity_overview",
    "get_activity_summary",
    "scan_activity_segments",
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

    has_resolved = "selected_activities" in available_state or "current_fit_file" in available_state

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

        # 副作用步骤必须前有活动定位
        if spec.side_effect and not has_resolved and not _is_side_effect_without_activity(step.name):
            warnings.append(
                f"step[{index}] {step.name!r} 有副作用,但前面没有活动定位步骤"
            )
        if spec.category == "activity_resolution":
            has_resolved = True

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

    return PlanValidationResult(errors=errors, warnings=warnings)


def _is_side_effect_without_activity(step_name: str) -> bool:
    """sync_garmin_activities 可以在还没有本地活动时执行."""
    return step_name == "sync_garmin_activities"


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
    return state


def _has_step(plan: WorkflowPlan, step_name: str) -> bool:
    return any(step.name == step_name for step in plan.steps)


def _validate_step_arguments(
    name: str,
    arguments: dict[str, Any],
    index: int,
    errors: list[str],
    warnings: list[str],
) -> None:
    if name == "sync_garmin_activities":
        _validate_positive_int_argument(
            arguments,
            key="count",
            step_name=name,
            index=index,
            max_value=MAX_SYNC_COUNT,
            errors=errors,
        )

    if name == "resolve_recent_activities":
        # planner 有时会用 count,有时会用 limit;两者都进入执行层,所以都要校验。
        _validate_positive_int_argument(
            arguments,
            key="count",
            step_name=name,
            index=index,
            max_value=50,
            errors=errors,
        )
        _validate_positive_int_argument(
            arguments,
            key="limit",
            step_name=name,
            index=index,
            max_value=50,
            errors=errors,
        )

    if name == "resolve_activity_range":
        days = arguments.get("days")
        if days is not None and (not isinstance(days, int) or days <= 0 or days > 366):
            errors.append(f"step[{index}] resolve_activity_range.days 必须是 1 到 366 的整数")

    if name == "ask_user_clarification" and not arguments:
        warnings.append(f"step[{index}] ask_user_clarification 最好带上 question 参数")


def _validate_positive_int_argument(
    arguments: dict[str, Any],
    *,
    key: str,
    step_name: str,
    index: int,
    max_value: int,
    errors: list[str],
) -> None:
    value = arguments.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > max_value:
        errors.append(f"step[{index}] {step_name}.{key} 必须是 1 到 {max_value} 的整数")
