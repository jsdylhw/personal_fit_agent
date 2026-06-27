"""run_tool_loop 控制流单测:确认、max_steps、pending 直接执行."""

from __future__ import annotations

from unittest.mock import patch

from agent.context import AgentContext
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
