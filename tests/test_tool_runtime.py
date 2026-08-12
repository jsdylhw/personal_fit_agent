from __future__ import annotations

from agent.context import AgentContext
from agent.main_agent.guard import guard_tool_call
from agent.main_agent.intent import extract_route_signals, intent_tool_categories, route_intent
from agent.main_agent.tools import TOOL_HANDLERS
from agent.tools.agent_tools import MAIN_AGENT_TOOLS


def test_tool_handler_executes_selection_directly(monkeypatch):
    called = {}

    def fake_selection(mode, args, context):
        called["mode"] = mode
        called["arguments"] = args
        return {"selection_mode": mode, "status": "completed"}

    monkeypatch.setattr("agent.activity.selection.service.execute_activity_selection", fake_selection)

    result = TOOL_HANDLERS["find_activity"](
        {"limit": 1},
        AgentContext(session_id="direct-tool"),
    )

    assert result == {
        "step": "find_activity",
        "status": "completed",
        "selection_mode": "recent",
    }
    assert called == {"mode": "recent", "arguments": {"limit": 1}}


def test_workflow_handler_returns_service_result_directly(monkeypatch):
    context = AgentContext(session_id="workflow-tool")
    monkeypatch.setattr(
        "agent.activity.workflow_service.start_local_activity_workflow",
        lambda **kwargs: {
            "status": "completed",
            "workflow_id": "run-1",
            "execution": {"waiting_for": []},
        },
    )

    result = TOOL_HANDLERS["run_activity_workflow"](
        {"limit": 5, "goals": ["upload_strava"]},
        context,
    )

    assert result["status"] == "completed"
    assert result["workflow_id"] == "run-1"


def test_sync_workflow_handler_returns_service_result_directly(monkeypatch):
    context = AgentContext(session_id="sync-workflow-tool")
    monkeypatch.setattr(
        "agent.activity.workflow_service.sync_and_start_activity_workflow",
        lambda **kwargs: {
            "status": "completed", "workflow_id": "run-2",
            "execution": {"waiting_for": []},
        },
    )

    result = TOOL_HANDLERS["sync_and_run_activity_workflow"](
        {"count": 5, "goals": ["upload_strava"]}, context,
    )

    assert result["status"] == "completed"
    assert result["workflow_id"] == "run-2"


def test_workflow_intent_is_available():
    upload_intent = route_intent("重新上传本地的五个活动")
    assert "workflow" in intent_tool_categories(upload_intent)


def test_router_does_not_treat_negated_garmin_or_strava_as_requested_side_effects():
    intent = route_intent("只汇总本地最近 1 条活动，不要下载 Garmin，也不要上传 Strava")

    assert intent.kind.value == "analyze_range"
    assert intent.allow_side_effects is False
    assert "workflow" in intent_tool_categories(intent)


def test_router_keeps_non_activity_conversation_in_chat_mode():
    assert route_intent("我有一个朋友叫小a").kind.value == "chat"
    assert route_intent("我有三个朋友").kind.value == "chat"
    assert route_intent("我有个朋友他叫什么").kind.value == "chat"


def test_router_still_recognizes_implicit_single_activity_question():
    assert route_intent("这次骑行表现怎么样").kind.value == "analyze_single"


def test_router_treats_sync_upload_as_one_mixed_goal():
    intent = route_intent("同步最新三个活动并上传 Strava")

    assert intent.kind.value == "mixed"
    assert intent.allow_side_effects is True
    assert {"operation", "workflow"}.issubset(intent_tool_categories(intent))


def test_router_distinguishes_latest_single_activity_from_recent_range():
    assert route_intent("查看最近一次骑行的完整报告").kind.value == "analyze_single"
    assert route_intent("分析最新一条跑步活动").kind.value == "analyze_single"
    assert route_intent("分析最近三个上午的活动").kind.value == "analyze_range"
    assert route_intent("比较最近几次骑行").kind.value == "compare"


def test_route_signals_keep_negated_side_effects_out_of_mixed_intent():
    signals = extract_route_signals("同步三个活动，不要上传，也不要分析")

    assert signals.wants_sync is True
    assert signals.wants_upload is False
    assert signals.wants_analyze is False


def test_guard_rejects_registered_tool_outside_the_current_category_allowlist():
    result = guard_tool_call(
        "sync_and_run_activity_workflow",
        {"count": 1},
        context=AgentContext(session_id="guard"),
        allowed_categories={"conversation"},
    )

    assert result.allowed is False
    assert "不在本轮允许" in result.reason


def test_guard_rejects_unknown_tool_before_handler_dispatch():
    result = guard_tool_call(
        "unadvertised_side_effect",
        {},
        context=AgentContext(session_id="guard"),
        allowed_categories={"conversation"},
    )

    assert result.allowed is False
    assert "未知或未注册" in result.reason


def test_analyze_activity_refuses_to_reanalyze_a_selected_range():
    context = AgentContext(session_id="range", selected_activities=[{"activity_key": "a1"}, {"activity_key": "a2"}])

    result = TOOL_HANDLERS["analyze_activity"]({}, context)

    assert result["error"] == "single_activity_required"


def test_main_agent_exposes_explicit_detail_query_instead_of_implicit_targeted_analysis():
    names = {tool.name for tool in MAIN_AGENT_TOOLS}

    assert "query_activity_detail" in names
    assert "user_request" not in next(tool for tool in MAIN_AGENT_TOOLS if tool.name == "analyze_activity").input_schema["properties"]


def test_find_activity_chooses_single_day_selection_from_date_not_scope(monkeypatch):
    called = {}

    def fake_selection(mode, args, context):
        called["mode"] = mode
        return {"selection_mode": mode, "status": "completed"}

    monkeypatch.setattr("agent.activity.selection.service.execute_activity_selection", fake_selection)

    TOOL_HANDLERS["find_activity"](
        {"date": "today", "time_of_day": "morning"},
        AgentContext(session_id="today-range"),
    )

    assert called["mode"] == "single"
