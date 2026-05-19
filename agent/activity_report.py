"""基于已有 summary.json 展示单活动报告."""

from __future__ import annotations

from typing import Any

from agent.activity_comparison import read_activity_summary
from agent.context import AgentContext
from agent.plan_schema import WorkflowPlanStep


def show_selected_activity_report(
    step: WorkflowPlanStep,
    context: AgentContext,
) -> dict[str, Any]:
    """读取当前或已选活动的已有报告,不重新分析 FIT."""
    activity = _selected_activity(context)
    if not activity:
        return {
            "error": "missing_selected_activity",
            "message": "analyze_single_activity requires a resolved activity.",
        }

    summary_path, summary, error = read_activity_summary(activity)
    if error or summary is None:
        return {
            "error": error or "missing_activity_summary",
            "message": "Selected activity does not have a readable summary report.",
            "activity": activity,
        }

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
        "step": step.name,
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
