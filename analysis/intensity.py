from __future__ import annotations

from typing import Any

import pandas as pd


def analyze_intensity_distribution(analysis: dict[str, Any]) -> dict[str, Any]:
    records = analysis.get("records") or []
    df = pd.DataFrame(records)
    thresholds = _thresholds(analysis)
    ftp = thresholds.get("functional_threshold_power")
    max_hr = thresholds.get("max_heart_rate")
    resting_hr = thresholds.get("resting_heart_rate")

    power_zones = _power_zones(df, ftp)
    hr_zones = _heart_rate_zones(df, max_hr=max_hr, resting_hr=resting_hr)
    main_stimulus = _main_stimulus(power_zones, hr_zones)

    warnings: list[str] = []
    if ftp is None and "power" in df.columns:
        warnings.append("缺少 FTP，功率区间无法按个人阈值计算。")
    if max_hr is None and "heart_rate" in df.columns:
        warnings.append("缺少最大心率，心率区间无法按个人阈值计算。")

    return {
        "schema_version": "intensity_distribution.v1",
        "thresholds": thresholds,
        "power_zones": power_zones,
        "heart_rate_zones": hr_zones,
        "main_stimulus": main_stimulus,
        "intensity_label": _intensity_label(analysis, power_zones, hr_zones),
        "warnings": warnings,
    }


def _power_zones(df: pd.DataFrame, ftp: float | None) -> dict[str, Any]:
    if df.empty or "power" not in df.columns:
        return {"available": False, "reason": "no power data"}
    power = pd.to_numeric(df["power"], errors="coerce").dropna()
    if power.empty:
        return {"available": False, "reason": "no valid power data"}
    if not ftp:
        return {"available": False, "reason": "missing ftp", "sample_count": int(power.count())}

    zones = {
        "Z1_recovery": power < ftp * 0.55,
        "Z2_endurance": (power >= ftp * 0.55) & (power < ftp * 0.75),
        "Z3_tempo": (power >= ftp * 0.75) & (power < ftp * 0.90),
        "Z4_threshold": (power >= ftp * 0.90) & (power < ftp * 1.05),
        "Z5_vo2max": (power >= ftp * 1.05) & (power < ftp * 1.20),
        "Z6_anaerobic": (power >= ftp * 1.20) & (power < ftp * 1.50),
        "Z7_sprint": power >= ftp * 1.50,
    }
    total = float(power.count())
    return {
        "available": True,
        "ftp": ftp,
        "sample_count": int(total),
        "fractions": {name: round(float(mask.sum()) / total, 3) for name, mask in zones.items()},
        "seconds_estimate": {name: int(mask.sum()) for name, mask in zones.items()},
    }


def _heart_rate_zones(
    df: pd.DataFrame,
    *,
    max_hr: float | None,
    resting_hr: float | None,
) -> dict[str, Any]:
    if df.empty or "heart_rate" not in df.columns:
        return {"available": False, "reason": "no heart rate data"}
    hr = pd.to_numeric(df["heart_rate"], errors="coerce").dropna()
    if hr.empty:
        return {"available": False, "reason": "no valid heart rate data"}
    if not max_hr:
        return {"available": False, "reason": "missing max heart rate", "sample_count": int(hr.count())}

    if resting_hr is not None and max_hr > resting_hr:
        reserve = max_hr - resting_hr
        intensity = (hr - resting_hr) / reserve
        method = "heart_rate_reserve"
    else:
        intensity = hr / max_hr
        method = "max_heart_rate_percent"

    zones = {
        "Z1_easy": intensity < 0.60,
        "Z2_endurance": (intensity >= 0.60) & (intensity < 0.70),
        "Z3_tempo": (intensity >= 0.70) & (intensity < 0.80),
        "Z4_threshold": (intensity >= 0.80) & (intensity < 0.90),
        "Z5_high": intensity >= 0.90,
    }
    total = float(hr.count())
    return {
        "available": True,
        "method": method,
        "max_heart_rate": max_hr,
        "resting_heart_rate": resting_hr,
        "sample_count": int(total),
        "fractions": {name: round(float(mask.sum()) / total, 3) for name, mask in zones.items()},
        "seconds_estimate": {name: int(mask.sum()) for name, mask in zones.items()},
    }


def _main_stimulus(power_zones: dict[str, Any], hr_zones: dict[str, Any]) -> str:
    if power_zones.get("available"):
        fractions = power_zones.get("fractions", {})
        low = fractions.get("Z1_recovery", 0) + fractions.get("Z2_endurance", 0)
        tempo = fractions.get("Z3_tempo", 0) + fractions.get("Z4_threshold", 0)
        high = (
            fractions.get("Z5_vo2max", 0)
            + fractions.get("Z6_anaerobic", 0)
            + fractions.get("Z7_sprint", 0)
        )
        if high >= 0.12:
            return "高强度间歇或冲刺能力刺激"
        if tempo >= 0.30:
            return "节奏耐力或阈值耐力"
        if low >= 0.65:
            return "有氧基础或恢复"
    if hr_zones.get("available"):
        fractions = hr_zones.get("fractions", {})
        if fractions.get("Z4_threshold", 0) + fractions.get("Z5_high", 0) >= 0.25:
            return "心肺高强度刺激"
        if fractions.get("Z2_endurance", 0) + fractions.get("Z3_tempo", 0) >= 0.60:
            return "有氧耐力"
    return "强度结构不明确"


def _intensity_label(
    analysis: dict[str, Any],
    power_zones: dict[str, Any],
    hr_zones: dict[str, Any],
) -> str:
    activity = analysis.get("activity_metrics", {})
    intensity_factor = activity.get("intensity_factor")
    if intensity_factor is not None:
        if intensity_factor < 0.55:
            return "低强度"
        if intensity_factor < 0.75:
            return "中低强度"
        if intensity_factor < 0.90:
            return "中高强度"
        return "高强度"
    stimulus = _main_stimulus(power_zones, hr_zones)
    if "高强度" in stimulus:
        return "高强度"
    if "节奏" in stimulus or "阈值" in stimulus:
        return "中高强度"
    if "有氧" in stimulus:
        return "中低强度"
    return "未知"


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
