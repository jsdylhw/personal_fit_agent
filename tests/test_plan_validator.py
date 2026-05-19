from __future__ import annotations

from pathlib import Path

from agent.context import AgentContext
from agent.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.plan_validator import validate_workflow_plan


def _plan(*steps: WorkflowPlanStep, **kwargs) -> WorkflowPlan:
    return WorkflowPlan(
        task_type=kwargs.pop("task_type", "analysis"),
        steps=list(steps),
        **kwargs,
    )


def test_validator_accepts_resolution_before_single_activity_analysis():
    context = AgentContext(session_id="validator-test")
    plan = _plan(
        WorkflowPlanStep(
            name="resolve_activity_by_date",
            reason="用户指定了某一天的活动",
            arguments={"date": "2026-05-18"},
        ),
        WorkflowPlanStep(
            name="analyze_single_activity",
            reason="定位活动后分析单条 FIT",
        ),
        WorkflowPlanStep(name="final_response", reason="汇总分析结果"),
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is True
    assert result.errors == []


def test_validator_rejects_unknown_and_low_level_tool_steps():
    context = AgentContext(session_id="validator-test")
    plan = _plan(
        WorkflowPlanStep(name="get_activity_summary", reason="错误地暴露了底层工具"),
        WorkflowPlanStep(name="missing_step", reason="不存在的步骤"),
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is False
    assert "底层工具名" in result.errors[0]
    assert "missing_step" in result.errors[1]


def test_validator_rejects_side_effect_without_plan_permission():
    context = AgentContext(session_id="validator-test")
    plan = _plan(
        WorkflowPlanStep(
            name="sync_garmin_activities",
            reason="用户要求同步活动",
            arguments={"count": 2},
        ),
        allow_side_effects=False,
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is False
    assert any("allow_side_effects=false" in error for error in result.errors)


def test_validator_rejects_missing_activity_state():
    context = AgentContext(session_id="validator-test")
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="需要当前活动"),
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is False
    assert any("current_fit_file" in error for error in result.errors)


def test_validator_uses_existing_context_state():
    context = AgentContext(
        session_id="validator-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
        WorkflowPlanStep(name="final_response", reason="汇总分析结果"),
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is True


def test_validator_requires_existing_upload_preview_for_confirm_upload():
    context = AgentContext(
        session_id="validator-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="confirm_strava_upload", reason="用户确认上传"),
        allow_side_effects=True,
        requires_confirmation=True,
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is False
    assert any("pending_action" in error for error in result.errors)


def test_validator_accepts_confirm_upload_with_pending_preview():
    context = AgentContext(
        session_id="validator-test",
        current_fit_file=Path("/tmp/current.fit"),
        pending_action={"type": "upload_preview", "fit_path": "/tmp/current.fit"},
    )
    plan = _plan(
        WorkflowPlanStep(name="confirm_strava_upload", reason="用户确认上传"),
        allow_side_effects=True,
        requires_confirmation=True,
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is True


def test_validator_checks_simple_argument_bounds():
    context = AgentContext(session_id="validator-test")
    plan = _plan(
        WorkflowPlanStep(
            name="sync_garmin_activities",
            reason="同步过多活动",
            arguments={"count": 100},
        ),
        allow_side_effects=True,
    )

    result = validate_workflow_plan(plan, context)

    assert result.valid is False
    assert any("1 到 50" in error for error in result.errors)
