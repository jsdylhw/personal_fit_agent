from __future__ import annotations

import json
from pathlib import Path

from agent.context import AgentContext
from agent.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.workflow_executor import execute_workflow_plan


def _plan(*steps: WorkflowPlanStep, **kwargs) -> WorkflowPlan:
    return WorkflowPlan(
        task_type=kwargs.pop("task_type", "workflow_execution"),
        steps=list(steps),
        **kwargs,
    )


def test_executor_stops_before_selection_when_validation_fails():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(name="sync_garmin_activities", reason="有副作用但未允许"),
        allow_side_effects=False,
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "validation_failed"
    assert result.selection is None
    assert result.step_results == []


def test_executor_runs_activity_resolution_and_final_response():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
        current_activity_key="activity-1",
    )
    plan = _plan(
        WorkflowPlanStep(name="resolve_current_activity", reason="使用当前活动"),
        WorkflowPlanStep(name="final_response", reason="汇总结果"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert [step.step_name for step in result.step_results] == [
        "resolve_current_activity",
        "final_response",
    ]
    assert context.selected_activities[0]["activity_key"] == "activity-1"
    assert result.final_response == "resolve_current_activity 已完成."


def test_executor_runs_casual_chat_without_dedicated_handler():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(name="casual_chat", reason="普通问候"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].step_name == "casual_chat"
    assert "你好" in (result.final_response or "")


def test_executor_runs_user_clarification_without_dedicated_handler():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(
            name="ask_user_clarification",
            reason="缺少日期范围",
            arguments={"question": "你想分析哪一天的活动？"},
        )
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.final_response == "你想分析哪一天的活动？"


def test_executor_can_use_injected_step_handler():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
        WorkflowPlanStep(name="final_response", reason="汇总结果"),
    )
    calls = []

    def fake_single_activity_handler(step, context):
        calls.append((step.name, str(context.current_fit_file)))
        return {
            "step": step.name,
            "status": "completed",
            "answer": "活动分析完成",
        }

    result = execute_workflow_plan(
        plan,
        context,
        handlers={"run_single_activity_react_analysis": fake_single_activity_handler},
    )

    assert result.status == "completed"
    assert calls == [("analyze_single_activity", "/tmp/current.fit")]
    assert result.step_results[0].result["answer"] == "活动分析完成"
    assert result.final_response == "活动分析完成"


def test_executor_runs_single_activity_report_from_existing_summary(tmp_path):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_summary": {"start_time_local": "2026-05-18T21:00:00", "sport_type": "cycling"},
                "markdown_report": "# 最新骑行报告\n\n已有报告内容。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="executor-test",
        selected_activities=[{"activity_key": "a1", "summary_path": str(summary)}],
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="展示报告"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.final_response is not None
    assert result.final_response.startswith("# 最新骑行报告")


def test_executor_reports_unimplemented_default_handler():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "failed"
    assert result.step_results[0].status == "failed"
    assert result.step_results[0].error == "missing_activity_summary"


def test_executor_can_continue_after_step_error_when_requested():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
        WorkflowPlanStep(name="final_response", reason="汇总失败"),
    )

    result = execute_workflow_plan(plan, context, stop_on_error=False)

    assert result.status == "completed"
    assert result.step_results[0].status == "failed"
    assert result.step_results[1].step_name == "final_response"
    assert "执行失败" in (result.final_response or "")


def test_executor_runs_compare_activities_from_existing_summaries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    summary_dir = tmp_path / "data" / "summaries"
    summary_dir.mkdir(parents=True)
    first = summary_dir / "morning.summary.json"
    second = summary_dir / "evening.summary.json"
    first.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_summary": {"start_time_local": "2026-05-18T08:00:00", "sport_type": "cycling"},
                "history_entry": {
                    "summary_label": "晨间轻松骑",
                    "main_stimulus": "低强度耐力",
                    "training_load": "非常轻",
                    "duration_min": 26.9,
                    "distance_km": 9.38,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "activity_key": "a2",
                "fit_summary": {"start_time_local": "2026-05-18T21:00:00", "sport_type": "cycling"},
                "history_entry": {
                    "summary_label": "夜间恢复骑",
                    "main_stimulus": "有氧基础/恢复",
                    "training_load": "极低",
                    "duration_min": 42.8,
                    "distance_km": 15.79,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="executor-test",
        selected_activities=[
            {"activity_key": "a1", "summary_path": str(first)},
            {"activity_key": "a2", "summary_path": str(second)},
        ],
    )
    plan = _plan(
        WorkflowPlanStep(name="compare_activities", reason="对比已有报告"),
        WorkflowPlanStep(name="final_response", reason="输出对比结果"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].step_name == "compare_activities"
    assert result.step_results[0].result["result"]["count"] == 2
    assert result.final_response is not None
    assert "没有重新解析 FIT" in result.final_response


def test_executor_serializes_result():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
        current_activity_key="activity-1",
    )
    plan = _plan(
        WorkflowPlanStep(name="resolve_current_activity", reason="使用当前活动"),
    )

    data = execute_workflow_plan(plan, context).to_dict()

    assert data["status"] == "completed"
    assert data["validation"]["valid"] is True
    assert data["selection"]["valid"] is True
    assert data["step_results"][0]["step_name"] == "resolve_current_activity"
