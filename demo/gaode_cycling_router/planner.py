"""Bridge existing route-composition algorithms to the AMap cycling adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from demo.osm_cycling_router.router import Point
from demo.osm_cycling_router.segment_loop import ConnectorFetcher, DirectedSegment, LoopCandidate, plan_ordered_segment_route

from .amap import AmapCyclingRouter, AmapPoint
from .coordinates import wgs84_to_gcj02


def wgs84_point_to_amap(point: Point) -> AmapPoint:
    lon, lat = wgs84_to_gcj02(point.lon, point.lat)
    return AmapPoint(lat, lon)


def amap_connector_fetcher(router: AmapCyclingRouter) -> ConnectorFetcher:
    """Make AMap pairwise cycling directions usable by ``segment_loop``."""
    def fetch(origin: Point, destination: Point) -> dict[str, Any]:
        # The planner receives GCJ-02 points after ``segments_to_gcj02`` below.
        result = router.route(AmapPoint(origin.lat, origin.lon), AmapPoint(destination.lat, destination.lon))
        return {
            **result,
            "raw": {"paths": [{"points": {"coordinates": result["geometry"]}}]},
            "details": {"provider": "amap", "mode": "bicycling"},
        }
    return fetch


def segments_to_gcj02(segments: Sequence[DirectedSegment]) -> list[DirectedSegment]:
    """Convert imported WGS-84 Strava/OSM skeletons once for AMap routing/rendering."""
    converted: list[DirectedSegment] = []
    for segment in segments:
        geometry = tuple(wgs84_to_gcj02(lon, lat) for lon, lat in segment.geometry)
        converted.append(DirectedSegment(
            segment_id=segment.segment_id,
            name=segment.name,
            geometry=geometry,
            distance_m=segment.distance_m,
            ascend_m=segment.ascend_m,
            properties={**segment.properties, "source_coordinate_system": "wgs84", "coordinate_system": "gcj02"},
        ))
    return converted


def plan_ordered_wgs84_segments_with_amap(
    segments: Sequence[DirectedSegment],
    *,
    start: Point,
    target_distance_m: float,
    router: AmapCyclingRouter,
    start_name: str = "指定起终点",
    near_handoff_m: float = 0.0,
) -> LoopCandidate:
    """Run the current ordered skeleton algorithm with AMap cycling connectors.

    Input segment geometries and ``start`` are WGS-84.  The output candidate is
    GCJ-02 and can be drawn directly on a high-map JS API base map.
    """
    gcj_start = wgs84_point_to_amap(start)
    return plan_ordered_segment_route(
        segments_to_gcj02(segments),
        start=Point(gcj_start.lat, gcj_start.lon),
        target_distance_m=target_distance_m,
        profile="amap_bicycling",
        connector_fetcher=amap_connector_fetcher(router),
        start_name=start_name,
        near_handoff_m=near_handoff_m,
    )
