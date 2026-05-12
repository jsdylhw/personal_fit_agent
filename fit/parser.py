from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import fitdecode
import pandas as pd

TRAINING_MESSAGE_NAMES = {
    "training_settings",
    "zones_target",
    "time_in_zone",
    "hrv",
    "user_profile",
    "device_info",
    "device_settings",
    "event",
    "split",
    "split_summary",
}


def _field_dict(frame: fitdecode.FitDataMessage) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in frame.fields:
        values[field.name] = _clean_value(field.value)
    return values


def parse_fit(path: str | Path) -> dict[str, Any]:
    fit_path = Path(path)
    records: list[dict[str, Any]] = []
    laps: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    sports: list[dict[str, Any]] = []
    training_messages: dict[str, list[dict[str, Any]]] = {
        name: [] for name in sorted(TRAINING_MESSAGE_NAMES)
    }

    with fitdecode.FitReader(str(fit_path)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            values = _field_dict(frame)
            if frame.name == "record":
                records.append(values)
            elif frame.name == "lap":
                laps.append(values)
            elif frame.name == "session":
                sessions.append(values)
            elif frame.name == "sport":
                sports.append(values)
            if frame.name in training_messages:
                training_messages[frame.name].append(values)

    summary = summarize_fit(records, laps, sessions, sports)
    training_metadata = summarize_training_metadata(training_messages)
    return {
        "path": str(fit_path),
        "summary": summary,
        "records": records,
        "laps": laps,
        "sessions": sessions,
        "sports": sports,
        "training_metadata": training_metadata,
    }


def summarize_fit(
    records: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    sports: list[dict[str, Any]],
) -> dict[str, Any]:
    session = sessions[-1] if sessions else {}
    sport_msg = sports[-1] if sports else {}
    first_record = records[0] if records else {}
    last_record = records[-1] if records else {}

    start = (
        session.get("start_time")
        or first_record.get("timestamp")
        or session.get("timestamp")
    )
    duration_s = session.get("total_timer_time") or session.get("total_elapsed_time")
    distance_m = session.get("total_distance") or last_record.get("distance")

    return {
        "sport_type": str(session.get("sport") or sport_msg.get("sport") or "unknown"),
        "sub_sport": str(session.get("sub_sport") or sport_msg.get("sub_sport") or ""),
        "start_time": _iso(start),
        "duration_s": _num(duration_s),
        "distance_m": _num(distance_m),
        "record_count": len(records),
        "lap_count": len(laps),
        "has_power": any("power" in r for r in records),
        "has_heart_rate": any("heart_rate" in r for r in records),
        "has_position": any("position_lat" in r and "position_long" in r for r in records),
    }


def records_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")
        df["elapsed_s"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    return df


def summarize_training_metadata(messages: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "message_counts": {
            name: len(rows)
            for name, rows in messages.items()
            if rows
        },
        "training_settings": _select_keys(
            _last(messages.get("training_settings")) or {},
            ["target_distance", "target_speed", "target_time"],
        ),
        "zones_target": _select_keys(
            _last(messages.get("zones_target")) or {},
            [
                "functional_threshold_power",
                "max_heart_rate",
                "threshold_heart_rate",
                "hr_calc_type",
                "pwr_calc_type",
            ],
        ),
        "time_in_zone": [_compact_time_in_zone(row) for row in messages.get("time_in_zone", [])],
        "hrv": _summarize_hrv(messages.get("hrv", [])),
        "user_profile": _compact_user_profile(_last(messages.get("user_profile")) or {}),
        "device_info": [_compact_device_info(row) for row in messages.get("device_info", [])],
        "device_settings": _select_keys(
            _last(messages.get("device_settings")) or {},
            ["lactate_threshold_autodetect_enabled", "activity_tracker_enabled", "move_alert_enabled"],
        ),
        "events": [_compact_event(row) for row in messages.get("event", [])],
        "splits": [_compact_split(row) for row in messages.get("split", [])],
        "split_summary": [_compact_split(row) for row in messages.get("split_summary", [])],
    }


def _summarize_hrv(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [_num(row.get("time")) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return {"count": len(rows)}
    return {
        "count": len(rows),
        "time_min": min(values),
        "time_max": max(values),
        "time_avg": sum(values) / len(values),
    }


def _last(rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    return rows[-1] if rows else None


def _select_keys(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if key in row}


def _compact_time_in_zone(row: dict[str, Any]) -> dict[str, Any]:
    return _select_keys(
        row,
        [
            "timestamp",
            "reference_mesg",
            "reference_index",
            "functional_threshold_power",
            "max_heart_rate",
            "resting_heart_rate",
            "threshold_heart_rate",
            "hr_calc_type",
            "pwr_calc_type",
            "hr_zone_high_boundary",
            "power_zone_high_boundary",
            "time_in_hr_zone",
            "time_in_power_zone",
        ],
    )


def _compact_user_profile(row: dict[str, Any]) -> dict[str, Any]:
    return _select_keys(
        row,
        [
            "friendly_name",
            "gender",
            "age",
            "height",
            "weight",
            "resting_heart_rate",
            "default_max_biking_heart_rate",
            "default_max_heart_rate",
            "hr_setting",
            "power_setting",
            "activity_class",
        ],
    )


def _compact_device_info(row: dict[str, Any]) -> dict[str, Any]:
    return _select_keys(
        row,
        [
            "timestamp",
            "manufacturer",
            "garmin_product",
            "product",
            "software_version",
            "device_index",
            "local_device_type",
            "antplus_device_type",
            "source_type",
            "battery_status",
            "battery_level",
        ],
    )


def _compact_event(row: dict[str, Any]) -> dict[str, Any]:
    return _select_keys(
        row,
        ["timestamp", "event", "event_type", "timer_trigger", "event_group", "data"],
    )


def _compact_split(row: dict[str, Any]) -> dict[str, Any]:
    return _select_keys(
        row,
        [
            "message_index",
            "split_type",
            "start_time",
            "end_time",
            "total_elapsed_time",
            "total_timer_time",
            "total_distance",
            "avg_speed",
            "max_speed",
            "avg_heart_rate",
            "max_heart_rate",
            "total_ascent",
            "total_descent",
            "total_calories",
            "num_splits",
        ],
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _clean_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _clean_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
