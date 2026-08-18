"""Project trusted tool outputs into small, stable UI presentation blocks."""

from __future__ import annotations

from typing import Any

from agent.runtime.models import ToolExecution
from agent.runtime.presentations import PresentationBlock


def project_presentations(executions: list[ToolExecution]) -> list[PresentationBlock]:
    """Return deterministic UI blocks for the tool schemas understood by the UI."""
    blocks: list[PresentationBlock] = []
    for execution in executions:
        payload = _schema_payload(execution.result)
        schema_version = str(payload.get("schema_version") or "")
        if schema_version == "training_history_analysis.v1":
            blocks.extend(_training_history_blocks(execution, payload))
        elif schema_version == "activity_report.v1":
            blocks.extend(_activity_report_blocks(execution, payload))
    return blocks


def _schema_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    nested = result.get("result")
    if isinstance(nested, dict) and nested.get("schema_version"):
        return nested
    return result


def _training_history_blocks(
    execution: ToolExecution,
    payload: dict[str, Any],
) -> list[PresentationBlock]:
    source = _source(execution, payload)
    blocks = [PresentationBlock(
        presentation_id=f"execution-{execution.index}-history-table",
        type="table",
        title="训练趋势对比",
        data={
            "columns": [
                "dimension", "metric", "baseline", "current", "change", "unit", "confidence",
            ],
            "rows": _history_rows(payload.get("dimensions")),
        },
        source=source,
    )]

    chart = _history_chart(payload)
    if chart["series"]:
        blocks.append(PresentationBlock(
            presentation_id=f"execution-{execution.index}-history-chart",
            type="line_chart",
            title="训练周期趋势",
            data=chart,
            source=source,
        ))
    return blocks


def _history_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension in value if isinstance(value, list) else []:
        if not isinstance(dimension, dict):
            continue
        evidence = dimension.get("evidence")
        evidence_items = evidence if isinstance(evidence, list) else []
        if not evidence_items:
            rows.append({
                "dimension": dimension.get("name"),
                "metric": None,
                "baseline": None,
                "current": None,
                "change": None,
                "unit": None,
                "confidence": dimension.get("confidence"),
            })
            continue
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            rows.append({
                "dimension": dimension.get("name"),
                "metric": item.get("metric"),
                "baseline": item.get("baseline"),
                "current": item.get("current"),
                "change": item.get("percent_change"),
                "unit": item.get("unit"),
                "confidence": dimension.get("confidence"),
            })
    return rows


def _history_chart(payload: dict[str, Any]) -> dict[str, Any]:
    series_payload = payload.get("series") if isinstance(payload.get("series"), dict) else {}
    periods = series_payload.get("periods") if isinstance(series_payload.get("periods"), list) else []
    view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
    metrics = view.get("chart_metrics") if isinstance(view.get("chart_metrics"), list) else []
    labels = [period.get("period") for period in periods if isinstance(period, dict)]
    series = []
    for metric in metrics:
        metric_name = str(metric)
        values = []
        has_value = False
        for period in periods:
            totals = period.get("totals") if isinstance(period, dict) else None
            value = totals.get(metric_name) if isinstance(totals, dict) else None
            values.append(value)
            has_value = has_value or value is not None
        if has_value:
            series.append({
                "metric": metric_name,
                "unit": _metric_unit(metric_name),
                "values": values,
            })
    return {"labels": labels, "series": series}


def _activity_report_blocks(
    execution: ToolExecution,
    payload: dict[str, Any],
) -> list[PresentationBlock]:
    result = execution.result if isinstance(execution.result, dict) else {}
    blocks: list[PresentationBlock] = []
    fit_summary = payload.get("fit_summary") if isinstance(payload.get("fit_summary"), dict) else {}
    cards = _activity_metric_cards(fit_summary)
    if cards:
        blocks.append(PresentationBlock(
            presentation_id=f"execution-{execution.index}-activity-metrics",
            type="metric_cards",
            title="活动概览",
            data={"items": cards},
            source=_source(execution, payload),
        ))
    markdown = result.get("answer") or payload.get("markdown_report")
    if isinstance(markdown, str) and markdown.strip():
        blocks.append(PresentationBlock(
            presentation_id=f"execution-{execution.index}-activity-report",
            type="markdown",
            title="活动分析报告",
            data={"markdown": markdown},
            source=_source(execution, payload),
        ))
    return blocks


def _activity_metric_cards(fit_summary: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    duration_s = _number(fit_summary.get("duration_s"))
    distance_m = _number(fit_summary.get("distance_m"))
    values = [
        ("sport_type", fit_summary.get("sport_type"), ""),
        ("start_time_local", fit_summary.get("start_time_local"), ""),
        ("duration_min", round(duration_s / 60, 1) if duration_s is not None else None, "min"),
        ("distance_km", round(distance_m / 1000, 2) if distance_m is not None else None, "km"),
    ]
    for metric, value, unit in values:
        if value is not None and value != "":
            cards.append({"metric": metric, "value": value, "unit": unit})
    return cards


def _source(execution: ToolExecution, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_index": execution.index,
        "tool": execution.tool,
        "result_schema": payload.get("schema_version"),
    }


def _metric_unit(metric: str) -> str:
    return {"duration_min": "min", "distance_km": "km", "tss": "TSS"}.get(metric, "")


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
