"""CLI 入口:覆盖分析/上传/工作流/Strava 认证等操作.

通过 typer 注册,入口点为 python -m app.cli <command>.
"""

import json

import typer

from agent.workflow_runner import run_planned_workflow
from agent.fit_paths import resolve_fit_path
from agent.tools.workflow import MAX_SYNC_COUNT, analyze_fit_file_tool, sync_garmin_activities_tool
from core.strava_workflow import (
    update_strava_description_from_summary,
    upload_summary_to_strava,
)
from sinks.strava import StravaSink


app = typer.Typer(help="Personal FIT Agent CLI")


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
    if result.get("log_path"):
        typer.echo(f"workflow_log_md: {result['log_path']}")
    if result.get("current_fit_file"):
        typer.echo(f"current_fit_file: {result['current_fit_file']}")


@app.command("analyze-file")
def analyze_file_command(
    path: str = typer.Argument("latest"),
    force: bool = False,
) -> None:
    fit = resolve_fit_path(path)
    result = analyze_fit_file_tool(str(fit), force=force)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("sync-garmin")
def sync_garmin_command(
    count: int = typer.Option(
        5,
        "--count",
        "-n",
        min=1,
        max=MAX_SYNC_COUNT,
        help=f"下载最近 N 条 Garmin 活动,最多 {MAX_SYNC_COUNT} 条.",
    ),
) -> None:
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


if __name__ == "__main__":
    app()
