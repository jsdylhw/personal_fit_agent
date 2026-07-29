from __future__ import annotations

from agent.activity.workflow_executor import execute_activity_run
from agent.activity.workflow_factory import TASK_UPLOAD_STRAVA, create_activity_run_from_activities
from agent.activity.workflow_service import (
    get_activity_workflow,
    retry_activity_workflow,
    sync_and_start_activity_workflow,
)


def test_service_runs_and_retries_persisted_upload_run(monkeypatch, tmp_path):
    fit = tmp_path / "a1.fit"
    fit.write_bytes(b"fit")
    summary = tmp_path / "a1.summary.json"
    summary.write_text("{}", encoding="utf-8")
    created = create_activity_run_from_activities(
        [{"activity_key": "a1", "fit_path": str(fit), "summary_path": str(summary)}],
        request={"source": "test", "goals": [TASK_UPLOAD_STRAVA], "force": False},
        directory=tmp_path,
    )
    run = created["run"]
    workflow_id = run["workflow_id"]
    monkeypatch.setattr(
        "agent.activity.workflow_handlers.upload_summary",
        lambda *args, **kwargs: {"status": "failed", "error": "network_error", "message": "offline"},
    )

    failed = execute_activity_run(run, directory=tmp_path)
    assert failed["workflow"]["status"] == "partial"
    assert next(task for task in run["tasks"] if task["kind"] == TASK_UPLOAD_STRAVA)["status"] == "failed"

    monkeypatch.setattr(
        "agent.activity.workflow_handlers.upload_summary",
        lambda *args, **kwargs: {"status": "completed", "outcome": "uploaded", "strava_activity_id": "456"},
    )
    retried = retry_activity_workflow(workflow_id, directory=tmp_path)
    assert retried["retried_task_ids"] == ["a1:upload_strava"]
    upload = next(task for task in retried["tasks"] if task["kind"] == TASK_UPLOAD_STRAVA)
    assert retried["workflow"]["status"] == "completed"
    assert upload["attempts"] == 2
    assert retried["activities"][0]["strava_activity_id"] == "456"


def test_service_reports_missing_run_and_nothing_to_retry(tmp_path):
    assert get_activity_workflow("missing", directory=tmp_path)["status"] == "not_found"

    created = create_activity_run_from_activities(
        [{"activity_key": "a1", "fit_path": str(tmp_path / "a1.fit")}],
        request={"source": "test", "goals": ["ensure_summary"], "force": False},
        directory=tmp_path,
    )
    result = retry_activity_workflow(created["run"]["workflow_id"], directory=tmp_path)
    assert result["status"] == "nothing_to_retry"


def test_sync_service_freezes_exact_indexed_items_and_persists_sync_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.activity.workflow_service.sync_recent",
        lambda count: {
            "status": "partial", "downloaded": 1, "skipped": 1, "failed": 1,
            "failed_items": [{"id": "remote-failed"}],
            "activities": [
                {"activity_key": "a1", "activity_id": "remote-a1", "path": "/fit/a1.fit", "sport_type": "cycling", "start_time_local": "2026-07-29T08:00:00"},
                {"activity_key": "a2", "activity_id": "remote-a2", "path": "/fit/a2.fit", "sport_type": "running", "start_time_local": "2026-07-29T19:00:00"},
            ],
        },
    )
    monkeypatch.setattr(
        "agent.activity.workflow_service.execute_activity_run",
        lambda run, **kwargs: {"workflow": {"status": "completed"}, "waiting_for": []},
    )

    result = sync_and_start_activity_workflow(
        count=5, goals=["ensure_summary", "upload_strava"], directory=tmp_path,
    )

    assert result["created"] is True
    assert [item["activity_key"] for item in result["activities"]] == ["a1", "a2"]
    from agent.runtime.workflow_store import load_workflow
    run = load_workflow(result["workflow_id"], directory=tmp_path)
    assert run["request"]["source"] == "garmin_sync"
    assert run["request"]["selection"]["activity_keys"] == ["a1", "a2"]
    assert run["request"]["sync"] == {
        "schema_version": "activity_workflow_sync.v1", "requested_count": 5, "status": "partial",
        "downloaded": 1, "skipped": 1, "failed": 1, "indexed_activity_keys": ["a1", "a2"],
        "failed_items": [{"id": "remote-failed"}],
    }
