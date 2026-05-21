from __future__ import annotations

from datetime import date

from agent.activity_resolution import execute_activity_resolution_step
from agent.context import AgentContext
from agent.plan_schema import WorkflowPlanStep
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


def test_resolve_activity_range_yesterday_updates_context(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="比较昨天的两次活动",
        arguments={"date_range": "yesterday"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
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


def test_resolve_activity_range_accepts_range_description(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="LLM 使用 range_description 表达昨天",
        arguments={"range_description": "yesterday"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["start_date"] == "2026-05-18"
    assert result["result"]["end_date"] == "2026-05-18"
    assert result["result"]["count"] == 2


def test_resolve_activity_range_accepts_range_type_yesterday(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="LLM 使用 range_type 表达昨天",
        arguments={"range_type": "yesterday"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["start_date"] == "2026-05-18"
    assert result["result"]["end_date"] == "2026-05-18"
    assert result["result"]["count"] == 2
    assert context.selected_activity_range == {
        "type": "date_range",
        "start_date": "2026-05-18",
        "end_date": "2026-05-18",
        "sport_type": None,
    }


def test_resolve_activity_range_accepts_time_range_last_month(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="LLM 使用 time_range 表达上个月",
        arguments={"time_range": "last_month"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
        index_path=index_path,
        today=date(2026, 5, 21),
    )

    assert result["result"]["start_date"] == "2026-04-01"
    assert result["result"]["end_date"] == "2026-04-30"
    assert context.selected_activity_range == {
        "type": "date_range",
        "start_date": "2026-04-01",
        "end_date": "2026-04-30",
        "sport_type": None,
    }


def test_resolve_activity_range_accepts_chinese_this_month(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="用户说本月活动",
        arguments={"time_range": "本月"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
        index_path=index_path,
        today=date(2026, 5, 21),
    )

    assert result["result"]["start_date"] == "2026-05-01"
    assert result["result"]["end_date"] == "2026-05-21"


def test_resolve_activity_range_accepts_natural_language_yesterday(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="LLM 使用自然语言短语表达昨天",
        arguments={"date_range": "昨天（具体日期范围）"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
        index_path=index_path,
        today=date(2026, 5, 19),
    )

    assert result["result"]["start_date"] == "2026-05-18"
    assert result["result"]["end_date"] == "2026-05-18"
    assert result["result"]["count"] == 2


def test_resolve_activity_range_preserves_range_scope_when_only_one_activity(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="查今天的活动",
        arguments={"date_range": "today"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
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


def test_resolve_activity_range_accepts_start_date_only(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="从某天开始查活动",
        arguments={"start_date": "2026-05-19"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
        index_path=index_path,
        today=date(2026, 5, 21),
    )

    assert result["result"]["start_date"] == "2026-05-19"
    assert result["result"]["end_date"] == "2026-05-21"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a3"]


def test_resolve_activity_range_accepts_end_date_only(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="查某天以前的活动",
        arguments={"end_date": "2026-05-18"},
    )

    result = execute_activity_resolution_step(step, context, index_path=index_path)

    assert result["result"]["start_date"] == "0001-01-01"
    assert result["result"]["end_date"] == "2026-05-18"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1", "a2"]


def test_resolve_activity_range_rejects_missing_range_instead_of_defaulting_today(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="比较一段时间",
        arguments={},
    )

    result = execute_activity_resolution_step(
        step,
        context,
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
    step = WorkflowPlanStep(
        name="resolve_activity_range",
        reason="分析所有历史活动",
        arguments={"range": "all"},
    )

    result = execute_activity_resolution_step(step, context, index_path=index_path)

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
    step = WorkflowPlanStep(
        name="resolve_activity_by_date",
        reason="找出昨天最晚的一条活动",
        arguments={"date": "yesterday", "match": "latest"},
    )

    result = execute_activity_resolution_step(
        step,
        context,
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
    step = WorkflowPlanStep(
        name="resolve_activity_by_date",
        reason="分析第二个活动",
        arguments={"activity_index": 2},
    )

    result = execute_activity_resolution_step(step, context, index_path=index_path)

    assert result["result"]["matched_count"] == 1
    assert context.current_activity_key == "a2"
    assert str(context.current_fit_file) == "/tmp/evening.fit"
    assert context.selected_activities[0]["activity_index"] == 2


def test_resolve_activity_by_date_can_infer_activity_index_from_reason(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_activity_by_date",
        reason="分析第二个活动",
        arguments={},
    )

    execute_activity_resolution_step(step, context, index_path=index_path)

    assert context.current_activity_key == "a2"


def test_resolve_recent_activities_updates_selected_activities(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_recent_activities",
        reason="找最近两条活动",
        arguments={"limit": 2},
    )

    result = execute_activity_resolution_step(step, context, index_path=index_path)

    assert result["result"]["count"] == 2
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a3", "a2"]
    assert context.selected_activity_range == {
        "type": "recent_activities",
        "limit": 2,
        "sport_type": None,
        "order": "latest",
    }


def test_resolve_recent_activities_can_select_earliest_activity(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_recent_activities",
        reason="找第一个活动",
        arguments={"limit": 1, "order": "earliest"},
    )

    result = execute_activity_resolution_step(step, context, index_path=index_path)

    assert result["result"]["order"] == "earliest"
    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1"]
    assert context.current_activity_key == "a1"
    assert context.selected_activities[0]["activity_index"] == 1


def test_resolve_recent_activities_can_infer_earliest_from_reason(tmp_path):
    index_path = tmp_path / "activity_index.json"
    _write_index(index_path)
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="resolve_recent_activities",
        reason="定位第一个活动,也就是最早的活动",
        arguments={"limit": 1},
    )

    execute_activity_resolution_step(step, context, index_path=index_path)

    assert [activity["activity_key"] for activity in context.selected_activities] == ["a1"]


def test_non_activity_resolution_step_is_rejected():
    context = AgentContext(session_id="test")
    step = WorkflowPlanStep(
        name="analyze_single_activity",
        reason="不是活动解析步骤",
    )

    result = execute_activity_resolution_step(step, context)

    assert result["error"] == "unsupported_activity_resolution_step"
