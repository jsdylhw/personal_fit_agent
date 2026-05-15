"""FIT 只读数据查询工具:activity_overview / summary / time_intervals / distance_intervals.

每个函数接收 parse_fit() 输出的 parsed dict,返回 LLM 可直接消费的结构化数据.
被 agent/tools.py 路由调用.
"""

from __future__ import annotations

from typing import Any

from fit.parser import records_dataframe

from .stats import (
    _distance_delta,
    _duration_from_group,
    _filter_numeric_window,
    _first_number,
    _last_item,
    _meters_to_km,
    _mps_to_kmh,
    _normalize_bucket_distance_m,
    _normalize_bucket_seconds,
    _numeric_field_stats,
    _round_float,
    _rows_to_column_arrays,
    _seconds_to_minutes,
    _select_stats,
    _series_stats,
    _stats_value,
    prune_empty_values,
)

# get_activity_summary 支持的全部 section
SUMMARY_SECTIONS = [
    "activity_identity", "duration_distance",
    "power", "heart_rate", "cadence", "speed", "elevation",
    "energy_load", "training_zones", "laps", "device_profile",
]

# 默认只返回核心 section,避免一次工具调用消耗过多 token
DEFAULT_SECTIONS = [
    "activity_identity", "duration_distance",
    "power", "heart_rate", "cadence", "speed", "elevation",
    "energy_load",
]


# =============================================================================
# 工具入口(被 agent/tools.py 路由调用)
# =============================================================================

def get_activity_overview_tool(parsed: dict[str, Any]) -> dict[str, Any]:
    """高层活动概览:运动类型,时长/距离/爬升,功率/心率/踏频均值,TSS/IF,数据可用性.

    适合 LLM 第一眼快速了解活动规模和传感器覆盖情况.

    Args:
        parsed: parse_fit() 的返回值.

    Returns:
        dict: {activity_identity, scale, basic_metrics, data_availability}
    """
    summary = parsed.get("summary") or {}
    session = _last_item(parsed.get("sessions")) or {}
    stats = _numeric_field_stats(records_dataframe(parsed.get("records", [])))

    duration_s = _first_number(summary.get("duration_s"), session.get("total_timer_time"), session.get("total_elapsed_time"))
    distance_m = _first_number(summary.get("distance_m"), session.get("total_distance"))
    calories = _first_number(session.get("total_calories"))
    avg_power = _first_number(session.get("avg_power"), _stats_value(stats, "power", "avg"))
    max_power = _first_number(session.get("max_power"), _stats_value(stats, "power", "max"))
    avg_hr = _first_number(session.get("avg_heart_rate"), _stats_value(stats, "heart_rate", "avg"))
    max_hr = _first_number(session.get("max_heart_rate"), _stats_value(stats, "heart_rate", "max"))
    avg_cadence = _first_number(session.get("avg_cadence"), _stats_value(stats, "cadence", "avg"))
    avg_speed = _first_number(session.get("enhanced_avg_speed"), session.get("avg_speed"), _stats_value(stats, "enhanced_speed", "avg"))
    total_ascent = _round_float(session.get("total_ascent"), 1)

    return {
        "schema_version": "activity_overview.v1",
        "activity_identity": {
            "sport_type": summary.get("sport_type"),
            "sub_sport": summary.get("sub_sport"),
            "start_time_local": summary.get("start_time_local"),
            "start_time_utc": summary.get("start_time_utc") or summary.get("start_time"),
        },
        "scale": {
            "duration_min": _seconds_to_minutes(duration_s),
            "distance_km": _meters_to_km(distance_m),
            "total_ascent_m": total_ascent,
            "calories": _round_float(calories, 0),
        },
        "basic_metrics": {
            "avg_speed_kmh": _mps_to_kmh(avg_speed),
            "avg_power_w": _round_float(avg_power, 1),
            "max_power_w": _round_float(max_power, 1),
            "normalized_power_w": _round_float(session.get("normalized_power"), 1),
            "avg_hr_bpm": _round_float(avg_hr, 1),
            "max_hr_bpm": _round_float(max_hr, 1),
            "avg_cadence_rpm": _round_float(avg_cadence, 1),
            "tss": _round_float(session.get("training_stress_score"), 1),
            "intensity_factor": _round_float(session.get("intensity_factor"), 3),
        },
        "data_availability": {
            "record_count": summary.get("record_count"),
            "lap_count": summary.get("lap_count"),
            "has_power": summary.get("has_power"),
            "has_heart_rate": summary.get("has_heart_rate"),
            "has_position": summary.get("has_position"),
            "has_cadence": "cadence" in stats,
            "has_altitude": "enhanced_altitude" in stats or "altitude" in stats,
        },
    }


def get_activity_summary_tool(parsed: dict[str, Any], *, sections: Any = None) -> dict[str, Any]:
    """按 section 返回结构化活动摘要,支持按需取用以减少 token.

    不带参数返回 DEFAULT_SECTIONS(核心 8 项),"all" 返回全部 11 项.
    数据类 section(power/heart_rate/cadence/speed/elevation)结构统一:
        {available, record_count_with_data, stats, summary}

    Args:
        parsed: parse_fit() 的返回值.
        sections: None/"all"/["power","heart_rate",...]

    Returns:
        dict: {schema_version, sections, <section_name>: {...}, ...}
    """
    requested = _normalize_summary_sections(sections)
    summary = parsed.get("summary") or {}
    session = _last_item(parsed.get("sessions")) or {}
    metadata = parsed.get("training_metadata") or {}
    stats = _numeric_field_stats(records_dataframe(parsed.get("records", [])))

    section_builders = {
        "activity_identity": lambda: _build_activity_identity(parsed, summary),
        "duration_distance": lambda: _build_duration_distance(summary, session),
        "power": lambda: _build_power(session, stats, metadata),
        "heart_rate": lambda: _build_heart_rate(session, stats, metadata),
        "cadence": lambda: _build_cadence(session, stats),
        "speed": lambda: _build_speed(session, stats),
        "elevation": lambda: _build_elevation(session, stats),
        "energy_load": lambda: _build_energy_load(session),
        "training_zones": lambda: _build_training_zones(metadata),
        "laps": lambda: _build_laps(parsed.get("laps") or []),
        "device_profile": lambda: _build_device_profile(metadata),
    }

    result: dict[str, Any] = {"schema_version": "activity_summary.v1", "sections": requested}
    for section in requested:
        builder = section_builders.get(section)
        if builder:
            result[section] = builder()
    return result


def get_time_intervals_tool(
    parsed: dict[str, Any], *, bucket_seconds: int = 60, start_s: Any = None, end_s: Any = None,
) -> dict[str, Any]:
    """固定时间窗口的聚合数据,返回 column_arrays 格式以节省 token.

    用于让 LLM 检查冲刺,间歇,滑行,后半程掉速等时间维度的片段.
    功率/踏频/速度的 avg_nonzero_* 和 *_zero_fraction 用于区分滑行/停车.

    Args:
        parsed: parse_fit() 的返回值.
        bucket_seconds: 窗口秒数 [1, 600],默认 60.
        start_s: 起始时间秒数(可选,用于聚焦短片段).
        end_s: 结束时间秒数(可选).

    Returns:
        dict: available=False 时只有 reason;available=True 时包含 series.
    """
    df = records_dataframe(parsed.get("records", []))
    if df.empty or "elapsed_s" not in df.columns:
        return {"available": False, "reason": "No records or elapsed_s data available."}

    bucket_seconds = _normalize_bucket_seconds(bucket_seconds)
    working = _filter_numeric_window(df, "elapsed_s", start=start_s, end=end_s)
    if working.empty:
        return {
            "available": False, "reason": "No records in requested time window.",
            "mode": "time", "bucket_seconds": bucket_seconds,
            "window": {"start_s": _round_float(start_s, 1), "end_s": _round_float(end_s, 1)},
        }

    rows = _build_interval_rows(working, "time", bucket_seconds)
    return {
        "available": True, "mode": "time", "bucket_seconds": bucket_seconds,
        "record_count": int(len(df)), "filtered_count": int(len(working)),
        "bucket_count": len(rows),
        "window": {"start_s": _round_float(start_s, 1), "end_s": _round_float(end_s, 1)},
        "format": "column_arrays", "series": _rows_to_column_arrays(rows),
    }


def get_distance_intervals_tool(
    parsed: dict[str, Any], *, bucket_distance_m: Any = 1000, start_d: Any = None, end_d: Any = None,
) -> dict[str, Any]:
    """固定距离窗口的聚合数据,返回 column_arrays 格式以节省 token.

    用于分析每公里配速变化,爬坡段功率/心率响应.
    支持 start_d/end_d 聚焦特定路段.

    Args:
        parsed: parse_fit() 的返回值.
        bucket_distance_m: 窗口米数(100/200/500/1000/3000/5000/10000),默认 1000.
        start_d: 起始距离米数(可选).
        end_d: 结束距离米数(可选).

    Returns:
        dict: available=False 时只有 reason;available=True 时包含 series.
    """
    df = records_dataframe(parsed.get("records", []))
    if df.empty or "distance" not in df.columns:
        return {"available": False, "reason": "No records or distance data available."}

    bucket_distance_m = _normalize_bucket_distance_m(bucket_distance_m)
    working = _filter_numeric_window(df, "distance", start=start_d, end=end_d)
    if working.empty:
        return {
            "available": False, "reason": "No records in requested distance window.",
            "mode": "distance", "bucket_distance_m": bucket_distance_m,
            "window": {"start_d": _round_float(start_d, 1), "end_d": _round_float(end_d, 1)},
        }

    rows = _build_interval_rows(working, "distance", bucket_distance_m)
    return {
        "available": True, "mode": "distance", "bucket_distance_m": bucket_distance_m,
        "record_count": int(len(df)), "filtered_count": int(len(working)),
        "bucket_count": len(rows),
        "window": {"start_d": _round_float(start_d, 1), "end_d": _round_float(end_d, 1)},
        "format": "column_arrays", "series": _rows_to_column_arrays(rows),
    }


# =============================================================================
# 内部 helper
# =============================================================================

def _build_interval_rows(working: Any, mode: str, bucket_size: int) -> list[dict[str, Any]]:
    """time/distance intervals 共用的分组统计逻辑."""
    column = "elapsed_s" if mode == "time" else "distance"
    start_key = "start_s" if mode == "time" else "start_d"
    end_key = "end_s" if mode == "time" else "end_d"

    working["bucket_index"] = (working[column].astype(float) // bucket_size).astype(int)
    rows: list[dict[str, Any]] = []

    for bucket_index, group in working.groupby("bucket_index", sort=True):
        bucket_start = float(bucket_index) * bucket_size
        bucket_end = bucket_start + bucket_size
        row: dict[str, Any] = {
            start_key: _round_float(bucket_start, 1),
            end_key: _round_float(bucket_end, 1),
            "duration_s": _round_float(_duration_from_group(group), 1),
            "samples": int(len(group)),
        }
        row.update(_distance_delta(group))
        row.update(_series_stats(group, "heart_rate", "hr_bpm"))
        # 功率/踏频/速度的 0 值有训练含义(滑行,停踩,停车),保留占比
        row.update(_series_stats(group, "power", "power_w", include_zero_stats=True))
        row.update(_series_stats(group, "cadence", "cadence_rpm", include_zero_stats=True))
        row.update(_series_stats(group, "enhanced_speed", "speed_mps", include_zero_stats=True))
        row.update(_series_stats(group, "enhanced_altitude", "altitude_m"))
        rows.append(prune_empty_values(row))

    return rows


def _normalize_summary_sections(value: Any) -> list[str]:
    """标准化 sections 参数.None → DEFAULT_SECTIONS,"all" → SUMMARY_SECTIONS."""
    if value in (None, "", []):
        return list(DEFAULT_SECTIONS)
    if isinstance(value, str):
        raw_sections = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        raw_sections = [str(part).strip() for part in value if str(part).strip()]
    else:
        raw_sections = []
    if not raw_sections or "all" in raw_sections:
        return list(SUMMARY_SECTIONS)
    return [section for section in SUMMARY_SECTIONS if section in raw_sections]


# =============================================================================
# section builder — 每个 section 的构建函数
# =============================================================================

def _build_activity_identity(parsed: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_file": parsed.get("path"),
        "sport_type": summary.get("sport_type"),
        "sub_sport": summary.get("sub_sport"),
        "start_time_local": summary.get("start_time_local"),
        "start_time_utc": summary.get("start_time_utc") or summary.get("start_time"),
        "timezone_note": summary.get("timezone_note"),
    }


def _build_duration_distance(summary: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    duration_s = _first_number(summary.get("duration_s"), session.get("total_timer_time"))
    elapsed_s = _first_number(session.get("total_elapsed_time"), duration_s)
    distance_m = _first_number(summary.get("distance_m"), session.get("total_distance"))
    return {
        "duration_s": _round_float(duration_s, 1), "duration_min": _seconds_to_minutes(duration_s),
        "elapsed_s": _round_float(elapsed_s, 1), "elapsed_min": _seconds_to_minutes(elapsed_s),
        "distance_m": _round_float(distance_m, 1), "distance_km": _meters_to_km(distance_m),
    }


def _build_power(session: dict[str, Any], stats: dict[str, dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    """功率 section:{available, record_count_with_data, stats, summary}."""
    zones_target = metadata.get("zones_target") or {}
    power_stats = _select_stats(stats, "power")
    avg_power = _first_number(session.get("avg_power"), _stats_value(stats, "power", "avg"))
    normalized_power = _first_number(session.get("normalized_power"))

    return {
        "available": bool(power_stats),
        "record_count_with_data": power_stats.get("count"),
        "stats": power_stats,
        "summary": {
            "avg_power_w": _round_float(avg_power, 1),
            "max_power_w": _round_float(_first_number(session.get("max_power"), _stats_value(stats, "power", "max")), 1),
            "normalized_power_w": _round_float(normalized_power, 1),
            "threshold_power_w": _round_float(_first_number(session.get("threshold_power"), zones_target.get("functional_threshold_power")), 1),
            "intensity_factor": _round_float(session.get("intensity_factor"), 3),
            # VI = NP / AP,> 1.05 通常表示节奏不稳定
            "variability_index": _round_float((normalized_power / avg_power) if avg_power and normalized_power else None, 3),
            "total_work_kj": _round_float(_first_number(session.get("total_work")) / 1000 if _first_number(session.get("total_work")) is not None else None, 1),
        },
    }


def _build_heart_rate(session: dict[str, Any], stats: dict[str, dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    hr_stats = _select_stats(stats, "heart_rate")
    zones_target = metadata.get("zones_target") or {}
    profile = metadata.get("user_profile") or {}

    return {
        "available": bool(hr_stats),
        "record_count_with_data": hr_stats.get("count"),
        "stats": hr_stats,
        "summary": {
            "avg_hr_bpm": _round_float(_first_number(session.get("avg_heart_rate"), _stats_value(stats, "heart_rate", "avg")), 1),
            "max_hr_bpm": _round_float(_first_number(session.get("max_heart_rate"), _stats_value(stats, "heart_rate", "max")), 1),
            "resting_hr_bpm": _round_float(profile.get("resting_heart_rate"), 1),
            "max_hr_setting_bpm": _round_float(_first_number(zones_target.get("max_heart_rate"), profile.get("default_max_biking_heart_rate"), profile.get("default_max_heart_rate")), 1),
            "threshold_hr_bpm": _round_float(zones_target.get("threshold_heart_rate"), 1),
        },
    }


def _build_cadence(session: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cadence_stats = _select_stats(stats, "cadence")
    return {
        "available": "cadence" in stats,
        "record_count_with_data": cadence_stats.get("count"),
        "stats": cadence_stats,
        "summary": {
            "avg_cadence_rpm": _round_float(_first_number(session.get("avg_cadence"), _stats_value(stats, "cadence", "avg")), 1),
            "max_cadence_rpm": _round_float(_first_number(session.get("max_cadence"), _stats_value(stats, "cadence", "max")), 1),
        },
    }


def _build_speed(session: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    speed_stats = _select_stats(stats, "enhanced_speed") or _select_stats(stats, "speed")
    return {
        "available": bool(speed_stats),
        "record_count_with_data": speed_stats.get("count"),
        "stats": speed_stats,
        "summary": {
            "avg_speed_mps": _round_float(_first_number(session.get("enhanced_avg_speed"), session.get("avg_speed"), _stats_value(stats, "enhanced_speed", "avg")), 3),
            "max_speed_mps": _round_float(_first_number(session.get("enhanced_max_speed"), session.get("max_speed"), _stats_value(stats, "enhanced_speed", "max")), 3),
            "avg_speed_kmh": _mps_to_kmh(_first_number(session.get("enhanced_avg_speed"), session.get("avg_speed"), _stats_value(stats, "enhanced_speed", "avg"))),
            "max_speed_kmh": _mps_to_kmh(_first_number(session.get("enhanced_max_speed"), session.get("max_speed"), _stats_value(stats, "enhanced_speed", "max"))),
        },
    }


def _build_elevation(session: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    alt_stats = _select_stats(stats, "enhanced_altitude") or _select_stats(stats, "altitude")
    return {
        "available": bool(alt_stats),
        "record_count_with_data": alt_stats.get("count"),
        "stats": alt_stats,
        "summary": {
            "total_ascent_m": _round_float(session.get("total_ascent"), 1),
            "total_descent_m": _round_float(session.get("total_descent"), 1),
        },
    }


def _build_energy_load(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "calories": _round_float(session.get("total_calories"), 0),
        "tss": _round_float(session.get("training_stress_score"), 1),
        "training_load_peak": _round_float(session.get("training_load_peak"), 1),
        "aerobic_training_effect": _round_float(session.get("total_training_effect"), 1),
        "anaerobic_training_effect": _round_float(session.get("total_anaerobic_training_effect"), 1),
    }


def _build_training_zones(metadata: dict[str, Any]) -> dict[str, Any]:
    """FIT 文件中的原始区间定义和时间分布."""
    zones_target = metadata.get("zones_target") or {}
    return {"zones_target": zones_target, "time_in_zone": metadata.get("time_in_zone")}


def _build_laps(laps: list[dict[str, Any]]) -> dict[str, Any]:
    compact_laps: list[dict[str, Any]] = []
    for index, lap in enumerate(laps, start=1):
        compact_laps.append({
            "index": index,
            "start_time": lap.get("start_time"),
            "total_timer_time": _round_float(lap.get("total_timer_time"), 1),
            "total_elapsed_time": _round_float(lap.get("total_elapsed_time"), 1),
            "total_distance": _round_float(lap.get("total_distance"), 1),
            "avg_speed": _round_float(_first_number(lap.get("enhanced_avg_speed"), lap.get("avg_speed")), 3),
            "avg_power": _round_float(lap.get("avg_power"), 1),
            "max_power": _round_float(lap.get("max_power"), 1),
            "avg_heart_rate": _round_float(lap.get("avg_heart_rate"), 1),
            "max_heart_rate": _round_float(lap.get("max_heart_rate"), 1),
            "avg_cadence": _round_float(lap.get("avg_cadence"), 1),
            "total_ascent": _round_float(lap.get("total_ascent"), 1),
            "total_descent": _round_float(lap.get("total_descent"), 1),
        })
    return {"lap_count": len(laps), "laps": compact_laps}


def _build_device_profile(metadata: dict[str, Any]) -> dict[str, Any]:
    devices = metadata.get("device_info") or []
    device = devices[-1] if isinstance(devices, list) and devices else {}
    return {
        "user_profile": metadata.get("user_profile"),
        "device": device,
        "device_settings": metadata.get("device_settings"),
    }
