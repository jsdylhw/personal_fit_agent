from __future__ import annotations

import json

from agent.context import AgentContext
from agent.workflow.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.chat_logger import write_workflow_markdown_log
from agent.workflow.executor import execute_workflow_plan
from agent.workflow.runner import normalize_workflow_plan


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
        ],
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.final_response is not None
    assert "没有重新解析 FIT" in result.final_response


def test_write_workflow_markdown_log_is_readable_and_md_only(tmp_path):
    path = write_workflow_markdown_log(
        "planned_workflow_test",
        user_message="分析所有历史活动",
        planner_plan={
            "task_type": "history_overview",
            "steps": [
                {"name": "resolve_activity_range", "reason": "定位所有活动", "arguments": {"range": "all"}},
                {"name": "final_response", "reason": "组织最终回答"},
            ],
        },
        normalized_plan={
            "task_type": "history_overview",
            "steps": [
                {"name": "resolve_activity_range", "reason": "定位所有活动", "arguments": {"range": "all"}},
                {"name": "final_response", "reason": "组织最终回答"},
            ],
        },
        execution={
            "status": "completed",
            "final_response": "整体情况良好。",
            "validation": {"warnings": [], "errors": []},
            "step_results": [
                {
                    "index": 0,
                    "step_name": "resolve_activity_range",
                    "status": "completed",
                    "result": {"result": {"schema_version": "activity_list.v1", "count": 1}},
                },
                {
                    "index": 1,
                    "step_name": "summarize_activity_range",
                    "status": "completed",
                    "result": {
                        "answer": "整体情况良好。",
                        "result": {
                            "schema_version": "activity_range_summary.v1",
                            "count": 1,
                            "summary_generation": {
                                "generated_count": 1,
                                "skipped_count": 0,
                                "generated": [
                                    {
                                        "activity_index": 1,
                                        "status": "analyzed",
                                        "fit_path": "garmin_cn_fit_files/morning.fit",
                                        "summary_path": "data/summaries/morning.summary.json",
                                    }
                                ],
                                "skipped": [],
                            },
                        },
                    },
                },
                {
                    "index": 2,
                    "step_name": "final_response",
                    "status": "completed",
                    "result": {"answer": "整体情况良好。"},
                }
            ],
        },
        selected_activities=[
            {
                "activity_index": 1,
                "start_time_local": "2026-05-18T08:36:17",
                "summary_label": "晨间轻松骑",
                "distance_km": 9.38,
                "duration_min": 26.9,
                "summary_path": "data/summaries/morning.summary.json",
                "fit_path": "garmin_cn_fit_files/morning.fit",
            }
        ],
        selected_activity_range={"type": "all_history"},
        current_fit_file=None,
        log_dir=tmp_path,
    )

    text = path.read_text(encoding="utf-8")

    assert path.suffix == ".md"
    assert not path.with_suffix(".jsonl").exists()
    assert "# Workflow Log: planned_workflow_test" in text
    assert "## Final Answer" in text
    assert "整体情况良好。" in text
    assert "## Planner Plan" in text
    assert "final_response" not in text
    assert "## Execution" in text
    assert "summary_generation" in text
    assert "generated_count: `1`" in text
    assert "status=`analyzed`" in text
    assert "晨间轻松骑" in text
    assert "data/summaries/morning.summary.json" in text


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


def test_normalize_workflow_plan_moves_range_scope_to_step_arguments():
    plan = WorkflowPlan(
        task_type="range_summary",
        steps=[
            WorkflowPlanStep(
                name="resolve_activity_range",
                reason="定位上个月活动",
            ),
            WorkflowPlanStep(
                name="summarize_activity_range",
                reason="汇总范围活动",
            ),
        ],
        activity_scope={
            "time_range": "last_month",
            "activity_type": "cycling",
        },
    )

    normalized = normalize_workflow_plan(plan)

    assert normalized.steps[0].arguments == {
        "time_range": "last_month",
        "sport_type": "cycling",
    }


def test_normalize_workflow_plan_preserves_all_history_range_step_name():
    """Normalize 不做语义重写，"全部活动"由 executor 的 fallback 处理."""
    plan = WorkflowPlan(
        task_type="history_overview",
        steps=[
            WorkflowPlanStep(
                name="resolve_activity_range",
                reason="定位所有历史活动",
                arguments={"range": "all"},
            ),
            WorkflowPlanStep(
                name="summarize_activity_range",
                reason="汇总所有历史活动",
            ),
        ],
        activity_scope={"type": "all_history"},
    )

    normalized = normalize_workflow_plan(plan)

    assert normalized.steps[0].name == "resolve_activity_range"
    assert normalized.steps[0].arguments == {"range": "all"}


def test_normalize_workflow_plan_marks_ai_range_summary_request():
    plan = WorkflowPlan(
        task_type="history_overview",
        steps=[
            WorkflowPlanStep(name="resolve_activity_range", reason="定位全部历史活动", arguments={"range": "all"}),
            WorkflowPlanStep(name="summarize_activity_range", reason="汇总所有历史活动"),
        ],
    )

    normalized = normalize_workflow_plan(
        plan,
        user_message="分析所有活动 生成ai总结报告，详细一点",
    )

    assert normalized.steps[1].arguments == {
        "response_mode": "ai_summary",
        "detail_level": "detailed",
    }


def test_normalize_workflow_plan_drops_legacy_final_response_step():
    plan = WorkflowPlan(
        task_type="range_summary",
        steps=[
            WorkflowPlanStep(name="summarize_activity_range", reason="汇总活动"),
            WorkflowPlanStep(name="final_response", reason="旧 planner 输出的空转步骤"),
        ],
    )

    normalized = normalize_workflow_plan(plan, user_message="分析所有活动")

    assert [step.name for step in normalized.steps] == ["summarize_activity_range"]


def test_normalize_workflow_plan_moves_top_level_clarifying_question_to_step():
    plan = WorkflowPlan(
        task_type="clarification",
        steps=[
            WorkflowPlanStep(
                name="ask_user_clarification",
                reason="需要追问范围",
            )
        ],
        needs_user_clarification=True,
        clarifying_question="你想分析全部历史活动还是最近一个月？",
    )

    normalized = normalize_workflow_plan(plan)

    assert normalized.steps[0].arguments == {
        "question": "你想分析全部历史活动还是最近一个月？",
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
