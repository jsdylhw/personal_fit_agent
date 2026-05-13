import json

import typer

from agent.chat import ActivityChatSession, chat, preview_chat_payload
from agent.tool_loop import run_tool_loop
from agent.tools import call_tool, tool_catalog
from core.storage import list_activities
from core.workflow import analyze_activity, import_fit


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
    if result.get("report"):
        typer.echo("")
        typer.echo(f"已保存报告: analysis_report_id={result['report']['id']}")


@app.command("chat-shell")
def chat_shell_command(
    activity_id: str = "latest",
    history_days: int = 30,
    save_report: bool = False,
) -> None:
    typer.echo("进入多轮运动分析对话。输入 exit / quit 退出，Ctrl-D 也可以退出。")
    typer.echo(f"活动: {activity_id}; 历史窗口: {history_days} 天")
    session = ActivityChatSession(
        activity_id=activity_id,
        history_days=history_days,
        save_report=save_report,
    )
    while True:
        try:
            question = typer.prompt("你")
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
        if result.get("report"):
            typer.echo(f"\n已保存报告: analysis_report_id={result['report']['id']}")
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
    if result.get("error"):
        typer.echo("\n=== error ===")
        typer.echo(result["error"])


if __name__ == "__main__":
    app()
