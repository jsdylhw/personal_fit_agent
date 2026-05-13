import json

import typer

from agent.chat import ActivityChatSession, chat, preview_chat_payload
from agent.tool_loop import run_tool_loop
from agent.tools import call_tool, tool_catalog
from core.file_workflow import analyze_fit_file, analyze_fit_folder
from core.storage import list_activities
from core.strava_workflow import (
    update_strava_description_from_summary,
    upload_summary_to_strava,
)
from core.workflow import analyze_activity, import_fit
from sinks.strava import StravaSink


app = typer.Typer(help="Personal FIT Agent CLI")


@app.command("import")
def import_command(path: str, source: str = "manual") -> None:
    activity = import_fit(path, source=source)
    typer.echo(json.dumps(activity, ensure_ascii=False, indent=2))


@app.command("list")
def list_command(limit: int = 20) -> None:
    typer.echo(json.dumps(list_activities(limit), ensure_ascii=False, indent=2))


@app.command("analyze")
def analyze_command(activity_id: str = "latest", plot: bool = True) -> None:
    result = analyze_activity(activity_id, make_plot=plot)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("analyze-file")
def analyze_file_command(
    path: str,
    history: bool = False,
    plot: bool = False,
    force: bool = False,
) -> None:
    result = analyze_fit_file(
        path,
        use_history=history,
        make_plot=plot,
        force=force,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("analyze-folder")
def analyze_folder_command(
    folder: str,
    history: bool = True,
    plot: bool = False,
    force: bool = False,
) -> None:
    result = analyze_fit_folder(
        folder,
        use_history=history,
        make_plot=plot,
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


@app.command("tools-catalog")
def tools_catalog_command() -> None:
    typer.echo(json.dumps(tool_catalog(), ensure_ascii=False, indent=2))


@app.command("tool-call")
def tool_call_command(name: str, arguments_json: str = typer.Argument("{}")) -> None:
    arguments = json.loads(arguments_json)
    try:
        result = call_tool(name, arguments)
    except KeyError as exc:
        raise typer.BadParameter(str(exc), param_hint="name") from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("chat")
def chat_command(
    question: str,
    mode: str = "auto",
    activity_id: str = "latest",
    history_days: int = 30,
    save_report: bool = False,
) -> None:
    result = chat(
        question,
        mode=mode,
        activity_id=activity_id,
        history_days=history_days,
        save_report=save_report,
    )
    typer.echo(result["answer"])
    if result.get("log_path"):
        typer.echo("")
        typer.echo(f"chat_log: {result['log_path']}")
    if result.get("report"):
        typer.echo("")
        typer.echo(f"analysis_report_id={result['report']['id']}")


@app.command("chat-shell")
def chat_shell_command(
    activity_id: str = "latest",
    history_days: int = 30,
    save_report: bool = False,
) -> None:
    typer.echo("Interactive chat started. Type exit / quit, or press Ctrl-D to leave.")
    typer.echo(f"activity_id: {activity_id}; history_days: {history_days}")
    session = ActivityChatSession(
        activity_id=activity_id,
        history_days=history_days,
        save_report=save_report,
    )
    while True:
        try:
            question = typer.prompt("You")
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            break
        if question.strip().lower() in {"exit", "quit", "q"}:
            break
        if not question.strip():
            continue
        result = session.ask(question)
        typer.echo("")
        typer.echo("AI>")
        typer.echo(result["answer"])
        if result.get("log_path"):
            typer.echo(f"\nchat_log: {result['log_path']}")
        if result.get("report"):
            typer.echo(f"\nanalysis_report_id={result['report']['id']}")
        typer.echo("")


@app.command("chat-payload")
def chat_payload_command(
    question: str,
    mode: str = "auto",
    activity_id: str = "latest",
    history_days: int = 30,
) -> None:
    payload = preview_chat_payload(
        question,
        mode=mode,
        activity_id=activity_id,
        history_days=history_days,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


@app.command("chat-tools")
def chat_tools_command(
    question: str,
    max_steps: int = 8,
    json_logs: bool = False,
) -> None:
    result = run_tool_loop(question, max_steps=max_steps)
    if json_logs:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    for log in result.get("logs", []):
        typer.echo(f"\n--- step {log.get('step')} / {log.get('type')} ---")
        if log.get("type") == "llm_response":
            typer.echo("raw:")
            typer.echo(log.get("raw_text", ""))
            typer.echo("parsed:")
            typer.echo(json.dumps(log.get("parsed"), ensure_ascii=False, indent=2, default=str))
        elif log.get("type") == "tool_result":
            typer.echo(json.dumps(log, ensure_ascii=False, indent=2, default=str))

    if result.get("answer"):
        typer.echo("\n=== final answer ===")
        typer.echo(result["answer"])
    if result.get("log_path"):
        typer.echo("\n=== chat log ===")
        typer.echo(result["log_path"])
    if result.get("error"):
        typer.echo("\n=== error ===")
        typer.echo(result["error"])


if __name__ == "__main__":
    app()
