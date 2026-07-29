from __future__ import annotations

import json

from agent.activity.operations.aggregate import aggregate_summaries
from agent.activity.workflow_executor import execute_activity_run
from agent.activity.workflow_factory import TASK_AGGREGATE_REPORT, TASK_ENSURE_SUMMARY, create_activity_run_from_activities


def _write_summary(path, *, activity_key, distance_m, duration_s):
    path.write_text(json.dumps({
        "activity_key": activity_key,
        "fit_summary": {"sport_type": "cycling", "distance_m": distance_m, "duration_s": duration_s},
        "history_entry": {"summary_label": f"{activity_key} label", "main_stimulus": "aerobic"},
    }), encoding="utf-8")


def test_aggregate_summaries_is_deterministic_and_reports_omissions(tmp_path):
    summary = tmp_path / "a1.summary.json"
    _write_summary(summary, activity_key="a1", distance_m=12345, duration_s=3660)

    result = aggregate_summaries([
        {"activity_key": "a1", "summary_path": str(summary)},
        {"activity_key": "a2", "summary_path": str(tmp_path / "missing.json")},
    ])

    assert result["status"] == "partial"
    assert result["included_count"] == 1
    assert result["omitted"] == [{"activity_key": "a2", "summary_path": str(tmp_path / "missing.json"), "reason": "summary_unavailable"}]
    assert result["totals"] == {"distance_km": 12.35, "duration_min": 61.0}


def test_aggregate_task_runs_after_existing_summaries_without_confirmation(tmp_path):
    summary = tmp_path / "a1.summary.json"
    _write_summary(summary, activity_key="a1", distance_m=5000, duration_s=1800)
    created = create_activity_run_from_activities(
        [{"activity_key": "a1", "fit_path": str(tmp_path / "a1.fit"), "summary_path": str(summary)}],
        request={"source": "test", "goals": [TASK_ENSURE_SUMMARY, TASK_AGGREGATE_REPORT], "force": False},
        directory=tmp_path,
    )
    run = created["run"]

    result = execute_activity_run(run, directory=tmp_path)

    assert result["workflow"]["status"] == "completed"
    by_kind = {task["kind"]: task for task in run["tasks"]}
    assert by_kind[TASK_ENSURE_SUMMARY]["status"] == "skipped"
    assert by_kind[TASK_AGGREGATE_REPORT]["status"] == "completed"
    assert by_kind[TASK_AGGREGATE_REPORT]["report"]["totals"]["distance_km"] == 5.0
