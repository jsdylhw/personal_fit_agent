"""CLI 入口:覆盖分析/上传/工作流/Strava 认证等操作.

通过 typer 注册,入口点为 python -m app.cli <command>.
"""

import json

import typer

from agent.workflow.runner import run_planned_workflow
from agent.workflow.tool_loop import run_tool_loop
from core.fit_paths import resolve_fit_path
from agent.workflow.handlers.ops import MAX_SYNC_COUNT, analyze_fit_file_tool, sync_garmin_activities_tool
from core.strava_workflow import (
    update_strava_description_from_summary,
    upload_summary_to_strava,
)
from sinks.strava import StravaSink


app = typer.Typer(help="Personal FIT Agent CLI")


# -- chat helpers -----------------------------------------------------------

def _chat_once(
    message: str,
    *,
    fit_path: str | None = None,
    max_tokens: int = 4096,
) -> None:
    """单次对话 — 调用 tool loop 并打印结果."""
    result = run_tool_loop(
        message,
        fit_path=fit_path,
        use_history=True,
        max_tokens=max_tokens,
        verbose=True,
    )

    typer.echo("")
    typer.echo(result["answer"])
    typer.echo("")
    typer.echo(f"\033[2mstatus: {result['status']} | intent: {result.get('intent', '?')}\033[0m")
    typer.echo("")


@app.command("workflow")
def workflow_command(
    message: str,
    fit_path: str | None = typer.Option(
        None,
        "--fit",
        help="可选:当前 FIT 文件路径或 latest.",
    ),
    history: bool = True,
    max_tokens: int = typer.Option(4096, "--max-tokens", help="LLM 最大输出 token 数."),
    json_output: bool = typer.Option(False, "--json", help="输出完整 plan/execution JSON."),
    include_details: bool = typer.Option(False, "--include-details", help="JSON 输出中包含 planner 原文和 payload."),
    tool_use: bool = typer.Option(False, "--tool-use", help="使用新的原生 tool use 链路 (Intent Router + Allowlist + Guard)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="打印 tool 调用过程日志."),
) -> None:
    """运行 workflow: Planner -> Validator -> Selector -> Executor (旧) 或 Intent Router -> Tool Use Loop (新)."""
    if tool_use:
        result = run_tool_loop(
            message,
            fit_path=fit_path,
            use_history=history,
            max_tokens=max_tokens,
            verbose=verbose,
        )
    else:
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
    if result.get("intent"):
        typer.echo(f"intent: {result['intent']}")


@app.command("chat")
def chat_command(
    message: str | None = typer.Argument(None, help="单次对话内容。不传则进入交互模式。"),
    fit_path: str | None = typer.Option(None, "--fit", help="可选:当前 FIT 文件路径或 latest."),
    max_tokens: int = typer.Option(4096, "--max-tokens", help="LLM 最大输出 token 数."),
) -> None:
    """对话模式 — 原生 tool use + tool 调用日志。不传 message 进入交互模式，q/quit 退出。"""
    if message:
        _chat_once(message, fit_path=fit_path, max_tokens=max_tokens)
        return

    # 交互模式
    typer.echo("Personal FIT Agent (chat mode) — 输入 q/quit 退出")
    history: list[dict[str, Any]] = []
    while True:
        try:
            user_input = typer.prompt(">").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            break

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            break

        _chat_once(user_input, fit_path=fit_path, max_tokens=max_tokens)


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
    force: bool = typer.Option(False, "--force", help="遇到重复活动时不报错,改为更新已有活动的描述"),
) -> None:
    result = upload_summary_to_strava(summary_path, title=title, wait=wait, force=force)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("update-strava-description")
def update_strava_description_command(activity_id: str, summary_path: str) -> None:
    result = update_strava_description_from_summary(activity_id, summary_path)
    typer.echo(f"已更新 Strava 活动 {activity_id} 的描述。")
    detail = result.get("description")
    if detail:
        typer.echo(f"描述长度: {len(detail)} 字符")


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
