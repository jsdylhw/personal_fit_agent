"""训练负荷汇总工具.

这个模块只做确定性聚合:读取已选活动的 summary,提取 TSS/IF 等负荷线索,
只输出结构化训练负荷。是否疲劳、怎么安排路线,交给后续 LLM 步骤判断。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from agent.activity.comparison import read_activity_summary
from agent.context import AgentContext
from agent.workflow.plan_schema import WorkflowPlanStep


def summarize_recent_training_load(
    step: WorkflowPlanStep,
    context: AgentContext,
) -> dict[str, Any]:
    """汇总 context.selected_activities 的近期训练负荷."""
    activities = [
        activity
        for activity in context.selected_activities
        if isinstance(activity, dict)
    ]
    if not activities:
        return {
            "error": "missing_selected_activities",
            "message": "summarize_recent_training_load requires selected activities.",
        }

    reports: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for activity in activities:
        _, summary, error = read_activity_summary(activity)
        if error or summary is None:
            missing.append({
                "activity_key": activity.get("activity_key"),
                "summary_path": activity.get("summary_path"),
                "error": error,
            })
            continue
        reports.append(_training_load_activity(activity, summary))

    if not reports:
        return {
            "error": "missing_activity_summary",
            "message": "Need at least one readable summary to summarize training load.",
            "missing": missing,
        }

    summary = _build_training_load_summary(reports, missing=missing, scope=context.selected_activity_range or {})
    return {
        "step": step.name,
        "status": "completed",
        "result": summary,
    }


def _training_load_activity(activity: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    fit_summary = summary.get("fit_summary") if isinstance(summary.get("fit_summary"), dict) else {}
    history_entry = summary.get("history_entry") if isinstance(summary.get("history_entry"), dict) else {}
    text_blob = "\n".join(
        str(value or "")
        for value in (
            history_entry.get("training_load"),
            history_entry.get("brief"),
            summary.get("strava_summary"),
            summary.get("markdown_report"),
        )
    )
    tss = _extract_tss(text_blob)
    intensity_factor = _extract_intensity_factor(text_blob)
    return {
        "activity_key": summary.get("activity_key") or activity.get("activity_key"),
        "activity_index": activity.get("activity_index"),
        "summary_label": history_entry.get("summary_label") or activity.get("summary_label"),
        "start_time_local": (
            fit_summary.get("start_time_local")
            or history_entry.get("start_time_local")
            or activity.get("start_time_local")
        ),
        "sport_type": fit_summary.get("sport_type") or history_entry.get("sport_type") or activity.get("sport_type"),
        "duration_min": _number(history_entry.get("duration_min"), activity.get("duration_min")),
        "distance_km": _number(history_entry.get("distance_km"), activity.get("distance_km")),
        "training_load_text": history_entry.get("training_load"),
        "main_stimulus": history_entry.get("main_stimulus"),
        "brief": history_entry.get("brief"),
        "tss": tss,
        "intensity_factor": intensity_factor,
        "load_class": _classify_activity_load(tss, intensity_factor),
    }


def _build_training_load_summary(
    reports: list[dict[str, Any]],
    *,
    missing: list[dict[str, Any]],
    scope: dict[str, Any],
) -> dict[str, Any]:
    sorted_reports = sorted(reports, key=lambda item: str(item.get("start_time_local") or ""))
    tss_values = [float(item["tss"]) for item in sorted_reports if item.get("tss") is not None]
    if_values = [float(item["intensity_factor"]) for item in sorted_reports if item.get("intensity_factor") is not None]
    total_distance = round(sum(float(item.get("distance_km") or 0) for item in sorted_reports), 2)
    total_duration = round(sum(float(item.get("duration_min") or 0) for item in sorted_reports), 1)
    hard_count = sum(1 for item in sorted_reports if item.get("load_class") in {"hard", "very_hard"})
    easy_count = sum(1 for item in sorted_reports if item.get("load_class") in {"recovery", "easy"})
    total_tss = round(sum(tss_values), 1) if tss_values else None
    avg_if = round(sum(if_values) / len(if_values), 3) if if_values else None
    recency = _recency(sorted_reports)
    return {
        "schema_version": "training_load_summary.v1",
        "scope": scope,
        "activity_count": len(sorted_reports),
        "missing_summary_count": len(missing),
        "totals": {
            "distance_km": total_distance,
            "duration_min": total_duration,
            "tss": total_tss,
        },
        "intensity": {
            "basis": _intensity_basis(tss_values, if_values),
            "hard_activity_count": hard_count,
            "easy_activity_count": easy_count,
            "total_tss": total_tss,
            "avg_if": avg_if,
            "max_if": round(max(if_values), 3) if if_values else None,
        },
        "recency": recency,
        "activities": sorted_reports,
        "missing": missing,
    }


def _classify_activity_load(tss: float | None, intensity_factor: float | None) -> str:
    if intensity_factor is not None:
        if intensity_factor >= 0.95:
            return "very_hard"
        if intensity_factor >= 0.85:
            return "hard"
        if intensity_factor >= 0.75:
            return "moderate"
        if intensity_factor >= 0.60:
            return "easy"
        return "recovery"
    if tss is not None:
        if tss >= 150:
            return "very_hard"
        if tss >= 100:
            return "hard"
        if tss >= 50:
            return "moderate"
        return "easy"
    return "unknown"


def _recency(reports: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [_date_part(report.get("start_time_local")) for report in reports]
    dates = [item for item in dates if item is not None]
    if not dates:
        return {"last_activity_date": None, "days_since_last_activity": None}
    last_date = max(dates)
    return {
        "last_activity_date": last_date.isoformat(),
        "days_since_last_activity": (date.today() - last_date).days,
    }


def _intensity_basis(tss_values: list[float], if_values: list[float]) -> str:
    if tss_values and if_values:
        return "power_tss_if"
    if tss_values:
        return "power_tss"
    if if_values:
        return "power_if"
    return "summary_text"


def _extract_tss(text: str) -> float | None:
    patterns = (
        r"\bTSS\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*TSS\b",
    )
    return _extract_first_number(text, patterns)


def _extract_intensity_factor(text: str) -> float | None:
    patterns = (
        r"\bIF\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)",
        r"IF\s*([0-9]+(?:\.[0-9]+)?)",
        r"强度因子\s*(?:\(IF\))?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)",
    )
    return _extract_first_number(text, patterns)


def _extract_first_number(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _number(match.group(1))
    return None


def _date_part(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
