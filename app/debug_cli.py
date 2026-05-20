"""开发/调试 CLI:检查工具返回、FIT 解析和活动索引.

主 CLI(app.cli) 面向日常使用;这里保留偏底层的验证入口.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from agent.activity_resolution import ACTIVITY_RESOLUTION_STEPS, execute_activity_resolution_step
from agent.context import AgentContext
from agent.guided_chat import resolve_fit_path
from agent.planner import plan_initial_workflow
from agent.tools import agent_workflow_tool_catalog, call_fit_analysis_tool, fit_data_tool_catalog
from core.activity_index import (
    get_activities_in_range,
    list_activities,
    rebuild_activity_index,
    resolve_activity,
    upsert_activity_from_fit,
)
from core.history import query_activity_history
from fit.parser import parse_fit

app = typer.Typer(help="Personal FIT Agent debug CLI")


@app.command("list-tools")
def list_tools_command(all_tools: bool = True) -> None:
    """列出 LLM 可用工具."""
    tools = agent_workflow_tool_catalog() if all_tools else fit_data_tool_catalog()
    _echo_json({"count": len(tools), "tools": tools})


@app.command("plan-workflow")
def plan_workflow_command(
    message: str,
    fit_path: str | None = typer.Option(None, "--fit", help="可选:当前 FIT 文件路径或 latest."),
    history: bool = True,
    include_payload: bool = False,
    max_tokens: int = typer.Option(4096, "--max-tokens", help="planner LLM 最大输出 token 数."),
    resolve_activities: bool = typer.Option(False, "--resolve-activities", help="只执行 activity_resolution 步骤以定位活动."),
) -> None:
    """调用 LLM planner 生成初始工作流计划,不执行任何步骤."""
    current_fit = resolve_fit_path(fit_path) if fit_path else None
    context = AgentContext(
        session_id="debug_planner",
        current_fit_file=current_fit,
        history_enabled=history,
    )
    result = plan_initial_workflow(message, context, max_tokens=max_tokens)
    output = {
        "plan": result["plan_json"],
        "raw_text": result["raw_text"],
    }
    if resolve_activities:
        resolution_results = []
        for step in result["plan"].steps:
            if step.name in ACTIVITY_RESOLUTION_STEPS:
                resolution_results.append(execute_activity_resolution_step(step, context))
        output["activity_resolution_results"] = resolution_results
        output["selected_activities"] = context.selected_activities
        output["selected_activity_range"] = context.selected_activity_range
    if include_payload:
        output["payload"] = result["payload"]
    _echo_json(output)


@app.command("tool-call")
def tool_call_command(
    name: str,
    fit_path: str | None = typer.Option(None, "--fit", help="需要当前 FIT 的数据工具可传 latest 或路径."),
    args: str = typer.Option("{}", "--args", help="JSON object 参数."),
    history: bool = True,
) -> None:
    """直接调用一个 agent tool,用于检查返回 payload."""
    arguments = _parse_args_json(args)
    parsed = None
    history_before = None
    if fit_path:
        fit = resolve_fit_path(fit_path)
        parsed = parse_fit(fit)
        if history:
            summary = parsed.get("summary") or {}
            before = summary.get("start_time_local") or summary.get("start_time")
            history_before = query_activity_history(before=before, days=90, limit=50)

    result = call_fit_analysis_tool(name, arguments, parsed=parsed, history_before=history_before)
    _echo_json(result)


@app.command("inspect-fit")
def inspect_fit_command(
    fit_path: str = typer.Argument("latest"),
    tool_name: str | None = typer.Argument(None),
    args: str = typer.Option("{}", "--args", help="可选:调用数据工具时传入的 JSON object 参数."),
    history: bool = typer.Option(True, "--history/--no-history", help="调用 get_history 等数据工具时是否带历史上下文."),
) -> None:
    """解析 FIT;如果传 tool_name,则直接调用对应只读数据工具."""
    fit = resolve_fit_path(fit_path)
    parsed = parse_fit(fit)
    if tool_name:
        history_before = None
        if history:
            summary_for_history = parsed.get("summary") or {}
            before = summary_for_history.get("start_time_local") or summary_for_history.get("start_time")
            history_before = query_activity_history(before=before, days=90, limit=50)
        result = call_fit_analysis_tool(
            tool_name,
            _parse_args_json(args),
            parsed=parsed,
            history_before=history_before,
        )
        _echo_json({
            "fit_path": str(fit),
            **result,
        })
        return

    summary = parsed.get("summary") or {}
    metadata = parsed.get("training_metadata") or {}
    _echo_json({
        "fit_path": str(fit),
        "summary": summary,
        "record_count": len(parsed.get("records") or []),
        "lap_count": len(parsed.get("laps") or []),
        "session_count": len(parsed.get("sessions") or []),
        "training_message_counts": metadata.get("message_counts"),
    })


@app.command("index-fit")
def index_fit_command(fit_path: str = typer.Argument("latest"), source: str = "manual") -> None:
    """把一个 FIT 文件登记到 data/activity_index.json."""
    fit = resolve_fit_path(fit_path)
    _echo_json(upsert_activity_from_fit(fit, source=source))


@app.command("rebuild-index")
def rebuild_index_command() -> None:
    """扫描本地 FIT 和 summary,重建 data/activity_index.json."""
    _echo_json(rebuild_activity_index())


@app.command("list-activities")
def list_activities_command(limit: int = 20, sport_type: str | None = None, order: str = "latest") -> None:
    _echo_json(list_activities(limit=limit, sport_type=sport_type, order=order))


@app.command("resolve-activity")
def resolve_activity_command(
    date_local: str | None = None,
    name: str | None = None,
    activity_key: str | None = None,
    activity_index: int | None = None,
    sport_type: str | None = None,
    match: str = "latest",
) -> None:
    _echo_json(resolve_activity(
        activity_key=activity_key,
        activity_index=activity_index,
        date_local=date_local,
        name=name,
        sport_type=sport_type,
        match=match,
    ))


@app.command("activities-in-range")
def activities_in_range_command(
    start_date: str,
    end_date: str,
    sport_type: str | None = None,
) -> None:
    _echo_json(get_activities_in_range(start_date=start_date, end_date=end_date, sport_type=sport_type))


def _parse_args_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--args must be JSON object: {exc}") from exc
    if not isinstance(data, dict):
        raise typer.BadParameter("--args must be JSON object")
    return data


def _echo_json(data: Any) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    app()
