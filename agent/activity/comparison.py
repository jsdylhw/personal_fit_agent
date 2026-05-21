"""基于已有 summary.json 的多活动对比.

这里不重新解析 FIT,也不调用 LLM.它只读取已经生成的活动报告,把关键字段
整理成 executor 可消费的结构化对比结果.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.context import AgentContext
from agent.workflow.plan_schema import WorkflowPlanStep


def compare_selected_activities(
    step: WorkflowPlanStep,
    context: AgentContext,
) -> dict[str, Any]:
    """读取 context.selected_activities 的已有 summary 并生成对比结果."""
    activities = [
        activity
        for activity in context.selected_activities
        if isinstance(activity, dict)
    ]
    if len(activities) < 2:
        return {
            "error": "not_enough_activities",
            "message": "compare_activities requires at least two selected activities.",
        }

    loaded: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for activity in activities:
        summary_path = _resolve_summary_path(activity)
        if not summary_path:
            missing.append(_compact_missing_summary(activity))
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "error": "summary_read_failed",
                "message": f"failed to read summary: {summary_path}; {exc}",
            }
        loaded.append(_activity_report_from_summary(activity, summary_path, summary))

    if missing:
        return {
            "error": "missing_activity_summary",
            "message": "Some selected activities do not have readable summary files.",
            "missing": missing,
        }
    if len(loaded) < 2:
        return {
            "error": "not_enough_summaries",
            "message": "Need at least two readable summaries to compare activities.",
        }

    loaded = sorted(loaded, key=lambda item: str(item.get("start_time_local") or ""))
    comparison = _build_comparison(loaded)
    return {
        "step": step.name,
        "status": "completed",
        "result": comparison,
        "answer": _format_comparison_answer(comparison),
    }


def read_activity_summary(activity: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    """读取单条活动已有 summary,返回 path/data/error."""
    summary_path = _resolve_summary_path(activity)
    if not summary_path:
        return None, None, "missing_activity_summary"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return summary_path, None, f"summary_read_failed: {exc}"
    if not isinstance(summary, dict):
        return summary_path, None, "summary_must_be_object"
    return summary_path, summary, None


def _resolve_summary_path(activity: dict[str, Any]) -> Path | None:
    summary_path = activity.get("summary_path")
    if summary_path:
        path = Path(str(summary_path)).expanduser()
        if path.exists():
            return path

        # activity_index 可能来自 Windows 路径;在当前项目下用文件名回退查找.
        name = _path_name(str(summary_path))
        fallback = Path("data") / "summaries" / name
        if fallback.exists():
            return fallback

    fit_path = activity.get("fit_path")
    if fit_path:
        stem = _path_stem(str(fit_path))
        fallback = Path("data") / "summaries" / f"{stem}.summary.json"
        if fallback.exists():
            return fallback

    return None


def _activity_report_from_summary(
    activity: dict[str, Any],
    summary_path: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    fit_summary = summary.get("fit_summary") if isinstance(summary.get("fit_summary"), dict) else {}
    history_entry = summary.get("history_entry") if isinstance(summary.get("history_entry"), dict) else {}
    return {
        "activity_key": summary.get("activity_key") or activity.get("activity_key"),
        "file_name": activity.get("file_name") or _path_name(str(summary.get("fit_path") or "")),
        "summary_path": str(summary_path),
        "start_time_local": fit_summary.get("start_time_local") or history_entry.get("start_time_local"),
        "sport_type": fit_summary.get("sport_type") or history_entry.get("sport_type"),
        "duration_min": _number(history_entry.get("duration_min")),
        "distance_km": _number(history_entry.get("distance_km")),
        "summary_label": history_entry.get("summary_label"),
        "main_stimulus": history_entry.get("main_stimulus"),
        "training_load": history_entry.get("training_load"),
        "brief": history_entry.get("brief"),
        "quality_notes": history_entry.get("quality_notes") if isinstance(history_entry.get("quality_notes"), list) else [],
        "fit_summary": fit_summary,
    }


def _build_comparison(reports: list[dict[str, Any]]) -> dict[str, Any]:
    distances = [report.get("distance_km") for report in reports if report.get("distance_km") is not None]
    durations = [report.get("duration_min") for report in reports if report.get("duration_min") is not None]
    longest = max(reports, key=lambda item: float(item.get("distance_km") or 0))
    longest_duration = max(reports, key=lambda item: float(item.get("duration_min") or 0))
    higher_load = _higher_load_report(reports)
    return {
        "schema_version": "activity_comparison.v1",
        "count": len(reports),
        "activities": reports,
        "totals": {
            "distance_km": round(sum(float(value or 0) for value in distances), 2),
            "duration_min": round(sum(float(value or 0) for value in durations), 1),
        },
        "highlights": {
            "longest_distance_activity_key": longest.get("activity_key"),
            "longest_duration_activity_key": longest_duration.get("activity_key"),
            "higher_training_value_activity_key": higher_load.get("activity_key") if higher_load else None,
        },
        "training_judgement": _training_judgement(reports, higher_load),
    }


def _higher_load_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    def score(report: dict[str, Any]) -> tuple[float, float]:
        load_text = str(report.get("training_load") or "")
        label_score = 0.0
        if "非常轻" in load_text or "极低" in load_text:
            label_score = 1.0
        if "低" in load_text:
            label_score = max(label_score, 1.0)
        if "中" in load_text:
            label_score = max(label_score, 2.0)
        if "高" in load_text:
            label_score = max(label_score, 3.0)
        return label_score, float(report.get("duration_min") or 0)

    return max(reports, key=score) if reports else None


def _training_judgement(
    reports: list[dict[str, Any]],
    higher_load: dict[str, Any] | None,
) -> str:
    if not higher_load:
        return "已有报告不足以判断训练价值。"
    label = higher_load.get("summary_label") or higher_load.get("activity_key")
    load = higher_load.get("training_load") or "未知负荷"
    return f"相对更有训练价值的是 {label},主要因为它的时长/距离更高,报告负荷为 {load}。"


def _format_comparison_answer(comparison: dict[str, Any]) -> str:
    activities = comparison.get("activities") or []
    lines = [
        f"已基于 {len(activities)} 份已有活动报告完成对比,没有重新解析 FIT。",
        f"总量: {comparison['totals']['distance_km']} km, {comparison['totals']['duration_min']} 分钟。",
    ]
    for index, activity in enumerate(activities, start=1):
        lines.append(
            f"{index}. {activity.get('start_time_local') or activity.get('activity_key')}: "
            f"{activity.get('summary_label') or '未命名活动'}, "
            f"{activity.get('distance_km')} km / {activity.get('duration_min')} 分钟, "
            f"刺激: {activity.get('main_stimulus') or '未知'}, "
            f"负荷: {activity.get('training_load') or '未知'}。"
        )
    lines.append(comparison.get("training_judgement") or "")
    return "\n".join(line for line in lines if line)


def _compact_missing_summary(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_key": activity.get("activity_key"),
        "fit_path": activity.get("fit_path"),
        "summary_path": activity.get("summary_path"),
    }


def _path_name(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").split("/")[-1]


def _path_stem(value: str) -> str:
    name = _path_name(value)
    return name.rsplit(".", 1)[0] if "." in name else name


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
