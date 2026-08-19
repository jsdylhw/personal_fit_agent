"""Segment-aware domestic route planning built on verified baseline routes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Sequence

from demo.gaode_cycling_router.amap import AmapCyclingRouter, AmapPoint
from demo.gaode_cycling_router.coordinates import gcj02_to_wgs84, wgs84_to_gcj02
from demo.osm_cycling_router.segment_loop import haversine_m
from demo.osm_cycling_router.strava_segments import segment_detail_feature
from services.route.segments import enrich_route_plan_with_segments


Explorer = Callable[[str, str], dict[str, Any]]
DetailFetcher = Callable[[int], dict[str, Any]]
Selector = Callable[[dict[str, Any]], dict[str, Any]]
ElevationBuilder = Callable[[Sequence[Sequence[float]], float], dict[str, Any]]


def apply_segment_aware_routing(
    plan: dict[str, Any],
    *,
    strategy: str,
    access_token: str,
    amap_key: str,
    request_text: str,
    preferences: Sequence[str] = (),
    include_elevation: bool = True,
    corridor_km: float = 5.0,
    max_segments_per_target: int = 10,
    explorer: Explorer,
    detail_fetcher: DetailFetcher,
    selector: Selector,
    elevation_builder: ElevationBuilder | None = None,
) -> dict[str, Any]:
    """Enrich and optionally replace each baseline target with a Segment route.

    Explicit waypoints stay as hard anchors. Strava Segments are route material
    between those anchors; AMap still validates every connector. ``auto`` falls
    back to the baseline target, while ``require`` refuses an unverified target.
    """
    normalized_strategy = str(strategy or "auto").strip().lower()
    if normalized_strategy not in {"auto", "ignore", "require"}:
        raise ValueError("segment_strategy must be auto, ignore or require")
    updated = deepcopy(plan)
    updated["segment_strategy"] = normalized_strategy
    updated["segment_preferences"] = [str(value) for value in preferences if str(value).strip()]
    if normalized_strategy == "ignore":
        return _add_final_elevation(updated, include_elevation, elevation_builder)
    if str(updated.get("country_code") or "").upper() != "CN":
        if normalized_strategy == "require":
            raise ValueError("segment_strategy=require is currently supported only for mainland China")
        return _add_final_elevation(updated, include_elevation, elevation_builder)
    if not amap_key:
        raise ValueError("amap.web_service_key is not configured")

    targets = _plan_targets(updated)
    available: dict[str, list[dict[str, Any]]] = {}
    selection_targets = []
    for target_id, target in targets:
        temporary = {
            "plan_id": "segment_discovery",
            "workspace_id": "segment_discovery",
            "active_candidate_id": target_id,
            "candidates": [{**deepcopy(target), "candidate_id": target_id}],
        }
        discovered_plan, discovery = enrich_route_plan_with_segments(
            temporary,
            access_token=access_token,
            candidate_id=target_id,
            corridor_km=corridor_km,
            max_segments=max_segments_per_target,
            explorer=explorer,
        )
        segments = discovered_plan["candidates"][0].get("strava_segments") or []
        available[target_id] = segments
        target["strava_segment_discovery"] = {
            "source": "strava_segments_explore",
            "corridor_km": corridor_km,
            "sample_count": sum(int(item.get("sample_count") or 0) for item in discovery.get("targets") or []),
            "nearby_segment_count": len(segments),
            "discovery_limit": discovery.get("discovery_limit"),
        }
        selection_targets.append({
            "target_id": target_id,
            "label": target.get("label") or target.get("name") or target_id,
            "route_type": target.get("route_type"),
            "target_distance_km": target.get("target_distance_km"),
            "baseline_distance_km": target.get("distance_km"),
            "anchors": [
                point.get("query") or point.get("name")
                for point in target.get("waypoints") or [] if isinstance(point, dict)
            ],
            "segments": [
                {key: value for key, value in segment.items() if key != "geometry"}
                for segment in segments
            ],
        })

    package = {
        "schema_version": "route_segment_selection_request.v1",
        "request": request_text,
        "preferences": updated["segment_preferences"],
        "rules": {
            "anchors_are_hard_constraints": True,
            "maximum_segments_per_target": 3,
            "do_not_invent_segment_ids": True,
        },
        "targets": selection_targets,
    }
    try:
        selections = _selection_map(selector(package), available)
    except Exception as exc:  # noqa: BLE001 - auto mode explicitly degrades to the verified baseline
        if normalized_strategy == "require":
            raise RuntimeError(f"Strava route selection failed: {exc}") from exc
        selections = {}
        for _, target in targets:
            _append_warning(target, f"Strava 路段选择失败，保留高德基准路线：{type(exc).__name__}")

    router = AmapCyclingRouter(amap_key)
    composed_count = 0
    for target_id, target in targets:
        choices = selections.get(target_id) or []
        if not choices:
            if normalized_strategy == "require":
                raise RuntimeError(f"Strava did not produce a usable selection for {target_id}")
            _append_warning(target, "未选择到适合当前锚点顺序的 Strava 路段，保留高德基准路线")
            continue
        selected = []
        by_id = {int(item["segment_id"]): item for item in available.get(target_id) or []}
        for choice in choices:
            segment_id = int(choice["segment_id"])
            summary = by_id.get(segment_id)
            if not summary:
                continue
            try:
                feature = segment_detail_feature(detail_fetcher(segment_id))
            except Exception:  # Explorer geometry is a bounded fallback when detail temporarily fails.
                feature = _summary_feature(summary)
            selected.append({
                "summary": summary,
                "feature": feature,
                "direction": str(choice.get("direction") or summary.get("suggested_direction") or "forward"),
            })
        try:
            composed = _compose_target(target, selected, router=router)
        except Exception as exc:  # noqa: BLE001 - retain a real provider baseline in auto mode
            if normalized_strategy == "require":
                raise RuntimeError(f"Strava route composition failed for {target_id}: {exc}") from exc
            _append_warning(target, f"Strava 路段连接失败，保留高德基准路线：{type(exc).__name__}")
            continue
        target.clear()
        target.update(composed)
        composed_count += 1

    updated["segment_aware_summary"] = {
        "target_count": len(targets),
        "composed_target_count": composed_count,
        "fallback_target_count": len(targets) - composed_count,
    }
    return _add_final_elevation(updated, include_elevation, elevation_builder)


def _plan_targets(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    targets = []
    for candidate in plan.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        stages = [item for item in candidate.get("stages") or [] if isinstance(item, dict)]
        if stages:
            targets.extend((str(stage.get("stage_id") or ""), stage) for stage in stages)
        else:
            targets.append((str(candidate.get("candidate_id") or ""), candidate))
    return [(identifier, target) for identifier, target in targets if identifier]


def _selection_map(
    payload: Any,
    available: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("route selector must return an object")
    result: dict[str, list[dict[str, Any]]] = {}
    for selection in payload.get("selections") or []:
        if not isinstance(selection, dict):
            continue
        target_id = str(selection.get("target_id") or "")
        valid_ids = {int(item["segment_id"]) for item in available.get(target_id) or []}
        choices = []
        for item in selection.get("segments") or []:
            if not isinstance(item, dict):
                continue
            try:
                segment_id = int(item.get("segment_id"))
            except (TypeError, ValueError):
                continue
            direction = str(item.get("direction") or "forward").lower()
            if segment_id in valid_ids and direction in {"forward", "reverse"}:
                choices.append({"segment_id": segment_id, "direction": direction})
            if len(choices) >= 3:
                break
        if choices:
            result[target_id] = choices
    return result


def _compose_target(
    baseline: dict[str, Any],
    selected: list[dict[str, Any]],
    *,
    router: AmapCyclingRouter,
) -> dict[str, Any]:
    if not selected:
        raise ValueError("at least one selected segment is required")
    baseline_geometry = _coordinates(baseline.get("geometry"))
    anchors = _anchor_events(baseline, baseline_geometry)
    events: list[tuple[float, int, str, Any]] = [
        (ratio, 1, "anchor", point) for ratio, point in anchors[1:]
    ]
    persisted_segments = []
    for item in selected:
        summary = item["summary"]
        feature = item["feature"]
        coordinates = _coordinates(feature.get("geometry"))
        direction = item["direction"]
        if direction == "reverse":
            coordinates = list(reversed(coordinates))
        position = float(summary.get("route_position_ratio") or 0)
        events.append((position, 0, "segment", coordinates))
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        persisted_segments.append({
            **{key: value for key, value in summary.items() if key != "geometry"},
            "direction": direction,
            "distance_km": round(float(properties.get("distance_m") or summary.get("distance_km", 0) * 1000) / 1000, 2),
            "geometry": {"type": "LineString", "coordinates": coordinates},
        })
    events.sort(key=lambda item: (item[0], item[1]))

    geometry: list[list[float]] = []
    connector_distance_m = connector_duration_s = segment_distance_m = 0.0
    current = anchors[0][1]

    def append(points: Sequence[Sequence[float]]) -> None:
        for point in points:
            normalized = [float(point[0]), float(point[1])]
            if not geometry or geometry[-1] != normalized:
                geometry.append(normalized)

    append([current])
    for _, _, kind, value in events:
        destination = value[0] if kind == "segment" else value
        connector = _connector(current, destination, router)
        append(connector["coordinates"])
        connector_distance_m += connector["distance_m"]
        connector_duration_s += connector["duration_s"]
        if kind == "segment":
            append(value)
            distance = _line_distance_m(value)
            segment_distance_m += distance
            current = value[-1]
        else:
            current = value

    distance_m = connector_distance_m + segment_distance_m
    baseline_distance = float(baseline.get("distance_m") or 0)
    baseline_duration = float(baseline.get("duration_s") or 0)
    speed_mps = baseline_distance / baseline_duration if baseline_distance > 0 and baseline_duration > 0 else 5.0
    duration_s = connector_duration_s + segment_distance_m / max(2.5, speed_mps)
    connector_ratio = connector_distance_m / max(1.0, distance_m)
    if connector_ratio > 0.9:
        raise RuntimeError("selected segments require too much connector distance")
    warnings = [
        warning for warning in baseline.get("warnings") or []
        if not str(warning).startswith("未选择到适合")
    ]
    warnings.extend([
        "路线包含 Strava 热门路段，路段之间由高德骑行连接",
        "Strava 路段上的预计时间按高德基准路线平均速度估算",
    ])
    distance_km = round(distance_m / 1000, 1)
    target_distance = baseline.get("target_distance_km")
    return {
        **baseline,
        "name": str(baseline.get("name") or baseline.get("label") or "路线"),
        "provider": "amap+strava",
        "travel_mode": "BICYCLE",
        "distance_m": distance_m,
        "distance_km": distance_km,
        "duration_s": duration_s,
        "duration_min": round(duration_s / 60),
        "distance_delta_km": round(distance_km - float(target_distance), 1) if target_distance is not None else None,
        "geometry": {"type": "LineString", "coordinates": geometry},
        "elevation": None,
        "strava_segments": persisted_segments,
        "segment_evidence": {
            "segment_ids": [int(item["segment_id"]) for item in persisted_segments],
            "connector_distance_km": round(connector_distance_m / 1000, 2),
            "connector_ratio": round(connector_ratio, 3),
            "baseline_distance_km": baseline.get("distance_km"),
        },
        "warnings": warnings,
    }


def _anchor_events(target: dict[str, Any], route: Sequence[Sequence[float]]) -> list[tuple[float, list[float]]]:
    anchors = []
    for point in target.get("waypoints") or []:
        if not isinstance(point, dict):
            continue
        lat = point.get("display_latitude", point.get("latitude"))
        lon = point.get("display_longitude", point.get("longitude"))
        try:
            anchors.append([float(lon), float(lat)])
        except (TypeError, ValueError):
            continue
    if len(anchors) < 2:
        raise ValueError("baseline route has insufficient anchors")
    events = [(0.0, anchors[0])]
    previous_index = 0
    for ordinal, anchor in enumerate(anchors[1:], start=1):
        if ordinal == len(anchors) - 1:
            index = len(route) - 1
        else:
            index = min(
                range(previous_index, len(route)),
                key=lambda candidate: haversine_m(anchor, route[candidate]),
            )
        events.append((index / max(1, len(route) - 1), anchor))
        previous_index = index
    return events


def _connector(
    origin: Sequence[float],
    destination: Sequence[float],
    router: AmapCyclingRouter,
) -> dict[str, Any]:
    straight = haversine_m(origin, destination)
    if straight <= 30:
        return {"coordinates": [list(origin), list(destination)], "distance_m": straight, "duration_s": 0.0}
    origin_gcj = wgs84_to_gcj02(float(origin[0]), float(origin[1]))
    destination_gcj = wgs84_to_gcj02(float(destination[0]), float(destination[1]))
    routed = router.route(
        AmapPoint(origin_gcj[1], origin_gcj[0]),
        AmapPoint(destination_gcj[1], destination_gcj[0]),
    )
    coordinates = [list(gcj02_to_wgs84(lon, lat)) for lon, lat in routed["geometry"]]
    return {
        "coordinates": coordinates,
        "distance_m": float(routed.get("distance_m") or 0),
        "duration_s": float(routed.get("duration_s") or 0),
    }


def _summary_feature(summary: dict[str, Any]) -> dict[str, Any]:
    geometry = summary.get("geometry") if isinstance(summary.get("geometry"), dict) else {}
    if len(geometry.get("coordinates") or []) < 2:
        raise ValueError("selected Strava Segment has no usable geometry")
    return {
        "type": "Feature",
        "properties": {
            "id": int(summary["segment_id"]),
            "name": summary.get("name"),
            "distance_m": float(summary.get("distance_km") or 0) * 1000,
            "ascend_m": summary.get("elevation_difference_m") or 0,
        },
        "geometry": geometry,
    }


def _coordinates(geometry: Any) -> list[list[float]]:
    value = geometry if isinstance(geometry, dict) else {}
    points = [
        [float(point[0]), float(point[1])]
        for point in value.get("coordinates") or []
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    if value.get("type") != "LineString" or len(points) < 2:
        raise ValueError("route geometry must be a usable LineString")
    return points


def _line_distance_m(points: Sequence[Sequence[float]]) -> float:
    return sum(haversine_m(first, second) for first, second in zip(points, points[1:]))


def _append_warning(target: dict[str, Any], warning: str) -> None:
    target["warnings"] = [*list(target.get("warnings") or []), warning]


def _add_final_elevation(
    plan: dict[str, Any],
    include_elevation: bool,
    elevation_builder: ElevationBuilder | None,
) -> dict[str, Any]:
    if not include_elevation or elevation_builder is None:
        return plan
    for _, target in _plan_targets(plan):
        geometry = _coordinates(target.get("geometry"))
        try:
            target["elevation"] = elevation_builder(geometry, float(target.get("distance_m") or 0))
        except (RuntimeError, ValueError) as exc:
            _append_warning(target, f"海拔请求失败：{exc}")
            target["elevation"] = None
    return plan
