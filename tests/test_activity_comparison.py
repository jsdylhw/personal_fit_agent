from __future__ import annotations

import json

from agent.activity.comparison import compare_selected_activities_tool
from agent.context import AgentContext


def _write_summary(path, *, key: str, label: str, distance_km: float, duration_min: float):
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
                    "training_load": "极低" if key == "a2" else "非常轻",
                    "duration_min": duration_min,
                    "distance_km": distance_km,
                    "brief": f"{label} brief",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_compare_selected_activities_reads_existing_summaries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    summary_dir = tmp_path / "data" / "summaries"
    summary_dir.mkdir(parents=True)
    first = summary_dir / "morning.summary.json"
    second = summary_dir / "evening.summary.json"
    _write_summary(first, key="a1", label="晨间轻松骑", distance_km=9.38, duration_min=26.9)
    _write_summary(second, key="a2", label="夜间恢复骑", distance_km=15.79, duration_min=42.8)

    context = AgentContext(
        session_id="comparison-test",
        selected_activities=[
            {
                "activity_key": "a1",
                "file_name": "morning.fit",
                "summary_path": str(first),
            },
            {
                "activity_key": "a2",
                "file_name": "evening.fit",
                "summary_path": str(second),
            },
        ],
    )

    result = compare_selected_activities_tool(context)

    assert result["status"] == "completed"
    assert result["result"]["count"] == 2
    assert result["result"]["totals"] == {"distance_km": 25.17, "duration_min": 69.7}
    assert result["result"]["highlights"]["longest_distance_activity_key"] == "a2"
    assert "没有重新解析 FIT" in result["answer"]


def test_compare_selected_activities_falls_back_from_windows_summary_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    summary_dir = tmp_path / "data" / "summaries"
    summary_dir.mkdir(parents=True)
    summary = summary_dir / "evening.summary.json"
    _write_summary(summary, key="a2", label="夜间恢复骑", distance_km=15.79, duration_min=42.8)
    other = summary_dir / "morning.summary.json"
    _write_summary(other, key="a1", label="晨间轻松骑", distance_km=9.38, duration_min=26.9)

    context = AgentContext(
        session_id="comparison-test",
        selected_activities=[
            {"activity_key": "a1", "summary_path": r"C:\codes\personal_fit_agent\data\summaries\morning.summary.json"},
            {"activity_key": "a2", "summary_path": r"C:\codes\personal_fit_agent\data\summaries\evening.summary.json"},
        ],
    )

    result = compare_selected_activities_tool(context)

    assert result["status"] == "completed"
    assert [item["activity_key"] for item in result["result"]["activities"]] == ["a1", "a2"]


def test_compare_selected_activities_reports_missing_summary():
    context = AgentContext(
        session_id="comparison-test",
        selected_activities=[
            {"activity_key": "a1"},
            {"activity_key": "a2"},
        ],
    )

    result = compare_selected_activities_tool(context)

    assert result["error"] == "missing_activity_summary"
    assert len(result["missing"]) == 2
