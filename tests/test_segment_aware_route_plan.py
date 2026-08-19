from __future__ import annotations

from unittest.mock import patch

import pytest

from services.route.segment_aware import apply_segment_aware_routing
from services.route.single_day import _encode_polyline


def _baseline_plan():
    return {
        "schema_version": "route_plan.v1",
        "plan_id": "route_test",
        "workspace_id": "workspace",
        "country_code": "CN",
        "active_candidate_id": "candidate_1",
        "candidates": [{
            "candidate_id": "candidate_1",
            "name": "湖岸路线",
            "route_type": "point_to_point",
            "waypoint_queries": ["起点", "终点"],
            "waypoints": [
                {"query": "起点", "name": "起点", "latitude": 30.0, "longitude": 120.0, "display_latitude": 30.0, "display_longitude": 120.0},
                {"query": "终点", "name": "终点", "latitude": 30.0, "longitude": 120.2, "display_latitude": 30.0, "display_longitude": 120.2},
            ],
            "provider": "amap",
            "travel_mode": "BICYCLE",
            "distance_m": 20_000,
            "distance_km": 20.0,
            "duration_s": 3_600,
            "duration_min": 60,
            "target_distance_km": 22,
            "geometry": {"type": "LineString", "coordinates": [[120.0, 30.0], [120.1, 30.0], [120.2, 30.0]]},
            "warnings": [],
        }],
    }


def _explorer(bounds, token):
    assert token == "token"
    return {"segments": [{
        "id": 101,
        "name": "热门湖岸段",
        "distance": 6_000,
        "avg_grade": 1.2,
        "elev_difference": 30,
        "start_latlng": [30.0, 120.07],
        "end_latlng": [30.0, 120.13],
    }]}


def _detail(segment_id):
    return {
        "id": segment_id,
        "name": "热门湖岸段",
        "distance": 6_000,
        "total_elevation_gain": 30,
        "map": {"polyline": _encode_polyline([(120.07, 30.0), (120.10, 30.0), (120.13, 30.0)])},
    }


class _FakeRouter:
    def __init__(self, key):
        assert key == "amap-key"

    def route(self, origin, destination):
        return {
            "distance_m": 7_000,
            "duration_s": 1_200,
            "geometry": [(origin.lon, origin.lat), (destination.lon, destination.lat)],
        }


def test_segment_aware_route_keeps_anchors_and_composes_selected_segment():
    captured = {}

    def selector(payload):
        captured.update(payload)
        return {"selections": [{
            "target_id": "candidate_1",
            "segments": [{"segment_id": 101, "direction": "forward"}],
        }]}

    with patch("services.route.segment_aware.AmapCyclingRouter", _FakeRouter):
        plan = apply_segment_aware_routing(
            _baseline_plan(),
            strategy="auto",
            access_token="token",
            amap_key="amap-key",
            request_text="走热门湖岸路线",
            preferences=["热门", "湖景"],
            include_elevation=True,
            explorer=_explorer,
            detail_fetcher=_detail,
            selector=selector,
            elevation_builder=lambda coordinates, distance: {"summary": {"samples": 2}, "labels": [0, distance / 1000], "elevations_m": [10, 20]},
        )

    route = plan["candidates"][0]
    assert route["provider"] == "amap+strava"
    assert route["geometry"]["coordinates"][0] == [120.0, 30.0]
    assert route["geometry"]["coordinates"][-1] == [120.2, 30.0]
    assert route["segment_evidence"]["segment_ids"] == [101]
    assert route["strava_segments"][0]["name"] == "热门湖岸段"
    assert route["elevation"]["summary"]["samples"] == 2
    assert captured["preferences"] == ["热门", "湖景"]
    assert "geometry" not in captured["targets"][0]["segments"][0]


def test_auto_falls_back_to_baseline_when_selector_fails():
    plan = apply_segment_aware_routing(
        _baseline_plan(),
        strategy="auto",
        access_token="token",
        amap_key="amap-key",
        request_text="参考路线",
        include_elevation=False,
        explorer=_explorer,
        detail_fetcher=_detail,
        selector=lambda payload: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )

    route = plan["candidates"][0]
    assert route["provider"] == "amap"
    assert any("保留高德基准路线" in warning for warning in route["warnings"])
    assert plan["segment_aware_summary"]["composed_target_count"] == 0


def test_require_rejects_empty_model_selection():
    with pytest.raises(RuntimeError, match="usable selection"):
        apply_segment_aware_routing(
            _baseline_plan(),
            strategy="require",
            access_token="token",
            amap_key="amap-key",
            request_text="必须包含热门路段",
            include_elevation=False,
            explorer=_explorer,
            detail_fetcher=_detail,
            selector=lambda payload: {"selections": []},
        )
