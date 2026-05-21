from __future__ import annotations

from pathlib import Path

import pytest

from agent.context import AgentContext
from agent.plan_schema import (
    WorkflowPlan,
    WorkflowPlanStep,
    available_workflow_steps,
    available_workflow_steps_catalog,
    get_workflow_step,
    workflow_steps_by_category,
)
from agent.planner import build_planner_payload, parse_workflow_plan_text, plan_initial_workflow


def test_available_workflow_step_names_are_unique():
    steps = available_workflow_steps()
    names = [step.name for step in steps]

    assert len(names) == len(set(names))


def test_key_workflow_step_flags_are_declared():
    single_activity = get_workflow_step("analyze_single_activity")
    compare_activities = get_workflow_step("compare_activities")
    ensure_summaries = get_workflow_step("ensure_activity_summaries")
    sync_garmin = get_workflow_step("sync_garmin_activities")
    prepare_upload = get_workflow_step("prepare_strava_upload")
    confirm_upload = get_workflow_step("confirm_strava_upload")

    assert single_activity is not None
    assert single_activity.requires_current_fit is True
    assert single_activity.requires == ["current_fit_file"]
    assert single_activity.produces == ["activity_analysis"]
    assert single_activity.side_effect is False

    assert compare_activities is not None
    assert compare_activities.requires == ["selected_activities"]
    assert compare_activities.side_effect is False

    assert ensure_summaries is not None
    assert ensure_summaries.side_effect is True
    assert ensure_summaries.requires == ["selected_activities"]

    assert sync_garmin is not None
    assert sync_garmin.side_effect is True
    assert sync_garmin.idempotent is False
    assert sync_garmin.produces == ["synced_fit_files"]

    assert prepare_upload is not None
    assert prepare_upload.side_effect is False
    assert prepare_upload.requires_confirmation is False
    assert prepare_upload.requires == ["current_fit_file"]

    assert confirm_upload is not None
    assert confirm_upload.side_effect is True
    assert confirm_upload.requires_confirmation is True
    assert confirm_upload.idempotent is False


def test_steps_can_be_filtered_by_category():
    activity_resolution_steps = {step.name for step in workflow_steps_by_category("activity_resolution")}

    assert {
        "resolve_current_activity",
        "resolve_activity_by_date",
        "resolve_activity_range",
        "resolve_recent_activities",
    }.issubset(activity_resolution_steps)


def test_workflow_plan_serializes_to_planner_json_shape():
    plan = WorkflowPlan(
        task_type="garmin_sync_and_analysis",
        steps=[
            WorkflowPlanStep(
                name="sync_garmin_activities",
                reason="用户要求同步最近两条 Garmin 活动",
                arguments={"count": 2},
            ),
            WorkflowPlanStep(
                name="analyze_new_fit_files",
                reason="用户要求同步后分析新下载的 FIT 文件",
            ),
        ],
        activity_scope={"type": "newly_synced"},
        allow_side_effects=True,
        final_output=["synced_files", "analysis_summary", "log_paths"],
    )

    assert plan.to_dict() == {
        "task_type": "garmin_sync_and_analysis",
        "steps": [
            {
                "name": "sync_garmin_activities",
                "reason": "用户要求同步最近两条 Garmin 活动",
                "arguments": {"count": 2},
            },
            {
                "name": "analyze_new_fit_files",
                "reason": "用户要求同步后分析新下载的 FIT 文件",
                "arguments": {},
            },
        ],
        "activity_scope": {"type": "newly_synced"},
        "allow_side_effects": True,
        "requires_confirmation": False,
        "needs_user_clarification": False,
        "clarifying_question": None,
        "final_output": ["synced_files", "analysis_summary", "log_paths"],
    }


def test_parse_workflow_plan_text_extracts_llm_json():
    text = """
    下面是计划:
    {
      "task_type": "weekly_training_advice",
      "steps": [
        {
          "name": "resolve_activity_range",
          "reason": "用户询问最近一周",
          "arguments": {"days": 7}
        },
        {
          "name": "generate_training_advice",
          "reason": "用户询问明天怎么练",
          "arguments": {}
        }
      ],
      "activity_scope": {"type": "recent_range", "days": 7},
      "allow_side_effects": false,
      "requires_confirmation": false,
      "needs_user_clarification": false,
      "clarifying_question": null,
      "final_output": ["weekly_summary", "next_session_advice"]
    }
    """

    plan = parse_workflow_plan_text(text)

    assert plan.task_type == "weekly_training_advice"
    assert [step.name for step in plan.steps] == [
        "resolve_activity_range",
        "generate_training_advice",
    ]
    assert plan.steps[0].arguments == {"days": 7}
    assert plan.activity_scope == {"type": "recent_range", "days": 7}
    assert plan.allow_side_effects is False
    assert plan.final_output == ["weekly_summary", "next_session_advice"]


def test_parse_workflow_plan_text_accepts_single_step_object():
    text = """
    {
      "task_type": "history_overview",
      "steps": {
        "name": "resolve_recent_activities",
        "reason": "获取所有历史活动",
        "arguments": {"limit": 0}
      },
      "activity_scope": {"type": "all_history"},
      "allow_side_effects": false,
      "requires_confirmation": false,
      "needs_user_clarification": false,
      "clarifying_question": null,
      "final_output": ["range_summary"]
    }
    """

    plan = parse_workflow_plan_text(text)

    assert [step.name for step in plan.steps] == ["resolve_recent_activities"]
    assert plan.steps[0].arguments == {"limit": 0}


def test_build_planner_payload_contains_context_and_coarse_steps_only():
    context = AgentContext(
        session_id="workflow_agent_test",
        current_fit_file=Path("/tmp/activity.fit"),
        current_activity_key="activity-1",
        history_enabled=True,
        pending_action={"type": "upload_preview"},
    )

    payload = build_planner_payload("帮我看看最近一周训练情况，明天怎么练", context)
    step_names = {step["name"] for step in payload["available_steps"]}
    serialized_catalog = str(available_workflow_steps_catalog())

    assert payload["user_message"] == "帮我看看最近一周训练情况，明天怎么练"
    assert payload["context"]["current_fit_file"] == "/tmp/activity.fit"
    assert payload["context"]["current_activity_key"] == "activity-1"
    assert payload["context"]["pending_action"] == {"type": "upload_preview"}
    assert "resolve_activity_range" in step_names
    assert "compare_activities" in step_names
    assert "ensure_activity_summaries" in step_names
    assert "generate_training_advice" in step_names
    assert "get_activity_summary" not in step_names
    assert "upload_to_strava" not in serialized_catalog
    assert "所有历史活动/全部历史活动" in payload["instruction"]
    assert "ensure_activity_summaries" in payload["instruction"]
    assert "arguments.force=true" in payload["instruction"]
    assert "只有明确比较/对比/差异" in payload["instruction"]


def test_planner_catalog_guides_reanalysis_away_from_comparison():
    """固定 planner 语言:重新分析是刷新 summary,不是默认横向对比。"""
    ensure_summaries = get_workflow_step("ensure_activity_summaries")
    compare_activities = get_workflow_step("compare_activities")
    summarize_range = get_workflow_step("summarize_activity_range")

    assert ensure_summaries is not None
    assert "重新分析" in ensure_summaries.description
    assert "force=true" in ensure_summaries.description

    assert compare_activities is not None
    assert "仅当用户明确要求比较" in compare_activities.description

    assert summarize_range is not None
    assert "最近 3 次活动概览" in summarize_range.description


def test_plan_initial_workflow_calls_llm_and_returns_plan_json():
    context = AgentContext(session_id="workflow_agent_test", history_enabled=True)

    class FakePlannerClient:
        def __init__(self):
            self.kwargs = None

        def create_message(self, **kwargs):
            self.kwargs = kwargs
            return {
                "model": "fake-model",
                "content": [
                    {
                        "type": "text",
                        "text": """
                        {
                          "task_type": "garmin_sync_and_analysis",
                          "steps": [
                            {
                              "name": "sync_garmin_activities",
                              "reason": "用户要求同步最近两条 Garmin 活动",
                              "arguments": {"count": 2}
                            },
                            {
                              "name": "analyze_new_fit_files",
                              "reason": "用户要求同步后分析",
                              "arguments": {}
                            }
                          ],
                          "activity_scope": {"type": "newly_synced"},
                          "allow_side_effects": true,
                          "requires_confirmation": false,
                          "needs_user_clarification": false,
                          "clarifying_question": null,
                          "final_output": ["synced_files", "analysis_summary"]
                        }
                        """,
                    }
                ],
            }

    client = FakePlannerClient()
    result = plan_initial_workflow("帮我同步最近两条 Garmin 活动并分析", context, client=client)

    assert result["plan"].task_type == "garmin_sync_and_analysis"
    assert result["plan_json"]["steps"][0]["name"] == "sync_garmin_activities"
    assert result["plan_json"]["steps"][0]["arguments"] == {"count": 2}
    assert result["payload"]["user_message"] == "帮我同步最近两条 Garmin 活动并分析"
    assert client.kwargs["temperature"] == 0
    assert "available_steps" in client.kwargs["user"]
    assert "sync_garmin_activities" in client.kwargs["user"]


def test_plan_initial_workflow_reports_empty_text_response():
    context = AgentContext(session_id="workflow_agent_test")

    class FakePlannerClient:
        def create_message(self, **kwargs):
            return {
                "model": "fake-model",
                "stop_reason": "max_tokens",
                "content": [{"type": "thinking", "thinking": "还在分析"}],
            }

    with pytest.raises(RuntimeError, match="no text content"):
        plan_initial_workflow("比较昨天的两次活动", context, client=FakePlannerClient())
