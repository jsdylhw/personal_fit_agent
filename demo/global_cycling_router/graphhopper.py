"""Hosted GraphHopper cycling adapter for the global route demo."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GRAPHHOPPER_ROUTE_URL = "https://graphhopper.com/api/1/route"
JsonTransport = Callable[[Request, float], dict[str, Any]]


@dataclass(frozen=True)
class WgsPoint:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90 <= self.lat <= 90 or not -180 <= self.lon <= 180:
            raise ValueError("point is outside the WGS-84 coordinate range")

    def api_value(self) -> str:
        return f"{self.lat:.6f},{self.lon:.6f}"


class GraphHopperCyclingRouter:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = GRAPHHOPPER_ROUTE_URL,
        timeout_s: float = 30.0,
        transport: JsonTransport | None = None,
    ) -> None:
        if not api_key or api_key.startswith("replace-with-"):
            raise ValueError("GRAPHHOPPER_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.transport = transport or _read_json

    def route(
        self,
        points: Sequence[WgsPoint],
        *,
        profile: str = "bike",
        locale: str = "en",
    ) -> dict[str, Any]:
        if len(points) < 2:
            raise ValueError("cycling route requires at least two points")
        if profile != "bike":
            raise ValueError("global route demo currently supports only the bike profile")
        query = urlencode({
            "point": [point.api_value() for point in points],
            "profile": profile,
            "locale": locale,
            "instructions": "true",
            "calc_points": "true",
            "points_encoded": "false",
            "key": self.api_key,
        }, doseq=True)
        request = Request(f"{self.base_url}?{query}", headers={"Accept": "application/json"})
        response = self.transport(request, self.timeout_s)
        paths = response.get("paths") or []
        if not paths or not isinstance(paths[0], dict):
            message = _provider_message(response)
            raise RuntimeError(f"GraphHopper returned no cycling route{': ' + message if message else ''}")
        path = paths[0]
        geometry = path.get("points")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString" or len(geometry.get("coordinates") or []) < 2:
            raise RuntimeError("GraphHopper route did not contain a usable LineString geometry")
        return {
            "schema_version": "cycling_route.v1",
            "provider": "graphhopper",
            "profile": profile,
            "coordinate_system": "wgs84",
            "distance_m": float(path.get("distance") or 0),
            "duration_s": float(path.get("time") or 0) / 1000,
            "geometry": {
                "type": "LineString",
                "coordinates": [[float(lon), float(lat)] for lon, lat, *_ in geometry["coordinates"]],
            },
            "bbox": list(path.get("bbox") or []),
            "instructions": [_normalize_instruction(item) for item in path.get("instructions") or [] if isinstance(item, dict)],
        }


def _normalize_instruction(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in ("text", "street_name", "distance", "time", "sign", "interval")
        if key in value
    }


def _provider_message(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if message:
        return str(message)
    hints = payload.get("hints") or []
    if hints and isinstance(hints[0], dict):
        return str(hints[0].get("message") or "")
    return ""


def _read_json(request: Request, timeout_s: float) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - fixed HTTPS provider URL
            payload = json.load(response)
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        raise RuntimeError(f"GraphHopper returned HTTP {exc.code}: {detail}") from exc
    except (TimeoutError, URLError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        raise RuntimeError(f"GraphHopper request failed: {reason or exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GraphHopper returned an invalid JSON object")
    return payload


def _http_error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        if isinstance(payload, dict):
            return _provider_message(payload) or str(exc.reason or "provider error")
    except (OSError, ValueError):
        pass
    return str(exc.reason or "provider error")
