"""Versioned accessors for persisted activity summary documents.

New writers emit ``llm_fit_file_analysis.v2``.  V1 support is intentionally
read-only and centralized here so it can be removed after an explicit data
backfill.

TODO(summary-v1-removal): add a backfill command, verify that the activity
index reports zero V1 summaries, then remove LEGACY_SUMMARY_SCHEMA_V1 and the
``history_entry``/``training_load`` fallbacks from this module.
"""

from __future__ import annotations

from typing import Any


LEGACY_SUMMARY_SCHEMA_V1 = "llm_fit_file_analysis.v1"
SUMMARY_SCHEMA_V2 = "llm_fit_file_analysis.v2"
ANALYSIS_SUMMARY_SCHEMA_V1 = "activity_analysis_summary.v1"
SUPPORTED_SUMMARY_SCHEMAS = {LEGACY_SUMMARY_SCHEMA_V1, SUMMARY_SCHEMA_V2}


def is_legacy_summary(document: dict[str, Any]) -> bool:
    return summary_schema_version(document) == LEGACY_SUMMARY_SCHEMA_V1


def summary_schema_version(document: dict[str, Any]) -> str:
    value = str(document.get("schema_version") or "")
    if value in SUPPORTED_SUMMARY_SCHEMAS:
        return value
    # Some early V1 fixtures/files predate the top-level version field.
    if isinstance(document.get("history_entry"), dict):
        return LEGACY_SUMMARY_SCHEMA_V1
    return "unknown"


def get_index_load_label(entry: dict[str, Any]) -> Any:
    """Read the V2 index field with one centralized V1 cache fallback."""
    return entry.get("load_label") or entry.get("training_load")


def analysis_summary_from_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Read-only V1 adapter: keep only qualitative model annotations."""
    load_label = entry.get("load_label")
    if load_label is None:
        # Legacy model output used training_load for a human-readable label or
        # a prose string containing metrics.  Preserve it only as a display
        # fallback; no calculation path reads this field.
        load_label = entry.get("training_load")
    return {
        "schema_version": ANALYSIS_SUMMARY_SCHEMA_V1,
        "summary_label": entry.get("summary_label"),
        "main_stimulus": entry.get("main_stimulus"),
        "load_label": load_label,
        "quality_notes": entry.get("quality_notes") if isinstance(entry.get("quality_notes"), list) else [],
        "brief": entry.get("brief") or "",
    }


def get_analysis_summary(document: dict[str, Any]) -> dict[str, Any]:
    value = document.get("analysis_summary")
    if isinstance(value, dict):
        return value
    legacy = document.get("history_entry")
    return analysis_summary_from_history_entry(legacy) if isinstance(legacy, dict) else {}


def build_history_entry(document: dict[str, Any]) -> dict[str, Any]:
    """Build the separate history-cache row from a V1 or V2 summary."""
    legacy = document.get("history_entry")
    if isinstance(legacy, dict) and legacy:
        return dict(legacy)

    analysis = get_analysis_summary(document)
    fit_summary = document.get("fit_summary") if isinstance(document.get("fit_summary"), dict) else {}
    duration_s = _number(fit_summary.get("duration_s"))
    distance_m = _number(fit_summary.get("distance_m"))
    return {
        "schema_version": "llm_activity_history_entry.v2",
        "activity_key": document.get("activity_key"),
        "file_path": document.get("fit_path"),
        "start_time": fit_summary.get("start_time_local"),
        "start_time_local": fit_summary.get("start_time_local"),
        "sport_type": fit_summary.get("sport_type"),
        "sub_sport": fit_summary.get("sub_sport"),
        "duration_s": duration_s,
        "distance_m": distance_m,
        "duration_min": round(duration_s / 60, 2) if duration_s is not None else None,
        "distance_km": round(distance_m / 1000, 3) if distance_m is not None else None,
        "summary_label": analysis.get("summary_label"),
        "main_stimulus": analysis.get("main_stimulus"),
        "load_label": analysis.get("load_label"),
        "quality_notes": analysis.get("quality_notes") if isinstance(analysis.get("quality_notes"), list) else [],
        "brief": analysis.get("brief") or "",
    }


def get_tss(metrics: dict[str, Any]) -> float | None:
    """Return TSS from activity_metrics.v1 or v2."""
    load = metrics.get("load") if isinstance(metrics.get("load"), dict) else {}
    power_stress = load.get("power_stress") if isinstance(load.get("power_stress"), dict) else {}
    return _number(power_stress.get("tss"), load.get("tss"))


def get_tss_source(metrics: dict[str, Any]) -> str:
    load = metrics.get("load") if isinstance(metrics.get("load"), dict) else {}
    power_stress = load.get("power_stress") if isinstance(load.get("power_stress"), dict) else {}
    return str(power_stress.get("source") or load.get("tss_source") or "unavailable")


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
