from __future__ import annotations

from core.storage.activity_store import ActivityStore, entry_from_fit_summary


def _v2_report(activity_key: str, fit_path: str) -> dict:
    return {
        "schema_version": "llm_fit_file_analysis.v2",
        "status": "analyzed",
        "activity_key": activity_key,
        "fit_path": fit_path,
        "fit_summary": {
            "sport_type": "cycling",
            "start_time_local": "2026-08-13T08:00:00",
            "duration_s": 1200,
            "distance_m": 8000,
        },
        "activity_metrics": {
            "schema_version": "activity_metrics.v2",
            "power": {"normalized_power_w": 180},
            "load": {"power_stress": {"tss": 20}},
        },
        "analysis_summary": {
            "schema_version": "activity_analysis_summary.v1",
            "summary_label": "晨间骑行",
            "main_stimulus": "有氧",
            "load_label": "低",
        },
        "markdown_report": "# report",
        "strava_summary": "summary",
    }


def test_activity_store_owns_catalogue_and_current_report(tmp_path):
    database = tmp_path / "activities.db"
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b"fit-data")
    store = ActivityStore(database)
    entry = entry_from_fit_summary(
        fit,
        {
            "sport_type": "cycling",
            "start_time_local": "2026-08-13T08:00:00",
            "duration_s": 1200,
            "distance_m": 8000,
        },
    )

    store.upsert_activity(entry)
    report = _v2_report(entry["activity_key"], entry["fit_path"])
    first = store.save_report(report, export_path=tmp_path / "ride.summary.json")
    second = store.save_report(report, export_path=tmp_path / "ride.summary.json")

    assert store.count_activities() == 1
    assert first["revision"] == 1
    assert second["revision"] == 1
    assert store.get_report(entry["activity_key"])["markdown_report"] == "# report"
    activity = store.list_activity_entries()[0]
    assert activity["has_summary"] is True
    assert activity["summary_schema_version"] == "llm_fit_file_analysis.v2"
    assert activity["estimated_tss"] == 20


def test_report_store_rejects_unindexed_and_legacy_documents(tmp_path):
    database = tmp_path / "activities.db"
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b"fit-data")
    store = ActivityStore(database)
    entry = entry_from_fit_summary(
        fit,
        {"sport_type": "cycling", "start_time_local": "2026-08-13T08:00:00"},
    )
    report = _v2_report(entry["activity_key"], entry["fit_path"])

    import pytest

    with pytest.raises(KeyError, match="indexed"):
        store.save_report(report)
    store.upsert_activity(entry)
    with pytest.raises(ValueError, match="unsupported report schema"):
        store.save_report({**report, "schema_version": "llm_fit_file_analysis.v1"})


def test_history_is_derived_from_v2_reports(tmp_path):
    database = tmp_path / "activities.db"
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b"fit-data")
    store = ActivityStore(database)
    entry = entry_from_fit_summary(
        fit,
        {
            "sport_type": "cycling",
            "start_time_local": "2026-08-13T08:00:00",
            "duration_s": 1200,
            "distance_m": 8000,
        },
    )
    store.upsert_activity(entry)
    store.save_report(_v2_report(entry["activity_key"], entry["fit_path"]))

    history = store.query_history(before="2026-08-14T00:00:00", days=7)

    assert history["schema_version"] == "activity_report_history.v1"
    assert history["count"] == 1
    assert history["activities"][0]["summary_label"] == "晨间骑行"
