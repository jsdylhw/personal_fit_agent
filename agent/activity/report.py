"""基于已有 summary.json 展示单活动报告."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.activity.analysis_agent import run_activity_analysis_agent
from agent.activity.comparison import read_activity_summary
from agent.context import AgentContext


def show_selected_activity_report_tool(
    context: AgentContext,
    *,
    args: dict[str, Any] | None = None,
    name: str = "analyze_activity",
) -> dict[str, Any]:
    """展示单活动报告;无 summary 但有 FIT 时触发文件分析工具链路."""
    args = args or {}
    activity = _selected_activity(context)
    if not activity:
        return {
            "error": "missing_selected_activity",
            "message": "analyze_activity requires a resolved activity.",
        }

    summary_path, summary, error = read_activity_summary(activity)
    if bool(args.get("force")) and isinstance(summary, dict):
        refreshed_activity = {
            **activity,
            "fit_path": activity.get("fit_path") or summary.get("fit_path"),
            "summary_path": str(summary_path) if summary_path else activity.get("summary_path"),
            "activity_key": activity.get("activity_key") or summary.get("activity_key"),
        }
        generated = _analyze_missing_summary(name, args, context, refreshed_activity)
        if generated.get("error"):
            return generated
        return generated

    if error or summary is None:
        generated = _analyze_missing_summary(name, args, context, activity)
        if generated.get("error"):
            return generated
        return generated

    report = str(summary.get("markdown_report") or "").strip()
    if not report:
        history_entry = summary.get("history_entry") if isinstance(summary.get("history_entry"), dict) else {}
        report = _fallback_report(history_entry)

    if not report:
        return {
            "error": "missing_markdown_report",
            "message": "Summary exists but does not contain markdown_report or history_entry.",
            "summary_path": str(summary_path) if summary_path else None,
        }

    return {
        "step": name,
        "status": "completed",
        "answer": report,
        "result": {
            "schema_version": "activity_report.v1",
            "activity_key": summary.get("activity_key") or activity.get("activity_key"),
            "fit_path": summary.get("fit_path") or activity.get("fit_path"),
            "summary_path": str(summary_path) if summary_path else None,
            "source": "existing_summary",
            "fit_summary": summary.get("fit_summary") if isinstance(summary.get("fit_summary"), dict) else {},
            "history_entry": summary.get("history_entry") if isinstance(summary.get("history_entry"), dict) else {},
        },
    }


def query_selected_activity_detail_tool(
    context: AgentContext,
    *,
    question: str,
    name: str = "query_activity_detail",
) -> dict[str, Any]:
    """Answer a FIT-level question, creating the normal summary first when absent."""
    if not question:
        return {"error": "missing_question", "message": "query_activity_detail requires a concrete question."}
    activity = _selected_activity(context)
    if not activity:
        return {"error": "missing_selected_activity", "message": "query_activity_detail requires a resolved activity."}

    summary_path, summary, error = read_activity_summary(activity)
    if error or summary is None:
        generated = _analyze_missing_summary(name, {}, context, activity)
        if generated.get("error"):
            return generated
        summary_path, summary, error = read_activity_summary({
            **activity,
            "summary_path": generated.get("result", {}).get("summary_path"),
        })
        if error or not isinstance(summary, dict):
            return {
                "error": "missing_summary_after_analysis",
                "message": "完整报告生成后无法读取 summary，无法继续定向查询。",
            }
    return _answer_targeted_question(name, context, activity, summary, summary_path, question)


def _answer_targeted_question(
    name: str,
    context: AgentContext,
    activity: dict[str, Any],
    summary: dict[str, Any],
    summary_path: Path | None,
    user_request: str,
) -> dict[str, Any]:
    """Answer a new question without overwriting the cached full report."""
    fit_path = activity.get("fit_path") or summary.get("fit_path")
    if not fit_path:
        return {
            "error": "missing_fit_path",
            "message": "A focused activity question requires the original FIT file.",
            "summary_path": str(summary_path) if summary_path else None,
        }

    analysis = run_activity_analysis_agent(
        str(fit_path),
        user_request=user_request,
        persist=False,
    )
    report = str(analysis.get("markdown_report") or "").strip()
    if not report:
        return {
            "error": "missing_markdown_report",
            "message": "Focused analysis did not return markdown_report.",
            "analysis": analysis,
        }
    return {
        "step": name,
        "status": "completed",
        "answer": report,
        "result": {
            "schema_version": "activity_report.v1",
            "activity_key": analysis.get("activity_key") or activity.get("activity_key"),
            "fit_path": analysis.get("fit_path") or fit_path,
            "summary_path": str(summary_path) if summary_path else analysis.get("summary_path"),
            "source": "targeted_query",
            "status": analysis.get("status"),
            "agent": analysis.get("agent"),
            "analysis_error": analysis.get("analysis_error") if isinstance(analysis.get("analysis_error"), dict) else None,
            "history_entry": analysis.get("history_entry") if isinstance(analysis.get("history_entry"), dict) else {},
        },
    }


def _analyze_missing_summary(
    name: str,
    args: dict[str, Any],
    context: AgentContext,
    activity: dict[str, Any],
) -> dict[str, Any]:
    fit_path = activity.get("fit_path") or (str(context.current_fit_file) if context.current_fit_file else None)
    if not fit_path:
        return {
            "error": "missing_activity_summary",
            "message": "Selected activity does not have a readable summary report or FIT path.",
            "activity": activity,
        }

    analysis = run_activity_analysis_agent(
        str(fit_path),
        force=bool(args.get("force")),
        user_request=str(args.get("user_request") or ""),
    )
    report = str(analysis.get("markdown_report") or "").strip()
    if not report:
        return {
            "error": "missing_markdown_report",
            "message": "File analysis completed but did not return markdown_report.",
            "activity": activity,
            "analysis": analysis,
        }

    summary_path = analysis.get("summary_path")
    context.current_fit_file = Path(str(analysis.get("fit_path") or fit_path)).expanduser()
    context.current_activity_key = analysis.get("activity_key") or activity.get("activity_key")
    if summary_path:
        context.current_summary_path = Path(str(summary_path)).expanduser()

    source = "analysis_agent_error" if analysis.get("analysis_error") else "generated_summary"
    return {
        "step": name,
        "status": "completed",
        "answer": report,
        "result": {
            "schema_version": "activity_report.v1",
            "activity_key": analysis.get("activity_key") or activity.get("activity_key"),
            "fit_path": analysis.get("fit_path") or fit_path,
            "summary_path": summary_path,
            "source": source,
            "status": analysis.get("status"),
            "agent": analysis.get("agent"),
            "analysis_error": analysis.get("analysis_error") if isinstance(analysis.get("analysis_error"), dict) else None,
            "history_entry": analysis.get("history_entry") if isinstance(analysis.get("history_entry"), dict) else {},
        },
    }


def _selected_activity(context: AgentContext) -> dict[str, Any] | None:
    if context.selected_activities:
        first = context.selected_activities[0]
        return first if isinstance(first, dict) else None
    if context.current_fit_file or context.current_activity_key or context.current_summary_path:
        return {
            "activity_key": context.current_activity_key,
            "fit_path": str(context.current_fit_file) if context.current_fit_file else None,
            "summary_path": str(context.current_summary_path) if context.current_summary_path else None,
        }
    return None


def _fallback_report(history_entry: dict[str, Any]) -> str:
    if not history_entry:
        return ""
    lines = [
        f"# {history_entry.get('summary_label') or '活动报告'}",
        "",
        f"- 时间: {history_entry.get('start_time_local') or history_entry.get('start_time') or '未知'}",
        f"- 类型: {history_entry.get('sport_type') or '未知'}",
        f"- 距离: {history_entry.get('distance_km') or '未知'} km",
        f"- 时长: {history_entry.get('duration_min') or '未知'} 分钟",
        f"- 主要刺激: {history_entry.get('main_stimulus') or '未知'}",
        f"- 训练负荷: {history_entry.get('training_load') or '未知'}",
    ]
    brief = history_entry.get("brief")
    if brief:
        lines.extend(["", str(brief)])
    return "\n".join(lines)
