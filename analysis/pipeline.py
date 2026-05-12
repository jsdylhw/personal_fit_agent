from __future__ import annotations

from typing import Any

from fit.parser import records_dataframe

from .activity import activity_metrics
from .derived import derived_metrics
from .laps import lap_summaries
from .llm_context import build_llm_context
from .observations import build_observations
from .quality import data_quality
from .stats import sample_statistics


def analyze_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    summary = dict(parsed["summary"])
    df = records_dataframe(parsed["records"])
    samples = sample_statistics(df)
    metrics = {
        "summary": summary,
        "activity_metrics": activity_metrics(summary, parsed, df),
        "records": _compact_records(parsed.get("records", [])),
        "sample_statistics": samples,
        "lap_summaries": lap_summaries(parsed.get("laps", [])),
        "training_metadata": parsed.get("training_metadata", {}),
        "data_quality": data_quality(summary, samples, df),
    }
    metrics["derived"] = derived_metrics(summary, samples, df)
    metrics["observations"] = build_observations(metrics)
    metrics["llm_context"] = build_llm_context(metrics)
    return metrics


def _compact_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "timestamp",
        "elapsed_s",
        "distance",
        "heart_rate",
        "power",
        "cadence",
        "enhanced_speed",
        "speed",
    ]
    df = records_dataframe(records)
    if df.empty:
        return []
    compact: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        compact.append({_field: _json_value(row.get(_field)) for _field in fields if _field in row})
    return compact


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            pass
    return value
