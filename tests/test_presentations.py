from __future__ import annotations

from agent.runtime.models import ToolExecution, TurnResult
from agent.runtime.presentation_projector import project_presentations


def _history_execution() -> ToolExecution:
    return ToolExecution(
        index=1,
        tool="analyze_training_history",
        input={"private_path": "/tmp/activity.fit"},
        result={
            "status": "completed",
            "result": {
                "schema_version": "training_history_analysis.v1",
                "dimensions": [{
                    "name": "volume",
                    "confidence": "medium",
                    "evidence": [{
                        "metric": "duration_min",
                        "baseline": 120,
                        "current": 150,
                        "percent_change": 25,
                        "unit": "min",
                    }],
                }],
                "series": {
                    "periods": [
                        {"period": "2026-W19", "totals": {"duration_min": 120, "tss": 80}},
                        {"period": "2026-W20", "totals": {"duration_min": 150, "tss": 110}},
                    ],
                },
                "view": {"chart_metrics": ["duration_min", "distance_km", "tss"]},
            },
        },
    )


def test_history_projector_uses_deterministic_result_values():
    blocks = project_presentations([_history_execution()])

    assert [block.type for block in blocks] == ["table", "line_chart"]
    assert blocks[0].data["rows"] == [{
        "dimension": "volume",
        "metric": "duration_min",
        "baseline": 120,
        "current": 150,
        "change": 25,
        "unit": "min",
        "confidence": "medium",
    }]
    assert blocks[1].data == {
        "x_label": "训练周期",
        "labels": ["2026-W19", "2026-W20"],
        "series": [
            {"metric": "duration_min", "unit": "min", "values": [120, 150]},
            {"metric": "tss", "unit": "TSS", "values": [80, 110]},
        ],
    }


def test_history_projector_omits_dimensions_without_evidence():
    execution = _history_execution()
    execution.result["result"]["dimensions"].append({
        "name": "recovery", "confidence": "low", "evidence": [],
    })

    blocks = project_presentations([execution])

    assert len(blocks[0].data["rows"]) == 1
    assert all(row["dimension"] != "recovery" for row in blocks[0].data["rows"])


def test_public_turn_result_excludes_internal_state_and_raw_tool_values():
    execution = _history_execution()
    presentations = project_presentations([execution])
    result = TurnResult(
        answer="完成",
        status="completed",
        context={"secret": "internal"},
        intent="training_history",
        executions=[execution],
        presentations=presentations,
        current_fit_file="/tmp/activity.fit",
    ).to_public_dict()

    assert result["answer"] == "完成"
    assert "context" not in result
    assert "current_fit_file" not in result
    assert "input" not in result["executions"][0]
    assert "result" not in result["executions"][0]
    assert "/tmp/activity.fit" not in str(result)


def test_activity_report_projects_markdown_without_exposing_report_metadata():
    execution = ToolExecution(
        index=2,
        tool="analyze_activity",
        result={
            "status": "completed",
            "answer": "# 骑行报告\n\n状态良好。",
            "result": {
                "schema_version": "activity_report.v1",
                "fit_path": "/private/activity.fit",
                "activity_key": "activity-1",
                "fit_summary": {
                    "sport_type": "cycling",
                    "start_time_local": "2026-08-18T08:00:00+08:00",
                    "duration_s": 3660,
                    "distance_m": 25120,
                },
            },
        },
    )

    blocks = project_presentations([execution])

    assert [block.type for block in blocks] == ["metric_cards", "markdown"]
    assert blocks[0].data == {"items": [
        {"metric": "sport_type", "value": "cycling", "unit": ""},
        {"metric": "start_time_local", "value": "2026-08-18T08:00:00+08:00", "unit": ""},
        {"metric": "duration_min", "value": 61.0, "unit": "min"},
        {"metric": "distance_km", "value": 25.12, "unit": "km"},
    ]}
    assert blocks[1].data == {"markdown": "# 骑行报告\n\n状态良好。"}
    assert "/private/activity.fit" not in str([block.to_dict() for block in blocks])


def test_activity_report_projects_local_profile_after_llm_execution(monkeypatch):
    monkeypatch.setattr(
        "agent.runtime.presentation_projector.build_activity_profile",
        lambda path: {
            "x_label": "经过时间",
            "labels": ["0:00", "30:00"],
            "series": [{
                "metric": "cumulative_distance_km", "unit": "km", "values": [0.0, 12.5],
            }],
        },
    )
    execution = ToolExecution(
        index=3,
        tool="analyze_activity",
        result={
            "answer": "活动完成。",
            "result": {
                "schema_version": "activity_report.v1",
                "fit_path": "/private/activity.fit",
            },
        },
    )

    blocks = project_presentations([execution])

    assert [block.type for block in blocks] == ["line_chart", "markdown"]
    assert blocks[0].title == "活动过程曲线"
    assert blocks[0].data["series"][0]["values"] == [0.0, 12.5]


def test_single_resolved_activity_projects_details_without_analyze_tool(monkeypatch):
    monkeypatch.setattr(
        "agent.runtime.presentation_projector.build_activity_profile",
        lambda path: {
            "x_label": "经过时间",
            "labels": ["0:00", "1:00:00"],
            "series": [
                {"metric": "cumulative_distance_km", "unit": "km", "values": [0.0, 52.8]},
                {"metric": "heart_rate_bpm", "unit": "bpm", "values": [118.0, 152.0]},
            ],
        },
    )
    execution = ToolExecution(
        index=0,
        tool="resolve_activities",
        result={"result": {
            "schema_version": "activity_selection.v2",
            "count": 1,
            "activities": [{
                "summary_label": "长距离骑行",
                "sport_type": "cycling",
                "start_time_local": "2026-08-01T18:45:13",
                "duration_min": 105.5,
                "distance_km": 52.8,
                "fit_path": "/private/long.fit",
            }],
        }},
    )

    blocks = project_presentations([execution])

    assert [block.type for block in blocks] == ["metric_cards", "line_chart"]
    assert blocks[0].data["items"][0] == {
        "metric": "summary_label", "value": "长距离骑行", "unit": "",
    }
    assert blocks[1].data["series"][1]["metric"] == "heart_rate_bpm"
    assert "/private/long.fit" not in str([block.to_dict() for block in blocks])


def test_activity_report_replaces_resolved_activity_preview(monkeypatch):
    monkeypatch.setattr(
        "agent.runtime.presentation_projector.build_activity_profile",
        lambda path: {},
    )
    resolved = ToolExecution(
        index=0,
        tool="resolve_activities",
        result={"result": {
            "schema_version": "activity_selection.v2",
            "activities": [{"summary_label": "长距离骑行", "duration_min": 105.5}],
        }},
    )
    report = ToolExecution(
        index=1,
        tool="analyze_activity",
        result={
            "answer": "# 完整报告",
            "result": {"schema_version": "activity_report.v1"},
        },
    )

    blocks = project_presentations([resolved, report])

    assert [block.type for block in blocks] == ["markdown"]
