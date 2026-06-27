from __future__ import annotations

from typer.testing import CliRunner

from app.cli import app


def test_cli_exposes_workflow_command_and_removes_old_agent_command():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "workflow" in result.output
    assert " agent " not in result.output
    assert "fit-ask" not in result.output
    assert "fit-chat" not in result.output

    missing = CliRunner().invoke(app, ["agent", "你好"])
    assert missing.exit_code != 0
    assert CliRunner().invoke(app, ["fit-ask"]).exit_code != 0
    assert CliRunner().invoke(app, ["fit-chat"]).exit_code != 0


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


def test_analyze_file_command_uses_workflow_tool_and_resolves_path(tmp_path, monkeypatch):
    fit = tmp_path / "activity.fit"
    fit.write_bytes(b"fit")
    captured = {}

    def fake_analyze_fit_file_tool(path: str, *, force: bool = False):
        captured["path"] = path
        captured["force"] = force
        return {"status": "ok", "fit_path": path}

    monkeypatch.setattr("app.cli.analyze_fit_file_tool", fake_analyze_fit_file_tool)

    result = CliRunner().invoke(app, ["analyze-file", str(fit), "--force"])

    assert result.exit_code == 0
    assert captured == {"path": str(fit.resolve()), "force": True}
    assert '"status": "ok"' in result.output


def test_workflow_command_prints_markdown_log_path(monkeypatch):
    def fake_run_tool_loop(*args, **kwargs):
        return {
            "answer": "整体总结",
            "status": "completed",
            "log_path": "log/tool_loop_test.md",
            "current_fit_file": None,
        }

    monkeypatch.setattr("app.cli.run_tool_loop", fake_run_tool_loop)

    result = CliRunner().invoke(app, ["workflow", "分析所有历史活动"])

    assert result.exit_code == 0
    assert "整体总结" in result.output
    assert "workflow_log_md: log/tool_loop_test.md" in result.output
    assert "chat_log_jsonl" not in result.output
