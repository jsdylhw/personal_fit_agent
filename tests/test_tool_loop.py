"""run_tool_loop 控制流单测:确认、max_steps、pending 直接执行."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent.context import AgentContext
from agent.workflow.permission import DENY_LIST
from agent.workflow.tool_loop import MAX_TOOL_STEPS, run_tool_loop


# -- 确认流: pending action 被用户确认后直接执行 --------------------------------

def test_confirmation_directly_executes_pending_tool():
    """用户说'确认'时,直接执行 pending tool,不走 LLM."""
    context = AgentContext(
        session_id="test-confirm",
        pending_action={
            "tool": "sync_garmin_activities",
            "input": {"count": 3},
            "message": "确认下载？",
        },
    )

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient"):
        with patch("agent.workflow.tool_loop.route_intent") as mock_route:
            with patch("agent.workflow.handlers.ops.sync_garmin_activities_tool") as mock_sync:
                mock_sync.return_value = {"total": 3, "downloaded": 2, "skipped": 1}
                result = run_tool_loop("确认", context=context)

    assert result["status"] == "completed"
    assert result["intent"] == "confirmed"
    assert result["steps"][0]["tool"] == "sync_garmin_activities"
    assert mock_sync.called
    mock_route.assert_not_called()  # 不走 LLM


def test_confirmation_resumes_paused_tool_loop():
    """权限暂停来自 tool_loop 时,确认后应执行工具并继续原 loop."""
    context = AgentContext(session_id="test-confirm-resume")

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.return_value = {
            "id": "msg-sync",
            "content": [
                {
                    "type": "tool_use",
                    "name": "sync_garmin_activities",
                    "id": "tu-sync",
                    "input": {"count": 3},
                }
            ],
            "stop_reason": "tool_use",
        }
        first = run_tool_loop("同步最近3条活动", context=context)

    assert first["status"] == "needs_confirmation"
    assert context.pending_action is not None
    assert context.pending_action["tool"] == "sync_garmin_activities"
    assert "resume" in context.pending_action

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.return_value = {
            "id": "msg-done",
            "content": [{"type": "text", "text": "同步完成。"}],
            "stop_reason": "end_turn",
        }
        with patch("agent.workflow.handlers.ops.sync_garmin_activities_tool") as mock_sync:
            with patch("agent.workflow.tool_loop.route_intent") as mock_route:
                mock_sync.return_value = {"total": 3, "downloaded": 3, "skipped": 0}
                second = run_tool_loop("确认", context=context)

    assert second["status"] == "completed"
    assert second["answer"] == "同步完成。"
    assert second["steps"] == [{"tool": "sync_garmin_activities", "input": {"count": 3}}]
    assert context.pending_action is None
    assert mock_sync.called
    mock_route.assert_not_called()


def test_confirmation_without_pending_is_explicit_message():
    """没有 pending action 时,'确认' 不应重新进入 LLM 路由."""
    context = AgentContext(session_id="test-no-pending")

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient"):
        with patch("agent.workflow.tool_loop.route_intent") as mock_route:
            result = run_tool_loop("确认", context=context)

    assert result["status"] == "no_pending_confirmation"
    assert "没有待确认" in result["answer"]
    mock_route.assert_not_called()


def test_non_confirmation_keeps_pending():
    """用户说别的话时,pending 保留,走正常 LLM."""
    context = AgentContext(
        session_id="test-keep",
        pending_action={
            "tool": "upload_strava_activity",
            "input": {},
            "message": "确认上传？",
        },
    )

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
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
            "tool": "upload_strava_activity",
            "input": {"force": True},
        },
    )

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient"):
        with patch("agent.workflow.tool_loop.route_intent") as mock_route:
            with patch("agent.workflow.executor.upload_to_strava_tool") as mock_upload:
                with patch("agent.workflow.executor.AnthropicMessagesClient") as MockUploadLlm:
                    mock_upload.return_value = {"status": "uploaded", "strava_activity_id": 123}
                    MockUploadLlm.return_value.create_message.return_value = {
                        "content": [{"type": "text", "text": "上传成功"}],
                        "stop_reason": "end_turn",
                    }
                    result = run_tool_loop("再试一次", context=context)

    assert result["status"] == "completed"
    assert result["intent"] == "retry"
    assert result["steps"] == [{"tool": "upload_strava_activity", "input": {"force": True}}]
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
            "content": [{"type": "tool_use", "name": "resolve_recent_activities", "id": "tu-1", "input": {"limit": 1}}],
            "stop_reason": "tool_use",
        }

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.side_effect = fake_create_messages
        result = run_tool_loop("分析", context=context)

    assert result["status"] == "max_steps_exceeded"
    assert result["steps"] is not None
    assert len(result["steps"]) > 0


def test_side_effect_returns_needs_confirmation():
    """LLM 请求 sync_garmin_activities 时返回 needs_confirmation."""
    context = AgentContext(session_id="test-sidefx")

    def fake_create_messages(**kwargs):
        return {
            "id": "msg-sync",
            "content": [{"type": "tool_use", "name": "sync_garmin_activities", "id": "tu-1", "input": {"count": 3}}],
            "stop_reason": "tool_use",
        }

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_messages.side_effect = fake_create_messages
        result = run_tool_loop("下载最近3条Garmin活动", context=context)

    assert result["status"] == "needs_confirmation"
    assert result["context"].pending_action is not None
    assert result["context"].pending_action["tool"] == "sync_garmin_activities"
    assert result["context"].pending_action["input"] == {"count": 3}


def test_hard_deny_does_not_create_pending_confirmation():
    """硬拒绝是不可确认的拒绝,不应写入 pending_action."""
    context = AgentContext(session_id="test-deny")
    DENY_LIST.append(("resolve_recent_activities", "测试硬拒绝"))
    responses = [
        {
            "id": "msg-deny",
            "content": [
                {
                    "type": "tool_use",
                    "name": "resolve_recent_activities",
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
        with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
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

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
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

    with patch("agent.workflow.tool_loop.AnthropicMessagesClient") as MockClient:
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
