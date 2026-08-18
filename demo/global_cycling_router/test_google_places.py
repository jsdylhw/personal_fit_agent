from __future__ import annotations

import json

import pytest

from demo.global_cycling_router.google_places import GOOGLE_PLACES_FIELD_MASK, GooglePlacesClient


def test_search_builds_text_request_and_normalizes_places():
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return {
            "places": [
                {
                    "id": "uji-station",
                    "displayName": {"text": "宇治站", "languageCode": "zh-CN"},
                    "formattedAddress": "日本京都府宇治市",
                    "location": {"latitude": 34.8908, "longitude": 135.8009},
                    "types": ["train_station", "point_of_interest"],
                },
                {"id": "missing-coordinate", "displayName": {"text": "无坐标"}},
            ]
        }

    client = GooglePlacesClient("test-google-key", transport=transport)
    result = client.search("宇治站 日本", near=(34.89, 135.80), radius_m=12_000, limit=6)

    request = captured["request"]
    body = json.loads(request.data)
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.method == "POST"
    assert body["textQuery"] == "宇治站 日本"
    assert body["pageSize"] == 6
    assert body["locationBias"]["circle"]["center"] == {"latitude": 34.89, "longitude": 135.8}
    assert headers["x-goog-api-key"] == "test-google-key"
    assert headers["x-goog-fieldmask"] == GOOGLE_PLACES_FIELD_MASK
    assert result == {
        "schema_version": "place_search.v1",
        "provider": "google_places",
        "coordinate_system": "wgs84",
        "query": "宇治站 日本",
        "places": [{
            "id": "uji-station",
            "name": "宇治站",
            "address": "日本京都府宇治市",
            "location": {"latitude": 34.8908, "longitude": 135.8009},
            "types": ["train_station", "point_of_interest"],
        }],
    }


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_query(query):
    client = GooglePlacesClient("test-google-key", transport=lambda *_: {})
    with pytest.raises(ValueError, match="query is required"):
        client.search(query)


def test_client_rejects_placeholder_key():
    with pytest.raises(ValueError, match="not configured"):
        GooglePlacesClient("replace-with-google-maps-api-key")
