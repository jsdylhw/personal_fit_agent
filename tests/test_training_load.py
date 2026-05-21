from __future__ import annotations

import json

from agent.context import AgentContext
from agent.plan_schema import WorkflowPlanStep
from agent.training_load import summarize_recent_training_load


def _write_summary(path, *, key: str, tss: float, intensity_factor: float, distance_km: float, duration_min: float):
    path.write_text(
        json.dumps(
            {
                "activity_key": key,
                "fit_summary": {
                    "sport_type": "cycling",
                    "start_time_local": f"2026-05-1{1 if key == 'a1' else 2}T08:00:00",
                },
                "history_entry": {
                    "summary_label": f"活动 {key}",
                    "main_stimulus": "耐力骑行",
                    "training_load": f"TSS {tss}",
                    "duration_min": duration_min,
                    "distance_km": distance_km,
                    "brief": f"NP 210W, IF {intensity_factor}, TSS {tss}",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_summarize_recent_training_load_outputs_structured_metrics_only(tmp_path):
    first = tmp_path / "first.summary.json"
    second = tmp_path / "second.summary.json"
    _write_summary(first, key="a1", tss=42.5, intensity_factor=0.62, distance_km=30, duration_min=80)
    _write_summary(second, key="a2", tss=114.0, intensity_factor=0.88, distance_km=43.2, duration_min=111.3)
    context = AgentContext(
        session_id="training-load-test",
        selected_activities=[
            {"activity_key": "a1", "summary_path": str(first)},
            {"activity_key": "a2", "summary_path": str(second)},
        ],
        selected_activity_range={"type": "recent_activities", "limit": 2},
    )

    result = summarize_recent_training_load(
        WorkflowPlanStep(name="summarize_recent_training_load", reason="整理近期训练负荷"),
        context,
    )

    assert result["status"] == "completed"
    assert "answer" not in result
    summary = result["result"]
    assert summary["schema_version"] == "training_load_summary.v1"
    assert summary["activity_count"] == 2
    assert summary["totals"]["distance_km"] == 73.2
    assert summary["totals"]["duration_min"] == 191.3
    assert summary["totals"]["tss"] == 156.5
    assert summary["intensity"]["basis"] == "power_tss_if"
    assert summary["intensity"]["hard_activity_count"] == 1
    assert summary["intensity"]["easy_activity_count"] == 1
    assert summary["intensity"]["avg_if"] == 0.75
    assert "load_assessment" not in summary


def test_summarize_recent_training_load_reports_missing_summaries():
    context = AgentContext(
        session_id="training-load-test",
        selected_activities=[{"activity_key": "a1"}],
    )

    result = summarize_recent_training_load(
        WorkflowPlanStep(name="summarize_recent_training_load", reason="整理近期训练负荷"),
        context,
    )

    assert result["error"] == "missing_activity_summary"
    assert result["missing"][0]["activity_key"] == "a1"
