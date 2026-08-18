from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from demo.global_cycling_router.graphhopper import GraphHopperCyclingRouter, WgsPoint


def test_route_builds_hosted_bike_request_and_normalizes_geojson():
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        return {
            "paths": [{
                "distance": 17250.4,
                "time": 4_020_000,
                "bbox": [135.7, 34.8, 135.9, 35.0],
                "points": {
                    "type": "LineString",
                    "coordinates": [[135.8009, 34.8908], [135.79, 34.92], [135.7727, 34.9671]],
                },
                "instructions": [{"text": "Turn right", "distance": 120.5, "time": 30000, "sign": 2, "interval": [0, 1]}],
            }]
        }

    router = GraphHopperCyclingRouter("test-graphhopper-key", transport=transport)
    result = router.route([WgsPoint(34.8908, 135.8009), WgsPoint(34.9671, 135.7727)])

    query = parse_qs(urlsplit(captured["request"].full_url).query)
    assert query["point"] == ["34.890800,135.800900", "34.967100,135.772700"]
    assert query["profile"] == ["bike"]
    assert query["points_encoded"] == ["false"]
    assert query["key"] == ["test-graphhopper-key"]
    assert result["distance_m"] == 17250.4
    assert result["duration_s"] == 4020
    assert result["geometry"]["type"] == "LineString"
    assert result["geometry"]["coordinates"][-1] == [135.7727, 34.9671]
    assert result["instructions"] == [{"text": "Turn right", "distance": 120.5, "time": 30000, "sign": 2, "interval": [0, 1]}]


def test_route_requires_two_points_and_bike_profile():
    router = GraphHopperCyclingRouter("test-key", transport=lambda *_: {})
    with pytest.raises(ValueError, match="at least two"):
        router.route([WgsPoint(34, 135)])
    with pytest.raises(ValueError, match="only the bike"):
        router.route([WgsPoint(34, 135), WgsPoint(35, 136)], profile="car")


def test_route_rejects_missing_geometry():
    router = GraphHopperCyclingRouter("test-key", transport=lambda *_: {"paths": [{"distance": 10}]})
    with pytest.raises(RuntimeError, match="LineString"):
        router.route([WgsPoint(34, 135), WgsPoint(35, 136)])
