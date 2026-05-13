from __future__ import annotations

from typing import Any

import pandas as pd


def data_quality_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    df = pd.DataFrame(analysis.get("records") or [])
    return data_quality(
        analysis.get("summary", {}),
        analysis.get("sample_statistics", {}),
        df,
    )


def data_quality(summary: dict[str, Any], sample_statistics: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    record_count = int(summary.get("record_count") or 0)
    power_stats = sample_statistics.get("power_w")
    hr_stats = sample_statistics.get("heart_rate_bpm")
    speed_stats = sample_statistics.get("speed_mps")
    cadence_stats = sample_statistics.get("cadence_rpm")
    altitude_stats = sample_statistics.get("altitude_m")
    zero_power = power_stats.get("zero_count") if power_stats else None
    zero_speed = speed_stats.get("zero_count") if speed_stats else None
    flags = []
    issues = []
    if summary.get("duration_s") and summary.get("duration_s") >= 12 * 3600:
        flags.append("very_long_duration")
        issues.append(_issue("very_long_duration", "medium", "活动时长异常长，建议确认是否包含非训练时间。"))
    if summary.get("distance_m") == 0:
        flags.append("zero_distance")
        issues.append(_issue("zero_distance", "high", "距离为 0，无法进行路线、配速或速度分析。"))
    if zero_power is not None and record_count and zero_power / record_count > 0.95:
        flags.append("mostly_zero_power")
        issues.append(_issue("mostly_zero_power", "high", "功率几乎全为 0，不建议进行功率分析。"))
    if zero_speed is not None and record_count and zero_speed / record_count > 0.95:
        flags.append("mostly_zero_speed")
        issues.append(_issue("mostly_zero_speed", "high", "速度几乎全为 0，不建议进行速度或配速分析。"))

    if power_stats and power_stats.get("max") and power_stats["max"] > 2000:
        flags.append("power_spike")
        issues.append(_issue("power_spike", "medium", "检测到异常高功率尖峰，分析时需要弱化尖峰影响。"))
    if hr_stats and hr_stats.get("max") and hr_stats["max"] > 230:
        flags.append("heart_rate_spike")
        issues.append(_issue("heart_rate_spike", "medium", "检测到异常高心率值，建议确认心率设备数据。"))

    sampling = _sampling_quality(df)
    if sampling.get("issue"):
        flags.append(sampling["issue"])
        issues.append(_issue(sampling["issue"], "low", sampling["message"]))

    available_columns = sorted(map(str, df.columns.tolist())) if not df.empty else []
    usable_for = []
    not_recommended_for = []
    if power_stats and "mostly_zero_power" not in flags:
        usable_for.append("power_analysis")
    else:
        not_recommended_for.append("power_analysis")
    if hr_stats:
        usable_for.append("heart_rate_analysis")
    else:
        not_recommended_for.append("heart_rate_analysis")
    if speed_stats:
        usable_for.append("speed_or_pace_analysis")
    if "position_lat" in available_columns or "lat" in available_columns or "latlng" in available_columns:
        usable_for.append("gps_route_analysis")
    else:
        not_recommended_for.append("gps_route_analysis")
    if altitude_stats:
        usable_for.append("elevation_analysis")
    if cadence_stats:
        usable_for.append("cadence_analysis")

    quality_score = _quality_score(record_count, flags, power_stats, hr_stats, speed_stats)
    return {
        "schema_version": "activity_data_quality.v1",
        "record_count": record_count,
        "quality_score": quality_score,
        "confidence": _confidence(quality_score),
        "has_power": bool(power_stats),
        "has_heart_rate": bool(hr_stats),
        "has_speed": bool(speed_stats),
        "has_cadence": bool(cadence_stats),
        "has_altitude": bool(altitude_stats),
        "has_gps": "position_lat" in available_columns or "lat" in available_columns or "latlng" in available_columns,
        "sampling": sampling,
        "available_columns": available_columns,
        "flags": flags,
        "issues": issues,
        "usable_for": usable_for,
        "not_recommended_for": not_recommended_for,
    }


def _issue(issue_type: str, severity: str, message: str) -> dict[str, str]:
    return {
        "type": issue_type,
        "severity": severity,
        "message": message,
    }


def _sampling_quality(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "elapsed_s" not in df.columns:
        return {"available": False}
    elapsed = pd.to_numeric(df["elapsed_s"], errors="coerce").dropna().sort_values()
    if elapsed.count() < 3:
        return {"available": False}
    deltas = elapsed.diff().dropna()
    median_delta = float(deltas.median())
    max_delta = float(deltas.max())
    result = {
        "available": True,
        "median_interval_seconds": round(median_delta, 2),
        "max_gap_seconds": round(max_delta, 2),
    }
    if max_delta >= 10:
        result["issue"] = "large_sampling_gap"
        result["message"] = f"最大采样间隔约 {max_delta:.0f} 秒，可能存在暂停或数据缺口。"
    return result


def _quality_score(
    record_count: int,
    flags: list[str],
    power_stats: dict[str, Any] | None,
    hr_stats: dict[str, Any] | None,
    speed_stats: dict[str, Any] | None,
) -> int:
    score = 100
    if record_count < 20:
        score -= 35
    if not power_stats:
        score -= 12
    if not hr_stats:
        score -= 12
    if not speed_stats:
        score -= 8
    for flag in flags:
        if flag in {"zero_distance", "mostly_zero_power", "mostly_zero_speed"}:
            score -= 25
        elif flag in {"power_spike", "heart_rate_spike"}:
            score -= 8
        else:
            score -= 5
    return max(0, min(100, score))


def _confidence(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"
