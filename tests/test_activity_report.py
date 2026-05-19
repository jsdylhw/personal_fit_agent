from __future__ import annotations

import json

from agent.activity_report import show_selected_activity_report
from agent.context import AgentContext
from agent.plan_schema import WorkflowPlanStep


def test_show_selected_activity_report_reads_markdown_report(tmp_path):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_path": "/tmp/latest.fit",
                "fit_summary": {"sport_type": "cycling"},
                "markdown_report": "# 最新骑行报告\n\n这是一份已有报告。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[
            {
                "activity_key": "a1",
                "summary_path": str(summary),
            }
        ],
    )

    result = show_selected_activity_report(
        WorkflowPlanStep(name="analyze_single_activity", reason="展示报告"),
        context,
    )

    assert result["status"] == "completed"
    assert result["answer"].startswith("# 最新骑行报告")
    assert result["result"]["source"] == "existing_summary"


def test_show_selected_activity_report_reports_missing_summary():
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[{"activity_key": "a1"}],
    )

    result = show_selected_activity_report(
        WorkflowPlanStep(name="analyze_single_activity", reason="展示报告"),
        context,
    )

    assert result["error"] == "missing_activity_summary"
