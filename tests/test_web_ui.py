"""Static Web UI regressions for authenticated API calls and Strava completion."""

from __future__ import annotations

from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "app" / "static"


def test_web_ui_keeps_api_token_in_session_and_uses_it_for_every_fetch_helper_call():
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "sessionStorage.getItem(API_TOKEN_STORAGE_KEY)" in source
    assert '"X-API-Token": token' in source
    assert "headers: apiHeaders(headers)" in source
    assert "fetchJson(`/api/summary?activity_key=${encodeURIComponent(file.activity_key)}`)" in source


def test_web_ui_waits_for_strava_completion_before_showing_success():
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "wait: true" in source
    assert "wait: false" not in source
    assert "uploadStatus.activity_id" in source
    assert "uploadStatus.error" in source
    assert "刷新确认" not in source
