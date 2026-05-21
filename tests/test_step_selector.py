from __future__ import annotations

from agent.workflow.plan_schema import WorkflowPlan, WorkflowPlanStep, available_workflow_steps
from agent.workflow.step_selector import (
    FIT_DATA_TOOLS,
    get_step_execution_spec,
    select_workflow_steps,
    step_execution_catalog,
)


def test_every_workflow_step_has_execution_mapping():
    mapped_names = {item["step_name"] for item in step_execution_catalog()}
    schema_names = {step.name for step in available_workflow_steps()}

    assert schema_names == mapped_names


def test_selector_maps_plan_steps_to_execution_specs():
    plan = WorkflowPlan(
        task_type="single_activity_analysis",
        steps=[
            WorkflowPlanStep(
                name="resolve_activity_by_date",
                reason="用户指定日期",
                arguments={"date": "2026-05-18"},
            ),
            WorkflowPlanStep(
                name="analyze_single_activity",
                reason="分析定位到的活动",
            ),
        ],
    )

    result = select_workflow_steps(plan)

    assert result.valid is True
    assert result.errors == []
    assert [step.execution.executor_type for step in result.selected_steps] == [
        "activity_resolution",
        "subworkflow",
    ]
    assert result.selected_steps[1].execution.handler_name == "run_single_activity_react_analysis"
    assert result.selected_steps[1].execution.allowed_tools == FIT_DATA_TOOLS


def test_selector_keeps_schema_constraints_on_execution_spec():
    sync_spec = get_step_execution_spec("sync_garmin_activities")
    confirm_spec = get_step_execution_spec("confirm_strava_upload")
    analyze_spec = get_step_execution_spec("analyze_single_activity")

    assert sync_spec.side_effect is True
    assert sync_spec.idempotent is False
    assert sync_spec.produces == ("synced_fit_files",)

    assert confirm_spec.side_effect is True
    assert confirm_spec.requires_confirmation is True
    assert confirm_spec.requires == ("current_fit_file", "upload_preview")

    assert analyze_spec.side_effect is False
    assert analyze_spec.requires == ("current_fit_file",)
    assert analyze_spec.produces == ("activity_analysis",)


def test_selector_reports_unknown_step_without_throwing():
    plan = WorkflowPlan(
        task_type="bad_plan",
        steps=[
            WorkflowPlanStep(
                name="missing_step",
                reason="LLM 输出了不存在的步骤",
            ),
        ],
    )

    result = select_workflow_steps(plan)

    assert result.valid is False
    assert result.selected_steps == []
    assert "missing_step" in result.errors[0]


def test_selector_serializes_selected_steps():
    plan = WorkflowPlan(
        task_type="route_advice",
        steps=[
            WorkflowPlanStep(
                name="generate_route_advice",
                reason="用户希望获得路线建议",
                arguments={"goal": "endurance"},
            )
        ],
    )

    data = select_workflow_steps(plan).to_dict()

    assert data["valid"] is True
    assert data["selected_steps"][0]["plan_step"]["arguments"] == {"goal": "endurance"}
    assert data["selected_steps"][0]["execution"]["handler_name"] == "generate_route_advice"
