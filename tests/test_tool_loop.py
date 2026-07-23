"""run_tool_loop 控制流单测:确认、max_steps、pending 直接执行."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent.context import AgentContext
from agent.main_agent.permission import DENY_LIST
from agent.main_agent.loop import MAX_TOOL_STEPS, run_tool_loop


# -- 确认流: pending action 被用户确认后直接执行 --------------------------------

def test_confirmation_directly_executes_pending_tool():
    """用户说'确认'时,直接执行 pending tool,不走 LLM."""
    context = AgentContext(
        session_id="test-confirm",
        pending_action={
            "tool": "download_activities",
            "input": {"count": 3},
            "message": "确认下载？",
        },
    )

    with patch("agent.main_agent.loop.AnthropicMessagesClient"):
        with patch("agent.main_agent.loop.route_intent") as mock_route:
            with patch("agent.operations.sync_garmin_activities_tool") as mock_sync:
                mock_sync.return_value = {"total": 3, "downloaded": 2, "skipped": 1}
                result = run_tool_loop("确认", context=context)

    assert result["status"] == "completed"
    assert result["intent"] == "confirmed"
    assert result["steps"][0]["tool"] == "download_activities"
    assert mock_sync.called
    mock_route.assert_not_called()  # 不走 LLM


def test_confirmation_resumes_paused_tool_loop():
    """权限暂停来自 tool_loop 时,确认后应执行工具并继续原 loop."""
    context = AgentContext(session_id="test-confirm-resume")

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.return_value = {
            "id": "msg-sync",
            "content": [
                {
                    "type": "tool_use",
                    "name": "download_activities",
                    "id": "tu-sync",
                    "input": {"count": 3},
                }
            ],
            "stop_reason": "tool_use",
        }
        first = run_tool_loop("同步最近3条活动", context=context)

    assert first["status"] == "needs_confirmation"
    assert context.pending_action is not None
    assert context.pending_action["tool"] == "download_activities"
    assert "resume" in context.pending_action

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.return_value = {
            "id": "msg-done",
            "content": [{"type": "text", "text": "同步完成。"}],
            "stop_reason": "end_turn",
        }
        with patch("agent.operations.sync_garmin_activities_tool") as mock_sync:
            with patch("agent.main_agent.loop.route_intent") as mock_route:
                mock_sync.return_value = {"total": 3, "downloaded": 3, "skipped": 0}
                second = run_tool_loop("确认", context=context)

    assert second["status"] == "completed"
    assert second["answer"] == "同步完成。"
    assert second["steps"] == [{"tool": "download_activities", "input": {"count": 3}}]
    assert context.pending_action is None
    assert mock_sync.called
    mock_route.assert_not_called()


def test_confirmation_without_pending_is_explicit_message():
    """没有 pending action 时,'确认' 不应重新进入 LLM 路由."""
    context = AgentContext(session_id="test-no-pending")

    with patch("agent.main_agent.loop.AnthropicMessagesClient"):
        with patch("agent.main_agent.loop.route_intent") as mock_route:
            result = run_tool_loop("确认", context=context)

    assert result["status"] == "no_pending_confirmation"
    assert "没有待确认" in result["answer"]
    mock_route.assert_not_called()


def test_non_confirmation_keeps_pending():
    """用户说别的话时,pending 保留,走正常 LLM."""
    context = AgentContext(
        session_id="test-keep",
        pending_action={
            "tool": "upload_activity",
            "input": {},
            "message": "确认上传？",
        },
    )

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.return_value = {
            "id": "msg-1",
            "content": [{"type": "text", "text": "好的，我了解了。"}],
            "stop_reason": "end_turn",
        }
        result = run_tool_loop("不，我想先分析一下", context=context)

    assert result["status"] == "needs_confirmation"  # pending 还在
    assert context.pending_action is not None


def test_retry_executes_last_failed_action():
    """用户说'再试一次'时,直接复用上次失败的 tool 和参数."""
    context = AgentContext(
        session_id="test-retry",
        current_fit_file=Path("/tmp/current.fit"),
        last_failed_action={
            "tool": "upload_activity",
            "input": {"force": True},
        },
    )

    with patch("agent.main_agent.loop.AnthropicMessagesClient"):
        with patch("agent.main_agent.loop.route_intent") as mock_route:
            with patch("agent.main_agent.handlers.upload_to_strava_tool") as mock_upload:
                with patch("agent.main_agent.handlers.AnthropicMessagesClient") as MockUploadLlm:
                    mock_upload.return_value = {"status": "uploaded", "strava_activity_id": 123}
                    MockUploadLlm.return_value.create_message.return_value = {
                        "content": [{"type": "text", "text": "上传成功"}],
                        "stop_reason": "end_turn",
                    }
                    result = run_tool_loop("再试一次", context=context)

    assert result["status"] == "completed"
    assert result["intent"] == "retry"
    assert result["steps"] == [{"tool": "upload_activity", "input": {"force": True}}]
    assert context.last_failed_action is None
    assert mock_upload.called
    mock_route.assert_not_called()


# -- max_steps ----------------------------------------------------------------

def test_max_steps_exceeded_returns_not_completed():
    """超过 MAX_TOOL_STEPS 且未完成 → status=max_steps_exceeded."""
    context = AgentContext(session_id="test-max")

    # 让 LLM 一直返回 tool_use, 触发 max steps
    def fake_create_messages(**kwargs):
        return {
            "id": "msg-loop",
            "content": [{"type": "tool_use", "name": "find_activity", "id": "tu-1", "input": {"limit": 1}}],
            "stop_reason": "tool_use",
        }

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.side_effect = fake_create_messages
        result = run_tool_loop("分析", context=context)

    assert result["status"] == "max_steps_exceeded"
    assert result["steps"] is not None
    assert len(result["steps"]) > 0


def test_confirmation_at_step_limit_does_not_start_an_extra_llm_turn(monkeypatch):
    """确认发生在最后预算轮次时，只执行已确认工具，不再发起第 11 轮 LLM 请求。"""
    context = AgentContext(session_id="test-confirm-at-step-limit")
    calls: list[str] = []

    def fake_find(args, ctx):
        calls.append("find_activity")
        return {"status": "completed"}

    def fake_download(args, ctx):
        calls.append("download_activities")
        return {"status": "completed"}

    import agent.main_agent.tools as tools_module

    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "find_activity", fake_find)
    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "download_activities", fake_download)

    responses = [
        {
            "id": f"msg-{step}",
            "content": [{"type": "tool_use", "name": "find_activity", "id": f"find-{step}", "input": {}}],
            "stop_reason": "tool_use",
        }
        for step in range(1, MAX_TOOL_STEPS)
    ]
    responses.append({
        "id": "msg-limit",
        "content": [{
            "type": "tool_use",
            "name": "download_activities",
            "id": "download-limit",
            "input": {"count": 1},
        }],
        "stop_reason": "tool_use",
    })

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        MockClient.return_value.create_messages.side_effect = responses
        paused = run_tool_loop("同步活动", context=context)

    assert paused["status"] == "needs_confirmation"
    assert context.pending_action["resume"]["step_count"] == MAX_TOOL_STEPS

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        resumed = run_tool_loop("确认", context=context)

    assert resumed["status"] == "max_steps_exceeded"
    assert MockClient.return_value.create_messages.call_count == 0
    assert calls == ["find_activity"] * (MAX_TOOL_STEPS - 1) + ["download_activities"]


def test_side_effect_returns_needs_confirmation():
    """LLM 请求 download_activities 时返回 needs_confirmation."""
    context = AgentContext(session_id="test-sidefx")

    def fake_create_messages(**kwargs):
        return {
            "id": "msg-sync",
            "content": [{"type": "tool_use", "name": "download_activities", "id": "tu-1", "input": {"count": 3}}],
            "stop_reason": "tool_use",
        }

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.side_effect = fake_create_messages
        result = run_tool_loop("下载最近3条Garmin活动", context=context)

    assert result["status"] == "needs_confirmation"
    assert result["context"].pending_action is not None
    assert result["context"].pending_action["tool"] == "download_activities"
    assert result["context"].pending_action["input"] == {"count": 3}


def test_find_activity_unblocks_analyze_activity_in_same_round(monkeypatch):
    """find_activity 后同轮 analyze_activity 应允许执行."""
    context = AgentContext(session_id="test-find-then-analyze")
    calls: list[str] = []

    def fake_find(args, ctx):
        calls.append("find_activity")
        return {"step": "find_activity", "status": "completed", "result": {"count": 1}}

    def fake_analyze(args, ctx):
        calls.append("analyze_activity")
        return {"step": "analyze_activity", "status": "completed", "answer": "分析完成"}

    monkeypatch.setitem(__import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS, "find_activity", fake_find)
    monkeypatch.setitem(__import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS, "analyze_activity", fake_analyze)

    responses = [
        {
            "id": "msg-tools",
            "content": [
                {"type": "tool_use", "name": "find_activity", "id": "tu-find", "input": {"scope": "recent", "limit": 1}},
                {"type": "tool_use", "name": "analyze_activity", "id": "tu-analyze", "input": {}},
            ],
            "stop_reason": "tool_use",
        },
        {
            "id": "msg-done",
            "content": [{"type": "text", "text": "分析完成"}],
            "stop_reason": "end_turn",
        },
    ]

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        MockClient.return_value.create_messages.side_effect = responses
        result = run_tool_loop("分析最后一个活动", context=context)

    assert result["status"] == "completed"
    assert calls == ["find_activity", "analyze_activity"]


def test_child_permission_pause_stops_remaining_tools(monkeypatch):
    """handler 内部触发子 agent 权限时,确认后应恢复原 tool loop."""
    context = AgentContext(session_id="test-child-permission")
    calls: list[str] = []

    def fake_find(args, ctx):
        calls.append("find_activity")
        return {"step": "find_activity", "status": "completed", "result": {"count": 1}}

    def fake_analyze(args, ctx):
        calls.append("analyze_confirmed" if args.get("_confirmed") else "analyze_activity")
        if args.get("_confirmed"):
            return {"step": "analyze_activity", "status": "completed", "answer": "分析完成"}
        ctx.pending_action = {
            "tool": "analyze_activity",
            "input": {**args, "_confirmed": True},
            "message": "生成/刷新 summary 文件 (会写入本地磁盘)",
        }
        return {"step": "analyze_activity", "status": "needs_confirmation"}

    def fake_upload(args, ctx):
        calls.append("upload_activity")
        return {"step": "upload_activity", "status": "completed"}

    tools_module = __import__("agent.main_agent.tools", fromlist=["TOOL_HANDLERS"])
    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "find_activity", fake_find)
    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "analyze_activity", fake_analyze)
    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "upload_activity", fake_upload)

    responses = [
        {
            "id": "msg-tools",
            "content": [
                {"type": "tool_use", "name": "find_activity", "id": "tu-find", "input": {"scope": "recent", "limit": 1}},
                {"type": "tool_use", "name": "analyze_activity", "id": "tu-analyze", "input": {"force": True}},
                {"type": "tool_use", "name": "upload_activity", "id": "tu-upload", "input": {}},
            ],
            "stop_reason": "tool_use",
        },
    ]

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        MockClient.return_value.create_messages.side_effect = responses
        result = run_tool_loop("重新分析然后上传", context=context)

    assert result["status"] == "needs_confirmation"
    assert calls == ["find_activity", "analyze_activity"]
    assert context.pending_action is not None
    assert context.pending_action["input"]["_confirmed"] is True
    assert "resume" in context.pending_action

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        MockClient.return_value.create_messages.return_value = {
            "id": "msg-done",
            "content": [{"type": "text", "text": "两个活动已处理。"}],
            "stop_reason": "end_turn",
        }
        confirmed = run_tool_loop("yes", context=context)

    assert confirmed["status"] == "completed"
    assert confirmed["answer"] == "两个活动已处理。"
    assert calls == ["find_activity", "analyze_activity", "analyze_confirmed"]
    assert context.pending_action is None


def test_hard_deny_does_not_create_pending_confirmation():
    """硬拒绝是不可确认的拒绝,不应写入 pending_action."""
    context = AgentContext(session_id="test-deny")
    DENY_LIST.append(("find_activity", "测试硬拒绝"))
    responses = [
        {
            "id": "msg-deny",
            "content": [
                {
                    "type": "tool_use",
                    "name": "find_activity",
                    "id": "tu-deny",
                    "input": {"limit": 1},
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "id": "msg-ok",
            "content": [{"type": "text", "text": "该操作已被拒绝。"}],
            "stop_reason": "end_turn",
        },
    ]

    try:
        with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
            mock_client = MockClient.return_value
            mock_client.create_messages.side_effect = responses
            result = run_tool_loop("分析最后一个活动", context=context)
    finally:
        DENY_LIST.pop()

    assert result["status"] == "completed"
    assert context.pending_action is None
    assert "已被拒绝" in result["answer"]


def test_completed_within_max_steps():
    """正常完成 → status=completed."""
    context = AgentContext(session_id="test-ok")

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.return_value = {
            "id": "msg-ok",
            "content": [{"type": "text", "text": "你好！有什么可以帮你的？"}],
            "stop_reason": "end_turn",
        }
        result = run_tool_loop("你好", context=context)

    assert result["status"] == "completed"


def test_todo_write_updates_context_for_any_intent():
    """todo_write 是规划工具,即使 chat intent 也应可用."""
    context = AgentContext(session_id="test-todo")

    responses = [
        {
            "id": "msg-todo",
            "content": [
                {
                    "type": "tool_use",
                    "name": "todo_write",
                    "id": "tu-todo",
                    "input": {
                        "todos": [
                            {"content": "定位最近活动", "status": "in_progress"},
                            {"content": "生成摘要", "status": "pending"},
                        ],
                    },
                },
            ],
            "stop_reason": "tool_use",
        },
        {
            "id": "msg-ok",
            "content": [{"type": "text", "text": "计划已更新。"}],
            "stop_reason": "end_turn",
        },
    ]

    with patch("agent.main_agent.loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.side_effect = responses
        result = run_tool_loop("你好", context=context)

    assert result["status"] == "completed"
    assert result["steps"] == [{"tool": "todo_write", "input": responses[0]["content"][0]["input"]}]
    assert context.current_todos == [
        {"content": "定位最近活动", "status": "in_progress"},
        {"content": "生成摘要", "status": "pending"},
    ]
    assert context.todo_rounds_since_update == 0
    assert not any(
        isinstance(message.get("content"), list)
        and any(isinstance(block, dict) and block.get("type") in {"tool_use", "tool_result"} for block in message["content"])
        for message in context.messages
    )
