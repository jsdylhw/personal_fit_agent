from __future__ import annotations

from core.activity_summary import (
    LEGACY_SUMMARY_SCHEMA_V1,
    SUMMARY_SCHEMA_V2,
    build_history_entry,
    get_analysis_summary,
    get_tss,
    is_legacy_summary,
    summary_schema_version,
)


def test_legacy_summary_is_read_through_one_compatibility_adapter():
    document = {
        "schema_version": LEGACY_SUMMARY_SCHEMA_V1,
        "history_entry": {
            "summary_label": "恢复骑",
            "main_stimulus": "低强度有氧",
            "training_load": "TSS 14.5 / IF 0.675",
            "duration_min": 19.5,
        },
    }

    assert is_legacy_summary(document) is True
    assert summary_schema_version(document) == LEGACY_SUMMARY_SCHEMA_V1
    assert get_analysis_summary(document)["load_label"] == "TSS 14.5 / IF 0.675"
    assert build_history_entry(document)["duration_min"] == 19.5


def test_v2_summary_keeps_qualitative_and_numeric_load_fields_separate():
    document = {
        "schema_version": SUMMARY_SCHEMA_V2,
        "fit_summary": {
            "sport_type": "cycling",
            "duration_s": 1200,
            "distance_m": 9000,
        },
        "analysis_summary": {
            "schema_version": "activity_analysis_summary.v1",
            "summary_label": "短途恢复骑",
            "load_label": "低总量，有氧维持",
        },
        "activity_metrics": {
            "schema_version": "activity_metrics.v2",
            "load": {
                "power_stress": {"tss": 14.5, "source": "fit_session"},
                "garmin": {"training_load_peak": 34.7, "aerobic_training_effect": 2.3},
            },
        },
    }

    assert is_legacy_summary(document) is False
    assert get_analysis_summary(document)["load_label"] == "低总量，有氧维持"
    assert get_tss(document["activity_metrics"]) == 14.5
    history = build_history_entry(document)
    assert history["duration_min"] == 20.0
    assert history["distance_km"] == 9.0
    assert "training_load" not in history
