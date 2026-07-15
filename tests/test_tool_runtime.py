from __future__ import annotations

from agent.context import AgentContext
from agent.main_agent.tools import TOOL_HANDLERS


def test_tool_handler_executes_resolution_directly(monkeypatch):
    called = {}

    def fake_resolution(name, args, context):
        called["step_name"] = name
        called["arguments"] = args
        return {"step": name, "status": "completed"}

    monkeypatch.setattr("agent.activity.resolution.executor.execute_activity_resolution_tool", fake_resolution)

    result = TOOL_HANDLERS["find_activity"](
        {"limit": 1},
        AgentContext(session_id="direct-tool"),
    )

    assert result == {
        "step": "find_activity",
        "status": "completed",
        "resolution_step": "resolve_recent_activities",
    }
    assert called == {"step_name": "resolve_recent_activities", "arguments": {"limit": 1}}
