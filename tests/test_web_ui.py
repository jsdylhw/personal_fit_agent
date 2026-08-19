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


def test_web_ui_chat_reuses_session_and_sends_idempotency_key():
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'fetchJson("/api/chat"' in source
    assert "session_id: state.chatSessionId" in source
    assert 'request_id: randomId("request")' in source
    assert "sessionStorage.getItem(CHAT_SESSION_STORAGE_KEY)" in source
    assert 'id="chatForm"' in markup
    assert 'id="presentations"' in markup


def test_web_ui_renders_presentations_without_injecting_markdown_html():
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'block.type === "metric_cards"' in source
    assert 'block.type === "table"' in source
    assert 'block.type === "line_chart"' in source
    assert 'block.type === "markdown"' in source
    assert 'markdown.textContent = block.data?.markdown || ""' in source
    assert "createElementNS(namespace, \"svg\")" in source
    assert 'summary.className = "chart-summary"' in source
    assert 'grid.setAttribute("class", "chart-grid")' in source
    assert 'label.setAttribute("class", "chart-value-label")' in source
    assert "if (values.length <= 40)" in source
    assert 'createElementNS(namespace, "path")' in source


def test_web_ui_initializes_leaflet_view_before_adding_route_layers():
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    initialize = 'L.map(container, { zoomControl: true }).setView([0, 0], 2)'
    add_route = "L.geoJSON(route.geometry"
    fit_route = "map.fitBounds("
    assert initialize in source
    assert source.index(initialize) < source.index(add_route) < source.index(fit_route)
