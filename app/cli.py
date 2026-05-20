"""CLI 入口:11 个命令,覆盖分析/上传/对话/Strava 认证等操作.

通过 typer 注册,入口点为 python -m app.cli <command>.
"""

import json

import typer

from agent.chat_logger import readable_chat_log_path
from agent.guided_chat import GuidedActivityChatSession, direct_fit_analysis, resolve_fit_path
from agent.workflow_chat import run_workflow_agent
from agent.workflow_runner import run_planned_workflow
from core.file_workflow import analyze_fit_file
from core.workflow_tools import sync_garmin_activities_tool
from core.strava_workflow import (
    update_strava_description_from_summary,
    upload_summary_to_strava,
)
from sinks.strava import StravaSink


app = typer.Typer(help="Personal FIT Agent CLI")


@app.command("agent")
def agent_command(
    message: str,
    fit_path: str | None = typer.Option(
        None,
        "--fit",
        help="可选:当前 FIT 文件路径或 latest.提供后可调用数据查询工具.",
    ),
    history: bool = True,
    max_steps: int = 8,
) -> None:
    """运行完整工具集 agent:数据查询 + Garmin 下载 + FIT 分析 + Strava 上传."""
    result = run_workflow_agent(
        message,
        fit_path=fit_path,
        use_history=history,
        max_steps=max_steps,
    )
    typer.echo(result["answer"])
    if result.get("log_path"):
        typer.echo("")
        _echo_log_paths(result["log_path"])
    if result.get("current_fit_file"):
        typer.echo(f"current_fit_file: {result['current_fit_file']}")


@app.command("workflow")
def workflow_command(
    message: str,
    fit_path: str | None = typer.Option(
        None,
        "--fit",
        help="可选:当前 FIT 文件路径或 latest.",
    ),
    history: bool = True,
    max_tokens: int = typer.Option(4096, "--max-tokens", help="planner LLM 最大输出 token 数."),
    json_output: bool = typer.Option(False, "--json", help="输出完整 plan/execution JSON."),
    include_details: bool = typer.Option(False, "--include-details", help="JSON 输出中包含 planner 原文和 payload."),
) -> None:
    """运行新规划执行链路:Planner -> Validator -> Selector -> Executor."""
    result = run_planned_workflow(
        message,
        fit_path=fit_path,
        use_history=history,
        max_tokens=max_tokens,
        include_details=include_details,
    )
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    typer.echo(result["answer"])
    typer.echo("")
    typer.echo(f"workflow_status: {result['status']}")
    if result.get("current_fit_file"):
        typer.echo(f"current_fit_file: {result['current_fit_file']}")


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


@app.command("sync-garmin")
def sync_garmin_command(count: int = typer.Option(5, "--count", "-n", help="下载最近 N 条 Garmin 活动,最多 20 条.")) -> None:
    """下载 Garmin 中国区最近活动 FIT 文件,自动跳过本地已有文件."""
    result = sync_garmin_activities_tool(count=count)
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
