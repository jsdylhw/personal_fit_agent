from __future__ import annotations

from typing import Any, Callable

import pandas as pd

IndicatorHandler = Callable[[dict[str, Any]], Any]


def get_distance(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {
        "distance_m": activity.get("distance_m"),
        "distance_km": activity.get("distance_km"),
    }


def get_duration(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {
        "timer_seconds": activity.get("timer_seconds"),
        "elapsed_seconds": activity.get("elapsed_seconds"),
        "moving_seconds": activity.get("moving_seconds"),
    }


def get_tss(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {"tss": activity.get("tss")}


def get_if(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {"intensity_factor": activity.get("intensity_factor")}


def get_power(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {
        "average_power": activity.get("avg_power"),
        "normalized_power": activity.get("np_power"),
        "max_power": activity.get("max_power"),
    }


def get_heart_rate(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {
        "average_heart_rate": activity.get("avg_hr"),
        "max_heart_rate": activity.get("max_hr"),
    }


def get_speed(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {
        "average_speed_mps": activity.get("avg_speed_mps"),
        "max_speed_mps": activity.get("max_speed_mps"),
        "average_speed_kmh_from_distance": activity.get("avg_speed_kmh_from_distance"),
    }


def get_training_effect(analysis: dict[str, Any]) -> dict[str, Any]:
    activity = analysis.get("activity_metrics", {})
    return {
        "training_effect": activity.get("training_effect"),
        "anaerobic_training_effect": activity.get("anaerobic_training_effect"),
        "training_load_peak": activity.get("training_load_peak"),
    }


def get_thresholds(analysis: dict[str, Any]) -> dict[str, Any]:
    metadata = analysis.get("llm_context", {}).get("training_metadata", {})
    zones = metadata.get("zones_target") or {}
    session_zone = _session_zone(metadata)
    return {
        "functional_threshold_power": zones.get("functional_threshold_power")
        or session_zone.get("functional_threshold_power"),
        "max_heart_rate": zones.get("max_heart_rate") or session_zone.get("max_heart_rate"),
        "threshold_heart_rate": zones.get("threshold_heart_rate")
        or session_zone.get("threshold_heart_rate"),
        "resting_heart_rate": session_zone.get("resting_heart_rate"),
        "heart_rate_calc_type": zones.get("hr_calc_type") or session_zone.get("hr_calc_type"),
        "power_calc_type": zones.get("pwr_calc_type") or session_zone.get("pwr_calc_type"),
    }


def get_zone_time(analysis: dict[str, Any]) -> dict[str, Any]:
    metadata = analysis.get("llm_context", {}).get("training_metadata", {})
    return {"time_in_zone": metadata.get("time_in_zone") or []}


def get_laps(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    return analysis.get("lap_summaries", [])


def get_time_series_summary(analysis: dict[str, Any], bucket_seconds: int = 60) -> dict[str, Any]:
    bucket_seconds = _normalize_bucket_seconds(bucket_seconds)
    records = analysis.get("records") or []
    df = pd.DataFrame(records)
    if df.empty or "elapsed_s" not in df.columns:
        return {
            "bucket_seconds": bucket_seconds,
            "buckets": [],
            "message": "no record time series available",
        }

    df = df.copy()
    df["bucket_index"] = (pd.to_numeric(df["elapsed_s"], errors="coerce") // bucket_seconds).astype("Int64")
    df = df.dropna(subset=["bucket_index"])
    if df.empty:
        return {"bucket_seconds": bucket_seconds, "buckets": []}

    fields = {
        "heart_rate": "heart_rate_bpm",
        "power": "power_w",
        "cadence": "cadence_rpm",
        "enhanced_speed": "speed_mps",
        "speed": "speed_mps",
    }
    buckets: list[dict[str, Any]] = []
    for bucket_index, group in df.groupby("bucket_index", sort=True):
        start_s = int(bucket_index) * bucket_seconds
        item: dict[str, Any] = {
            "start_s": start_s,
            "end_s": start_s + bucket_seconds,
            "sample_count": int(len(group)),
        }
        for source_field, output_name in fields.items():
            if source_field not in group.columns or output_name in item:
                continue
            stats = _bucket_stats(group[source_field])
            if stats:
                item[output_name] = stats
        if "distance" in group.columns:
            distance = pd.to_numeric(group["distance"], errors="coerce").dropna()
            if not distance.empty:
                item["distance_m"] = {
                    "start": float(distance.iloc[0]),
                    "end": float(distance.iloc[-1]),
                    "delta": float(distance.iloc[-1] - distance.iloc[0]),
                }
        buckets.append(item)

    return {
        "bucket_seconds": bucket_seconds,
        "bucket_count": len(buckets),
        "fields": ["heart_rate_bpm", "power_w", "cadence_rpm", "speed_mps", "distance_m"],
        "buckets": buckets,
    }


INDICATOR_HANDLERS: dict[str, IndicatorHandler] = {
    "request_distance": get_distance,
    "request_duration": get_duration,
    "request_tss": get_tss,
    "request_if": get_if,
    "request_power": get_power,
    "request_heart_rate": get_heart_rate,
    "request_speed": get_speed,
    "request_training_effect": get_training_effect,
    "request_thresholds": get_thresholds,
    "request_zone_time": get_zone_time,
    "request_laps": get_laps,
    "request_time_series_summary": get_time_series_summary,
}


def indicator_catalog() -> list[dict[str, str]]:
    return [
        {"name": "request_distance", "description": "返回距离，单位 m/km。"},
        {"name": "request_duration", "description": "返回计时时长、总 elapsed、估算移动时间。"},
        {"name": "request_tss", "description": "返回 Training Stress Score。"},
        {"name": "request_if", "description": "返回 Intensity Factor。"},
        {"name": "request_power", "description": "返回平均功率、NP、最大功率。"},
        {"name": "request_heart_rate", "description": "返回平均心率、最大心率。"},
        {"name": "request_speed", "description": "返回平均/最大速度。"},
        {"name": "request_training_effect", "description": "返回有氧/无氧训练效果和训练负荷峰值。"},
        {"name": "request_thresholds", "description": "返回 FTP、最大心率、阈值心率、静息心率和分区算法。"},
        {"name": "request_zone_time", "description": "返回心率/功率分区边界和各区间时间。"},
        {"name": "request_laps", "description": "返回分圈摘要。"},
        {"name": "request_time_series_summary", "description": "按 10/30/60 秒分桶返回心率、功率、踏频、速度、距离摘要。"},
    ]


def _session_zone(metadata: dict[str, Any]) -> dict[str, Any]:
    for row in metadata.get("time_in_zone") or []:
        if row.get("reference_mesg") == "session":
            return row
    return {}


def _normalize_bucket_seconds(value: int) -> int:
    if value not in {10, 30, 60}:
        raise ValueError("bucket_seconds 只支持 10、30、60")
    return value


def _bucket_stats(series: pd.Series) -> dict[str, Any] | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return {
        "avg": float(numeric.mean()),
        "min": float(numeric.min()),
        "max": float(numeric.max()),
    }
