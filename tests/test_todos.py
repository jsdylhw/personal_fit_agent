from __future__ import annotations

from agent.context import AgentContext
from agent.workflow.hooks import ToolLoopHooks
from agent.workflow.todos import format_todos_for_terminal, normalize_todos, write_todos


def test_write_todos_updates_context_and_resets_round_counter():
    context = AgentContext(session_id="todo-test", todo_rounds_since_update=2)

    result = write_todos(
        context,
        [
            {"content": "分析最近活动", "status": "in_progress"},
            {"content": "总结训练建议", "status": "pending"},
        ],
    )

    assert result["status"] == "updated"
    assert context.current_todos[0] == {"content": "分析最近活动", "status": "in_progress"}
    assert context.todo_rounds_since_update == 0


def test_normalize_todos_rejects_invalid_status():
    todos, error = normalize_todos([{"content": "x", "status": "doing"}])

    assert todos == []
    assert "invalid status" in (error or "")


def test_todo_reminder_hook_returns_message_after_threshold():
    context = AgentContext(
        session_id="todo-reminder-test",
        current_todos=[{"content": "分析活动", "status": "in_progress"}],
        todo_rounds_since_update=3,
    )
    hooks = ToolLoopHooks(context, {"planning"}, {"value": False}, [])

    reminder = hooks.before_llm_call()

    assert isinstance(reminder, dict)
    assert reminder["role"] == "user"
    assert "todo_write" in reminder["content"]
    assert context.todo_rounds_since_update == 0


def test_format_todos_for_terminal_matches_s05_style():
    text = format_todos_for_terminal([
        {"content": "定位最后一个活动", "status": "completed"},
        {"content": "重新分析", "status": "in_progress"},
        {"content": "上传 Strava", "status": "pending"},
    ])

    assert "## Current Tasks" in text
    assert "✓" in text
    assert "▸" in text
    assert "上传 Strava" in text
