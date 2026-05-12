from __future__ import annotations

from typing import Any


def build_llm_context(metrics: dict[str, Any]) -> dict[str, Any]:
    """Return raw structured data for an LLM. No conclusions or advice here."""
    return {
        "schema_version": "activity_raw_analysis.v1",
        "instruction": "Use only these structured metrics as source data. Do not treat this object as coaching advice.",
        "activity": metrics["activity_metrics"],
        "samples": metrics["sample_statistics"],
        "derived": metrics["derived"],
        "laps": metrics["lap_summaries"],
        "training_metadata": metrics.get("training_metadata", {}),
        "data_quality": metrics["data_quality"],
    }
