from __future__ import annotations

from datetime import date

from agent.activity.selection import execute_activity_selection, select_activity_mode
from agent.context import AgentContext
from core.activity_index import save_activity_index


def _write_index(path):
    save_activity_index(
        {
            "activities": [
                {
                    "activity_key": "a1",
                    "file_name": "morning.fit",
                    "fit_path": "/tmp/morning.fit",
                    "summary_path": "/tmp/morning.summary.json",
                    "sport_type": "cycling",
                    "start_time_local": "2026-05-18T08:00:00",
                    "date_local": "2026-05-18",
                    "duration_s": 1800,
                    "distance_m": 12000,
                    "has_summary": True,
                },
                {
                    "activity_key": "a2",
                    "file_name": "evening.fit",
                    "fit_path": "/tmp/evening.fit",
                    "summary_path": "/tmp/evening.summary.json",
                    "sport_type": "cycling",
                    "start_time_local": "2026-05-18T20:00:00",
                    "date_local": "2026-05-18",
                    "duration_s": 2400,
                    "distance_m": 18000,
                    "has_summary": False,
                },
                {
                    "activity_key": "a3",
                    "file_name": "today.fit",
                    "fit_path": "/tmp/today.fit",
                    "sport_type": "running",
                    "start_time_local": "2026-05-19T07:00:00",
                    "date_local": "2026-05-19",
                    "duration_s": 1200,
                    "distance_m": 3000,
                    "has_summary": False,
                },
            ]
        },
        path=path,
    )


def _run(name, arguments, context, *, reason="", index_path=None, today=None):
    mode = {
        "resolve_current_activity": "current",
        "resolve_activity_by_date": "single",
        "resolve_activity_range": "range",
        "resolve_recent_activities": "recent",
    }.get(name, name)
    return execute_activity_selection(
        mode,
        arguments,
        context,
        reason=reason,
        index_path=index_path,
        today=today,
    )


def test_resolve_activity_range_yesterday_updates_context(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_range",
        {"date_range": "yesterday"},
        context,
        reason="比较昨天的两次活动",
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["count"] == 2
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1", "a2"]
    assert context.selected_activity_range == {
        "type": "date_range",
        "start_date": "2026-05-18",
        "end_date": "2026-05-18",
        "sport_type": None,
    }
    assert context.current_fit_file is None


def test_resolve_activity_range_accepts_common_range_aliases(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    cases = [
        ({"range_description": "yesterday"}, date(2026, 5, 19), "2026-05-18", "2026-05-18"),
        ({"range_type": "yesterday"}, date(2026, 5, 19), "2026-05-18", "2026-05-18"),
        ({"time_range": "last_month"}, date(2026, 5, 21), "2026-04-01", "2026-04-30"),
        ({"time_range": "本月"}, date(2026, 5, 21), "2026-05-01", "2026-05-21"),
        ({"date_range": "昨天（具体日期范围）"}, date(2026, 5, 19), "2026-05-18", "2026-05-18"),
    ]

    for arguments, today, start_date, end_date in cases:
        context = AgentContext(session_id="test")
        result = _run(
            "resolve_activity_range",
            arguments,
            context,
            reason="解析时间范围",
            index_path=index_path,
            today=today,
        )
        assert result["result"]["start_date"] == start_date
        assert result["result"]["end_date"] == end_date


def test_resolve_activity_range_preserves_range_scope_when_only_one_activity(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_range",
        {"date_range": "today"},
        context,
        reason="查今天的活动",
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["count"] == 1
    assert context.current_activity_key == "a3"
    assert context.selected_activity_range == {
        "type": "date_range",
        "start_date": "2026-05-19",
        "end_date": "2026-05-19",
        "sport_type": None,
    }


def test_resolve_activity_range_accepts_open_ended_dates(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)

    context = AgentContext(session_id="test")
    result = _run(
        "resolve_activity_range",
        {"start_date": "2026-05-19"},
        context,
        reason="从某天开始查活动",
        index_path=index_path,
        today=date(2026, 5, 21),
    )
    assert result["result"]["start_date"] == "2026-05-19"
    assert result["result"]["end_date"] == "2026-05-21"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a3"]

    context = AgentContext(session_id="test")
    result = _run(
        "resolve_activity_range",
        {"end_date": "2026-05-18"},
        context,
        reason="查某天以前的活动",
        index_path=index_path,
    )
    assert result["result"]["start_date"] == "0001-01-01"
    assert result["result"]["end_date"] == "2026-05-18"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1", "a2"]


def test_resolve_activity_range_rejects_missing_range_instead_of_defaulting_today(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_range",
        {},
        context,
        reason="比较一段时间",
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["error"] == "missing_activity_range"
    assert context.selected_activities == []
    assert context.selected_activity_range is None


def test_resolve_activity_range_accepts_explicit_all_range(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_range",
        {"range": "all"},
        context,
        reason="分析所有历史活动",
        index_path=index_path,
    )

    assert result["result"]["count"] == 3
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a3", "a2", "a1"]
    assert context.selected_activity_range == {
        "type": "unbounded_range",
        "sport_type": None,
    }


def test_resolve_activity_by_date_updates_current_activity(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_by_date",
        {"date": "yesterday", "match": "latest"},
        context,
        reason="找出昨天最晚的一条活动",
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["matched_count"] == 2
    assert context.current_activity_key == "a2"
    assert str(context.current_fit_file) == "/tmp/evening.fit"
    assert str(context.current_summary_path) == "/tmp/evening.summary.json"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a2"]


def test_resolve_activity_by_activity_index_updates_current_activity(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_by_date",
        {"activity_index": 2},
        context,
        reason="分析第二个活动",
        index_path=index_path,
    )

    assert result["result"]["matched_count"] == 1
    assert context.current_activity_key == "a2"
    assert str(context.current_fit_file) == "/tmp/evening.fit"
    assert context.selected_activities[0]["activity_index"] == 2


def test_resolve_activity_by_date_can_infer_activity_index_from_reason(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    _run(
        "resolve_activity_by_date",
        {},
        context,
        reason="分析第二个活动",
        index_path=index_path,
    )

    assert context.current_activity_key == "a2"


def test_resolve_recent_activities_updates_selected_activities(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_recent_activities",
        {"limit": 2},
        context,
        reason="找最近两条活动",
        index_path=index_path,
    )

    assert result["result"]["count"] == 2
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a3", "a2"]
    assert context.selected_activity_range == {
        "type": "recent_activities",
        "limit": 2,
        "sport_type": None,
        "order": "latest",
    }


def test_resolve_recent_activities_filters_before_applying_limit(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_recent_activities",
        {"limit": 2, "time_of_day": "morning"},
        context,
        reason="分析最近两个上午的活动",
        index_path=index_path,
    )

    assert result["result"]["count"] == 2
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a3", "a1"]
    assert context.selected_activity_range["time_of_day"] == "morning"


def test_resolution_accepts_ride_alias_for_cycling(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_by_date",
        {"date": "yesterday", "sport_type": "Ride"},
        context,
        reason="昨天这次骑行",
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["matched_count"] == 2
    assert context.current_activity_key == "a2"


def test_single_day_resolution_applies_morning_filter(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")

    result = _run(
        "resolve_activity_by_date",
        {"date": "yesterday", "sport_type": "Ride", "time_of_day": "morning"},
        context,
        reason="昨天上午骑行",
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["matched_count"] == 1
    assert context.current_activity_key == "a1"


def test_resolve_recent_activities_can_select_earliest_activity(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)

    context = AgentContext(session_id="test")
    result = _run(
        "resolve_recent_activities",
        {"limit": 1, "order": "earliest"},
        context,
        reason="找第一个活动",
        index_path=index_path,
    )
    assert result["result"]["order"] == "earliest"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1"]
    assert context.current_activity_key == "a1"
    assert context.selected_activities[0]["activity_index"] == 1

    context = AgentContext(session_id="test")
    _run(
        "resolve_recent_activities",
        {"limit": 1},
        context,
        reason="定位第一个活动,也就是最早的活动",
        index_path=index_path,
    )
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1"]


def test_resolve_recent_activities_rejects_invalid_limit(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)

    for limit in ("latest", 999):
        context = AgentContext(session_id="test")
        result = _run(
            "resolve_recent_activities",
            {"limit": limit},
            context,
            reason="找最近活动",
            index_path=index_path,
        )
        assert result["error"] == "invalid_recent_activity_limit"
        assert context.selected_activities == []


def test_non_activity_resolution_step_is_rejected():
    result = _run(
        "analyze_single_activity",
        {},
        AgentContext(session_id="test"),
        reason="不是活动解析步骤",
    )

    assert result["error"] == "unsupported_activity_selection_mode"


def test_selection_mode_is_chosen_from_selector_facts():
    assert select_activity_mode({"date": "today", "time_of_day": "morning"}) == "single"
    assert select_activity_mode({"scope": "range", "date": "today"}) == "single"
    assert select_activity_mode({"start_date": "2026-05-01", "end_date": "2026-05-07"}) == "range"
    assert select_activity_mode({"limit": 3}) == "recent"
    assert select_activity_mode({"current": True}) == "current"
