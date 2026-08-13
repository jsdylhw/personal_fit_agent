from __future__ import annotations

from operations.activity.reporting import ensure_summary
from operations.activity.catalog import resolve_recent
from operations.activity.sync import sync_recent
from operations.activity.upload import upload_activity


def test_resolve_recent_is_explicit_and_does_not_need_agent_context(monkeypatch):
    monkeypatch.setattr(
        "operations.activity.catalog.list_activities",
        lambda **kwargs: {"count": 1, "activities": [{"activity_key": "a1", "fit_path": "a.fit"}]},
    )
    result = resolve_recent(limit=1)
    assert result["status"] == "completed"
    assert result["selection"] == {"kind": "recent", "limit": 1, "order": "latest", "sport_type": None}
    assert result["activities"][0]["activity_key"] == "a1"


def test_sync_recent_normalizes_partial_sync_result(monkeypatch):
    monkeypatch.setattr(
        "operations.activity.sync.sync_garmin_activities_tool",
        lambda count: {"downloaded": 1, "skipped": 0, "failed": 1, "indexed_items": [{"activity_key": "ok", "path": "ok.fit"}], "failed_items": [{"activity_id": 2, "error": "ConnectionError"}]},
    )
    result = sync_recent(count=2)
    assert result["status"] == "partial"
    assert result["activities"] == [{"activity_key": "ok", "path": "ok.fit"}]
    assert result["failed_items"][0]["activity_id"] == 2


def test_ensure_summary_requires_persisted_artifact(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fit = tmp_path / "activity.fit"
    fit.write_bytes(b"fit")
    monkeypatch.setattr("operations.activity.reporting.analyze_fit_file_tool", lambda path, force: {"activity_key": "a1", "status": "analyzed"})
    missing = ensure_summary(fit)
    assert missing["status"] == "failed"
    assert missing["error"] == "report_not_persisted"
    from storage.repositories.activity import ActivityStore

    store = ActivityStore()
    store.upsert_activity({
        "activity_key": "a1",
        "fit_path": str(fit),
        "sport_type": "cycling",
        "source": "test",
    })
    store.save_report({
        "schema_version": "llm_fit_file_analysis.v2",
        "status": "analyzed",
        "activity_key": "a1",
        "fit_path": str(fit),
        "fit_summary": {"sport_type": "cycling"},
        "activity_metrics": {"schema_version": "activity_metrics.v2"},
        "analysis_summary": {"schema_version": "activity_analysis_summary.v1"},
    })
    completed = ensure_summary(fit)
    assert completed["status"] == "completed"
    assert completed["report_schema_version"] == "llm_fit_file_analysis.v2"


def test_upload_activity_normalizes_completed_and_failed_results(monkeypatch, tmp_path):
    fit = tmp_path / "activity.fit"
    fit.write_bytes(b"fit")
    monkeypatch.setattr("operations.activity.upload.upload_to_strava_tool", lambda path, force: {"status": "uploaded", "strava_activity_id": 123})
    uploaded = upload_activity(fit)
    assert uploaded["status"] == "completed"
    assert uploaded["outcome"] == "uploaded"
    monkeypatch.setattr("operations.activity.upload.upload_to_strava_tool", lambda path, force: {"error": "network_error", "message": "TLS EOF"})
    failed = upload_activity(fit)
    assert failed["status"] == "failed"
    assert failed["error"] == "network_error"
