"""Web API security and managed-path regression tests."""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _prepare_api(tmp_path, monkeypatch, *, web_api_token: str = ""):
    monkeypatch.chdir(tmp_path)
    fit_dir = tmp_path / "fits"
    fit_dir.mkdir()
    config = {"output_dir": str(fit_dir)}
    if web_api_token:
        config["web_api_token"] = web_api_token
    api = importlib.import_module("app.api")
    monkeypatch.setattr(api, "load_config", lambda: config)
    return api, TestClient(api.app), fit_dir


def test_configured_api_token_is_required_for_dashboard(tmp_path, monkeypatch):
    _, client, _ = _prepare_api(tmp_path, monkeypatch, web_api_token="review-token")

    assert client.get("/api/dashboard/status").status_code == 401
    assert client.get("/api/dashboard/status", headers={"X-API-Token": "review-token"}).status_code == 200


def test_analyze_accepts_only_managed_fit_path(tmp_path, monkeypatch):
    api, client, fit_dir = _prepare_api(tmp_path, monkeypatch)
    managed_fit = fit_dir / "managed.fit"
    managed_fit.write_bytes(b"fit")
    outside_fit = tmp_path / "outside.fit"
    outside_fit.write_bytes(b"fit")
    calls = []

    def fake_analyze(path, **kwargs):
        calls.append((path, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr(api, "analyze_fit_document", fake_analyze)

    allowed = client.post("/api/fit-files/analyze", json={"path": str(managed_fit)})
    denied = client.post("/api/fit-files/analyze", json={"path": str(outside_fit)})

    assert allowed.status_code == 200
    assert calls == [(managed_fit, {"use_history": True, "force": False})]
    assert denied.status_code == 403


def test_strava_upload_uses_managed_summary_path(tmp_path, monkeypatch):
    api, client, _ = _prepare_api(tmp_path, monkeypatch)
    summary_dir = tmp_path / "data" / "summaries"
    summary_dir.mkdir(parents=True)
    summary = summary_dir / "ride.summary.json"
    summary.write_text("{}", encoding="utf-8")
    calls = []

    def fake_upload(path, **kwargs):
        calls.append((path, kwargs))
        return {"status": "uploaded"}

    monkeypatch.setattr(api, "upload_summary_document", fake_upload)

    allowed = client.post(
        "/api/strava/upload",
        json={"summary_path": str(summary), "force": True},
    )
    outside = client.post(
        "/api/strava/upload",
        json={"summary_path": str(tmp_path / "outside.summary.json")},
    )

    assert allowed.status_code == 200
    assert calls == [(summary.resolve(), {"title": None, "wait": True, "force": True})]
    assert outside.status_code == 403


def test_garmin_download_delegates_to_activity_operation(tmp_path, monkeypatch):
    api, client, fit_dir = _prepare_api(tmp_path, monkeypatch)
    calls = []

    def fake_sync(*, count):
        calls.append(count)
        return {
            "fit_dir": str(fit_dir),
            "downloaded": 1,
            "skipped": 1,
            "failed": 0,
            "downloaded_items": [{"activity_id": 1, "paths": ["new.fit"]}],
            "skipped_items": [{"activity_id": 2, "paths": ["old.fit"]}],
            "failed_items": [],
            "index_errors": [],
        }

    monkeypatch.setattr(api, "sync_garmin_activities_tool", fake_sync)

    response = client.post("/api/garmin/download", json={"count": 2})

    assert response.status_code == 200
    assert calls == [2]
    assert response.json()["status"] == "ok"
    assert [item["status"] for item in response.json()["results"]] == ["downloaded", "skipped_existing"]
