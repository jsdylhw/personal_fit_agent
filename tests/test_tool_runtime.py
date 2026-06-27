from __future__ import annotations

from agent.context import AgentContext
from agent.workflow.tool_runtime import run_tool_step


def test_run_tool_step_executes_resolution_directly(monkeypatch):
    called = {}

    def fake_resolution(name, args, context):
        called["step_name"] = name
        called["arguments"] = args
        return {"step": name, "status": "completed"}

    monkeypatch.setattr("agent.activity.resolution.executor.execute_activity_resolution_tool", fake_resolution)

    result = run_tool_step("resolve_recent_activities", {"limit": 1}, AgentContext(session_id="direct-tool"))

    assert result == {"step": "resolve_recent_activities", "status": "completed"}
    assert called == {"step_name": "resolve_recent_activities", "arguments": {"limit": 1}}
