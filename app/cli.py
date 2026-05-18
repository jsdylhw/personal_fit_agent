"""CLI 入口:11 个命令,覆盖分析/上传/对话/Strava 认证等操作.

通过 typer 注册,入口点为 python -m app.cli <command>.
"""

import json

import typer

from agent.chat_logger import readable_chat_log_path
from agent.guided_chat import GuidedActivityChatSession, direct_fit_analysis, resolve_fit_path
from core.file_workflow import analyze_fit_file
from core.strava_workflow import (
    update_strava_description_from_summary,
    upload_summary_to_strava,
)
from sinks.strava import StravaSink


app = typer.Typer(help="Personal FIT Agent CLI")


@app.command("analyze-file")
def analyze_file_command(
    path: str,
    history: bool = False,
    force: bool = False,
) -> None:
    result = analyze_fit_file(
        path,
        use_history=history,
        force=force,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("upload-strava")
def upload_strava_command(
    summary_path: str,
    title: str | None = None,
    wait: bool = True,
) -> None:
    result = upload_summary_to_strava(summary_path, title=title, wait=wait)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("update-strava-description")
def update_strava_description_command(activity_id: str, summary_path: str) -> None:
    result = update_strava_description_from_summary(activity_id, summary_path)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("strava-auth-url")
def strava_auth_url_command(
    redirect_uri: str = "http://localhost",
    scope: str = "activity:read_all,activity:write",
) -> None:
    typer.echo(StravaSink().build_authorize_url(redirect_uri=redirect_uri, scope=scope))


@app.command("strava-exchange-code")
def strava_exchange_code_command(code: str) -> None:
    result = StravaSink().exchange_authorization_code(code)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("strava-check-auth")
def strava_check_auth_command() -> None:
    athlete = StravaSink().get_athlete()
    safe = {
        key: athlete.get(key)
        for key in ["id", "username", "firstname", "lastname", "city", "country"]
        if key in athlete
    }
    typer.echo(json.dumps(safe, ensure_ascii=False, indent=2, default=str))


@app.command("fit-ask")
def fit_ask_command(
    fit_path: str,
    question: str,
    history: bool = True,
    update_summary: bool = False,
) -> None:
    result = direct_fit_analysis(
        fit_path, question, use_history=history, update_summary=update_summary,
    )
    typer.echo(result["answer"])
    if result.get("log_path"):
        typer.echo("")
        _echo_log_paths(result["log_path"])
    if result.get("summary_path"):
        typer.echo(f"summary_path: {result['summary_path']}")


@app.command("fit-chat")
def fit_chat_command(
    fit_path: str = typer.Argument("latest"),
    history: bool = True,
    update_summary: bool = True,
) -> None:
    resolved_fit = resolve_fit_path(fit_path)
    session = GuidedActivityChatSession(resolved_fit, use_history=history)

    typer.echo("Guided activity chat started. Type /final to generate the final summary.")
    typer.echo("Commands: /final [extra instruction], /help, /exit")
    typer.echo(f"fit_path: {resolved_fit}")
    typer.echo("")

    opening = session.start()
    typer.echo("AI>")
    typer.echo(opening["answer"])
    typer.echo("")

    while True:
        try:
            question = typer.prompt("You")
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            break

        text = question.strip()
        if not text:
            continue
        if text.lower() in {"/exit", "/quit", "exit", "quit", "q"}:
            break
        if text.lower() == "/help":
            typer.echo("Use /final to generate the guided summary. Use /exit to leave.")
            continue
        if text.lower().startswith("/final"):
            extra = text[len("/final") :].strip() or None
            result = session.finalize(extra, update_summary=update_summary)
            typer.echo("")
            typer.echo("AI>")
            typer.echo(result["answer"])
            if result.get("log_path"):
                _echo_log_paths(result["log_path"])
            if result.get("summary_path"):
                typer.echo(f"summary_path: {result['summary_path']}")
            break

        result = session.ask(text)
        typer.echo("")
        typer.echo("AI>")
        typer.echo(result["answer"])
        if result.get("log_path"):
            typer.echo("")
            _echo_log_paths(result["log_path"])
        typer.echo("")


def _echo_log_paths(log_path: str) -> None:
    typer.echo(f"chat_log_jsonl: {log_path}")
    typer.echo(f"chat_log_md: {readable_chat_log_path(log_path)}")


if __name__ == "__main__":
    app()
