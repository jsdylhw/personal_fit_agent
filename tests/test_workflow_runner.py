from __future__ import annotations

import json

from agent.context import AgentContext
from agent.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.workflow_executor import execute_workflow_plan
from agent.workflow_runner import normalize_workflow_plan


def test_planned_workflow_executor_path_compares_existing_summaries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    summary_dir = tmp_path / "data" / "summaries"
    summary_dir.mkdir(parents=True)
    first = summary_dir / "first.summary.json"
    second = summary_dir / "second.summary.json"
    _write_summary(first, key="a1", label="晨间轻松骑", distance_km=9.38, duration_min=26.9)
    _write_summary(second, key="a2", label="夜间恢复骑", distance_km=15.79, duration_min=42.8)

    context = AgentContext(
        session_id="runner-test",
        selected_activities=[
            {"activity_key": "a1", "summary_path": str(first)},
            {"activity_key": "a2", "summary_path": str(second)},
        ],
    )
    plan = WorkflowPlan(
        task_type="comparison",
        steps=[
            WorkflowPlanStep(name="compare_activities", reason="对比已有报告"),
            WorkflowPlanStep(name="final_response", reason="输出最终回答"),
        ],
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.final_response is not None
    assert "没有重新解析 FIT" in result.final_response


def test_normalize_workflow_plan_moves_recent_scope_to_step_arguments():
    plan = WorkflowPlan(
        task_type="activity_report",
        steps=[
            WorkflowPlanStep(
                name="resolve_recent_activities",
                reason="定位最后一次骑行",
            ),
            WorkflowPlanStep(
                name="analyze_single_activity",
                reason="展示报告",
            ),
        ],
        activity_scope={
            "scope_type": "recent",
            "limit": 1,
            "activity_type": "cycling",
        },
    )

    normalized = normalize_workflow_plan(plan)

    assert normalized.steps[0].arguments == {
        "limit": 1,
        "order": "latest",
        "sport_type": "cycling",
    }


def test_normalize_workflow_plan_moves_first_activity_scope_to_order():
    plan = WorkflowPlan(
        task_type="activity_report",
        steps=[
            WorkflowPlanStep(
                name="resolve_recent_activities",
                reason="定位第一个活动",
            ),
            WorkflowPlanStep(
                name="analyze_single_activity",
                reason="展示报告",
            ),
        ],
        activity_scope={
            "scope_type": "recent",
            "limit": 1,
            "description": "第一个活动,也就是最早的活动",
        },
    )

    normalized = normalize_workflow_plan(plan)

    assert normalized.steps[0].arguments == {
        "limit": 1,
        "order": "earliest",
    }


def _write_summary(path, *, key: str, label: str, distance_km: float, duration_min: float) -> None:
    path.write_text(
        json.dumps(
            {
                "activity_key": key,
                "fit_summary": {
                    "sport_type": "cycling",
                    "start_time_local": f"2026-05-18T0{1 if key == 'a1' else 2}:00:00",
                },
                "history_entry": {
                    "summary_label": label,
                    "main_stimulus": "低强度耐力",
                    "training_load": "极低",
                    "duration_min": duration_min,
                    "distance_km": distance_km,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
