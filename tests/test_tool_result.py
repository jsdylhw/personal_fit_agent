from __future__ import annotations

from agent.context import AgentContext
from agent.workflow.tool_result import is_failed_tool_output, remember_failed_action


def test_detects_nested_upload_error_as_failed():
    output = {
        "result": {
            "upload_result": {
                "error": "SSLError",
                "message": "network failed",
            },
        },
    }

    assert is_failed_tool_output(output) is True


def test_remember_failed_action_clears_after_same_tool_succeeds():
    context = AgentContext(session_id="tool-result-test")

    remember_failed_action(context, "upload_strava_activity", {"force": True}, {"error": "SSLError"})
    assert context.last_failed_action == {
        "tool": "upload_strava_activity",
        "input": {"force": True},
    }

    remember_failed_action(context, "upload_strava_activity", {"force": True}, {"status": "uploaded"})
    assert context.last_failed_action is None
