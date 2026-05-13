from __future__ import annotations

from typing import Any

import pandas as pd


def detect_workout_segments(analysis: dict[str, Any], bucket_seconds: int = 60) -> dict[str, Any]:
    bucket_seconds = _normalize_bucket_seconds(bucket_seconds)
    records = analysis.get("records") or []
    df = pd.DataFrame(records)
    if df.empty or "elapsed_s" not in df.columns:
        return {
            "schema_version": "workout_segments.v1",
            "bucket_seconds": bucket_seconds,
            "segments": [],
            "structure_label": "缺少时序数据，无法识别分段",
        }

    buckets = _build_buckets(df, bucket_seconds)
    if not buckets:
        return {
            "schema_version": "workout_segments.v1",
            "bucket_seconds": bucket_seconds,
            "segments": [],
            "structure_label": "缺少有效时序数据，无法识别分段",
        }

    ftp = _thresholds(analysis).get("functional_threshold_power")
    typed = [_classify_bucket(bucket, ftp) for bucket in buckets]
    segments = _merge_segments(typed, bucket_seconds)

    return {
        "schema_version": "workout_segments.v1",
        "bucket_seconds": bucket_seconds,
        "segments": segments,
        "structure_label": _structure_label(segments),
    }


def _build_buckets(df: pd.DataFrame, bucket_seconds: int) -> list[dict[str, Any]]:
    work = df.copy()
    work["elapsed_s"] = pd.to_numeric(work["elapsed_s"], errors="coerce")
    work = work.dropna(subset=["elapsed_s"])
    if work.empty:
        return []
    work["bucket_index"] = (work["elapsed_s"] // bucket_seconds).astype(int)
    buckets: list[dict[str, Any]] = []
    for index, group in work.groupby("bucket_index", sort=True):
        elapsed = pd.to_numeric(group["elapsed_s"], errors="coerce").dropna()
        bucket = {
            "bucket_index": int(index),
            "start_s": float(elapsed.min()) if not elapsed.empty else int(index) * bucket_seconds,
            "end_s": float(elapsed.max()) if not elapsed.empty else (int(index) + 1) * bucket_seconds,
            "avg_power": _avg(group, "power"),
            "avg_hr": _avg(group, "heart_rate"),
            "avg_cadence": _avg(group, "cadence"),
            "avg_speed": _avg_any(group, ["enhanced_speed", "speed"]),
        }
        buckets.append(bucket)
    return buckets


def _classify_bucket(bucket: dict[str, Any], ftp: float | None) -> dict[str, Any]:
    power = bucket.get("avg_power")
    speed = bucket.get("avg_speed")
    cadence = bucket.get("avg_cadence")

    if _low(speed, 0.5) and (_low(power, 30) or _low(cadence, 5)):
        segment_type = "pause_or_coast"
    elif ftp and power is not None:
        ratio = float(power) / float(ftp)
        if ratio < 0.55:
            segment_type = "recovery"
        elif ratio < 0.75:
            segment_type = "steady_endurance"
        elif ratio < 0.90:
            segment_type = "tempo"
        elif ratio < 1.05:
            segment_type = "threshold"
        elif ratio < 1.20:
            segment_type = "vo2max_interval"
        else:
            segment_type = "sprint_or_anaerobic"
    elif power is not None:
        segment_type = "moderate_work" if power >= 100 else "easy_work"
    elif speed is not None:
        segment_type = "moving" if speed >= 1 else "pause_or_coast"
    else:
        segment_type = "unknown"

    return {**bucket, "type": segment_type}


def _merge_segments(buckets: list[dict[str, Any]], bucket_seconds: int) -> list[dict[str, Any]]:
    if not buckets:
        return []
    segments: list[dict[str, Any]] = []
    current_type = buckets[0]["type"]
    current: list[dict[str, Any]] = []
    for bucket in buckets:
        if bucket["type"] != current_type and current:
            segments.append(_segment_from_buckets(current_type, current, bucket_seconds))
            current = []
            current_type = bucket["type"]
        current.append(bucket)
    if current:
        segments.append(_segment_from_buckets(current_type, current, bucket_seconds))
    return segments


def _segment_from_buckets(
    segment_type: str,
    buckets: list[dict[str, Any]],
    bucket_seconds: int,
) -> dict[str, Any]:
    start_s = buckets[0]["start_s"]
    end_s = buckets[-1]["end_s"]
    return {
        "start_min": round(start_s / 60, 1),
        "end_min": round(end_s / 60, 1),
        "duration_seconds": round(max(0, end_s - start_s), 1),
        "type": segment_type,
        "avg_power": _mean([b.get("avg_power") for b in buckets]),
        "avg_heart_rate": _mean([b.get("avg_hr") for b in buckets]),
        "avg_cadence": _mean([b.get("avg_cadence") for b in buckets]),
        "avg_speed_mps": _mean([b.get("avg_speed") for b in buckets]),
        "bucket_count": len(buckets),
        "bucket_seconds": bucket_seconds,
    }


def _structure_label(segments: list[dict[str, Any]]) -> str:
    if not segments:
        return "未识别出训练结构"
    types = [segment["type"] for segment in segments]
    hard = {"threshold", "vo2max_interval", "sprint_or_anaerobic"}
    if sum(1 for item in types if item in hard) >= 2:
        return "包含明显高强度段"
    if "tempo" in types or "threshold" in types:
        return "有明显节奏或阈值段"
    if types.count("steady_endurance") >= 1:
        return "以稳定有氧为主"
    if types.count("pause_or_coast") >= max(2, len(types) // 3):
        return "滑行或暂停较多"
    return "非结构化训练"


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
        or session_zone.get("functional_threshold_power")
    }


def _avg(group: pd.DataFrame, field: str) -> float | None:
    if field not in group.columns:
        return None
    series = pd.to_numeric(group[field], errors="coerce").dropna()
    if series.empty:
        return None
    return round(float(series.mean()), 1)


def _avg_any(group: pd.DataFrame, fields: list[str]) -> float | None:
    for field in fields:
        value = _avg(group, field)
        if value is not None:
            return value
    return None


def _mean(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 1)


def _low(value: Any, threshold: float) -> bool:
    return value is not None and float(value) < threshold


def _normalize_bucket_seconds(value: int) -> int:
    if value not in {10, 30, 60}:
        raise ValueError("bucket_seconds 只支持 10、30、60")
    return value
