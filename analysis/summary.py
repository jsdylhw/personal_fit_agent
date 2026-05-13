from __future__ import annotations

from typing import Any


def get_activity_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    metrics = analysis.get("activity_metrics", {})
    samples = analysis.get("sample_statistics", {})
    thresholds = _thresholds(analysis)

    avg_power = metrics.get("avg_power")
    np_power = metrics.get("np_power")
    vi = None
    if avg_power and np_power:
        vi = round(float(np_power) / float(avg_power), 3)

    duration_s = metrics.get("timer_seconds") or metrics.get("elapsed_seconds")
    distance_km = metrics.get("distance_km")
    if distance_km is None and metrics.get("distance_m") is not None:
        distance_km = round(float(metrics["distance_m"]) / 1000, 3)

    return {
        "schema_version": "activity_summary.v1",
        "sport_type": metrics.get("sport_type"),
        "sub_sport": metrics.get("sub_sport"),
        "start_time": metrics.get("start_time"),
        "duration_seconds": duration_s,
        "duration_min": _round(duration_s / 60, 1) if duration_s else None,
        "moving_seconds": metrics.get("moving_seconds"),
        "distance_m": metrics.get("distance_m"),
        "distance_km": distance_km,
        "ascent_m": metrics.get("ascent_m"),
        "descent_m": metrics.get("descent_m"),
        "average_speed_kmh": metrics.get("avg_speed_kmh_from_distance"),
        "average_power": avg_power,
        "normalized_power": np_power,
        "max_power": metrics.get("max_power"),
        "average_heart_rate": metrics.get("avg_hr"),
        "max_heart_rate": metrics.get("max_hr"),
        "average_cadence": _sample_avg(samples, "cadence_rpm"),
        "average_cadence_nonzero": _sample_nonzero_avg(samples, "cadence_rpm"),
        "energy_kj": metrics.get("energy_kj"),
        "calories": metrics.get("calories"),
        "tss": metrics.get("tss"),
        "intensity_factor": metrics.get("intensity_factor"),
        "variability_index": vi,
        "thresholds": thresholds,
        "summary_label": _summary_label(metrics.get("tss"), metrics.get("intensity_factor")),
    }


def _thresholds(analysis: dict[str, Any]) -> dict[str, Any]:
    metadata = analysis.get("llm_context", {}).get("training_metadata", {})
    zones = metadata.get("zones_target") or {}
    session_zone = {}
    for row in metadata.get("time_in_zone") or []:
        if row.get("reference_mesg") == "session":
            session_zone = row
            break
    return {
        "functional_threshold_power": zones.get("functional_threshold_power")
        or session_zone.get("functional_threshold_power"),
        "max_heart_rate": zones.get("max_heart_rate") or session_zone.get("max_heart_rate"),
        "threshold_heart_rate": zones.get("threshold_heart_rate")
        or session_zone.get("threshold_heart_rate"),
        "resting_heart_rate": session_zone.get("resting_heart_rate"),
    }


def _summary_label(tss: float | None, intensity_factor: float | None) -> str:
    if intensity_factor is not None:
        if intensity_factor < 0.55:
            return "低强度恢复或轻松活动"
        if intensity_factor < 0.75:
            return "低到中等强度有氧训练"
        if intensity_factor < 0.9:
            return "中高强度节奏训练"
        return "高强度阈值或比赛型训练"
    if tss is not None:
        if tss < 30:
            return "低训练负荷"
        if tss < 80:
            return "中等训练负荷"
        return "较高训练负荷"
    return "训练负荷未知"


def _sample_avg(samples: dict[str, Any], key: str) -> float | None:
    value = (samples.get(key) or {}).get("avg")
    return _round(value, 1)


def _sample_nonzero_avg(samples: dict[str, Any], key: str) -> float | None:
    value = (samples.get(key) or {}).get("nonzero_avg")
    return _round(value, 1)


def _round(value: Any, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
