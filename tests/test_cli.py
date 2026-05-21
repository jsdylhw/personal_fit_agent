from __future__ import annotations

from typer.testing import CliRunner

from app.cli import app


def test_cli_exposes_workflow_command_and_removes_old_agent_command():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "workflow" in result.output
    assert " agent " not in result.output

    missing = CliRunner().invoke(app, ["agent", "你好"])
    assert missing.exit_code != 0


def test_sync_garmin_command_calls_workflow_tool(monkeypatch):
    captured: dict[str, int] = {}

    def fake_sync_garmin_activities_tool(count: int):
        captured["count"] = count
        return {"status": "ok", "downloaded": 0, "skipped": 1}

    monkeypatch.setattr("app.cli.sync_garmin_activities_tool", fake_sync_garmin_activities_tool)

    result = CliRunner().invoke(app, ["sync-garmin", "--count", "3"])

    assert result.exit_code == 0
    assert captured["count"] == 3
    assert '"status": "ok"' in result.output
