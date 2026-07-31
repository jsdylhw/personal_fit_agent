"""run_tool_loop 的执行、重试与工具依赖测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent.context import AgentContext
from agent.llm import LLMRequestError
from agent.main_agent.loop import MAX_TOOL_STEPS, _build_state_preamble, _build_system_prompt, run_tool_loop


def test_main_prompt_prefers_persistent_workflows():
    prompt = _build_system_prompt(type("Intent", (), {"allow_side_effects": True})())
    assert "run_activity_workflow" in prompt
    assert "sync_and_run_activity_workflow" in prompt
    assert "确认" not in prompt


def test_sync_workflow_executes_without_confirmation(monkeypatch):
    context = AgentContext(session_id="test-direct-sync")
    monkeypatch.setattr(
        "agent.activity.workflow_service.sync_and_start_activity_workflow",
        lambda **kwargs: {"status": "completed", "workflow_id": "run-sync", "execution": {"waiting_for": []}},
    )
    with patch("agent.main_agent.loop.AnthropicMessagesClient") as client:
        client.return_value.create_messages.side_effect = [
            {"id": "msg-sync", "content": [
                {"type": "tool_use", "name": "sync_and_run_activity_workflow", "id": "tu-sync", "input": {"count": 3}},
            ], "stop_reason": "tool_use"},
            {"id": "msg-done", "content": [{"type": "text", "text": "同步完成。"}], "stop_reason": "end_turn"},
        ]
        result = run_tool_loop("同步最近三条活动", context=context)

    assert result["status"] == "completed"
    assert result["steps"] == [{"tool": "sync_and_run_activity_workflow", "input": {"count": 3}}]
    assert result["answer"].endswith("同步完成。")
    assert result["answer"].startswith("已处理：本次请求｜同步并处理活动")


def test_retry_executes_last_failed_workflow_action():
    context = AgentContext(
        session_id="test-retry",
        last_failed_action={"tool": "retry_activity_workflow", "input": {"workflow_id": "run-1"}},
    )
    with patch("agent.main_agent.loop.AnthropicMessagesClient"):
        with patch("agent.main_agent.loop.route_intent") as mock_route:
            with patch("agent.activity.workflow_service.retry_activity_workflow") as mock_retry:
                mock_retry.return_value = {"status": "completed", "workflow_id": "run-1"}
                result = run_tool_loop("再试一次", context=context)

    assert result["status"] == "completed"
    assert result["intent"] == "retry"
    assert context.last_failed_action is None
    assert mock_retry.called
    mock_route.assert_not_called()


def test_llm_disconnect_keeps_completed_tool_state(monkeypatch):
    context = AgentContext(session_id="test-llm-disconnect")

    def fake_find(args, ctx):
        ctx.current_fit_file = Path("/tmp/resolved.fit")
        return {"step": "find_activity", "status": "completed"}

    monkeypatch.setitem(__import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS, "find_activity", fake_find)
    with patch("agent.main_agent.loop.AnthropicMessagesClient") as client:
        client.return_value.create_messages.side_effect = [
            {"id": "msg-find", "content": [{"type": "tool_use", "name": "find_activity", "id": "tu-find", "input": {}}], "stop_reason": "tool_use"},
            LLMRequestError("connection closed"),
        ]
        result = run_tool_loop("分析最近活动", context=context)

    assert result["status"] == "llm_unavailable"
    assert context.current_fit_file == Path("/tmp/resolved.fit")
    assert context.last_llm_error["type"] == "LLMRequestError"


def test_llm_disconnect_after_completed_workflow_reports_real_completion(monkeypatch):
    context = AgentContext(session_id="test-workflow-disconnect")
    monkeypatch.setattr(
        "agent.activity.workflow_service.sync_and_start_activity_workflow",
        lambda **kwargs: {
            "status": "completed",
            "workflow_id": "run-finished",
            "sync": {"downloaded": 2, "skipped": 1},
            "tasks": [
                {"status": "completed"}, {"status": "completed"}, {"status": "skipped"},
            ],
        },
    )
    with patch("agent.main_agent.loop.AnthropicMessagesClient") as client:
        client.return_value.create_messages.side_effect = [
            {"id": "msg-sync", "content": [
                {"type": "tool_use", "name": "sync_and_run_activity_workflow", "id": "tu-sync", "input": {"count": 3}},
            ], "stop_reason": "tool_use"},
            LLMRequestError("connection closed"),
        ]
        result = run_tool_loop("同步最新三条活动，分析并上传", context=context)

    assert result["status"] == "llm_unavailable"
    assert "工作流已完成：run-finished" in result["answer"]
    assert "同步：下载 2 条，跳过 1 条" in result["answer"]
    assert "不会重复执行" in result["answer"]
    assert "最近工作流: run-finished（completed" in _build_state_preamble(context)


def test_max_steps_exceeded_returns_not_completed():
    context = AgentContext(session_id="test-max")
    response = {
        "id": "msg-loop",
        "content": [{"type": "tool_use", "name": "find_activity", "id": "tu-1", "input": {"limit": 1}}],
        "stop_reason": "tool_use",
    }
    with patch("agent.main_agent.loop.AnthropicMessagesClient") as client:
        client.return_value.create_messages.return_value = response
        result = run_tool_loop("分析最近活动", context=context)

    assert result["status"] == "max_steps_exceeded"
    assert len(result["steps"]) == MAX_TOOL_STEPS


def test_find_activity_unblocks_analyze_activity_in_same_round(monkeypatch):
    context = AgentContext(session_id="test-find-then-analyze")
    calls: list[str] = []
    monkeypatch.setitem(
        __import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS,
        "find_activity", lambda args, ctx: calls.append("find_activity") or {"status": "completed"},
    )
    monkeypatch.setitem(
        __import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS,
        "analyze_activity", lambda args, ctx: calls.append("analyze_activity") or {"status": "completed"},
    )
    with patch("agent.main_agent.loop.AnthropicMessagesClient") as client:
        client.return_value.create_messages.side_effect = [
            {"id": "msg-tools", "content": [
                {"type": "tool_use", "name": "find_activity", "id": "tu-find", "input": {}},
                {"type": "tool_use", "name": "analyze_activity", "id": "tu-analyze", "input": {}},
            ], "stop_reason": "tool_use"},
            {"id": "msg-done", "content": [{"type": "text", "text": "分析完成"}], "stop_reason": "end_turn"},
        ]
        result = run_tool_loop("分析最后一个活动", context=context)

    assert result["status"] == "completed"
    assert calls == ["find_activity", "analyze_activity"]


def test_terminal_detail_query_hides_tools_before_final_response(monkeypatch):
    context = AgentContext(
        session_id="terminal-detail",
        current_fit_file=Path("/tmp/current.fit"),
        selected_activities=[{"activity_key": "a1", "fit_path": "/tmp/current.fit"}],
    )
    monkeypatch.setitem(
        __import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS,
        "query_activity_detail",
        lambda args, ctx: {"status": "completed", "result": {"source": "targeted_query"}, "answer": "冲刺数据"},
    )
    with patch("agent.main_agent.loop.AnthropicMessagesClient") as client:
        client.return_value.create_messages.side_effect = [
            {"id": "msg-query", "content": [{"type": "tool_use", "name": "query_activity_detail", "id": "tu-query", "input": {"question": "有冲刺吗"}}], "stop_reason": "tool_use"},
            {"id": "msg-final", "content": [{"type": "text", "text": "冲刺表现良好。"}], "stop_reason": "end_turn"},
        ]
        result = run_tool_loop("这次有冲刺吗", context=context)

    assert result["status"] == "completed"
    assert result["steps"] == [{"tool": "query_activity_detail", "input": {"question": "有冲刺吗"}}]
    assert client.return_value.create_messages.call_args_list[1].kwargs["tools"] == []
