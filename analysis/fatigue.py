from __future__ import annotations

from typing import Any

import pandas as pd


def analyze_fatigue_and_stability(analysis: dict[str, Any]) -> dict[str, Any]:
    records = analysis.get("records") or []
    df = pd.DataFrame(records)
    if df.empty or "elapsed_s" not in df.columns:
        return {
            "schema_version": "fatigue_stability.v1",
            "available": False,
            "reason": "no record time series available",
        }

    halves = _split_halves(df)
    first = halves["first"]
    second = halves["second"]
    first_power = _avg(first, "power")
    second_power = _avg(second, "power")
    first_hr = _avg(first, "heart_rate")
    second_hr = _avg(second, "heart_rate")
    first_cadence = _avg(first, "cadence")
    second_cadence = _avg(second, "cadence")
    first_speed = _avg_any(first, ["enhanced_speed", "speed"])
    second_speed = _avg_any(second, ["enhanced_speed", "speed"])

    power_fade = _percent_change(first_power, second_power)
    speed_fade = _percent_change(first_speed, second_speed)
    cadence_drop = _delta(first_cadence, second_cadence)
    hr_drift = _delta(first_hr, second_hr)
    decoupling = _decoupling(first_power, second_power, first_hr, second_hr)
    vi = _variability_index(analysis)

    return {
        "schema_version": "fatigue_stability_metrics.v1",
        "purpose": "返回前后半程、漂移、解耦和稳定性指标；不直接判断是否疲劳。",
        "available": True,
        "split_method": "elapsed_time_halves",
        "comparison": {
            "first_half": {
                "avg_power": first_power,
                "avg_heart_rate": first_hr,
                "avg_cadence": first_cadence,
                "avg_speed_mps": first_speed,
            },
            "second_half": {
                "avg_power": second_power,
                "avg_heart_rate": second_hr,
                "avg_cadence": second_cadence,
                "avg_speed_mps": second_speed,
            },
        },
        "metrics": {
            "power_change_percent": power_fade,
            "speed_change_percent": speed_fade,
            "heart_rate_change_bpm": hr_drift,
            "cadence_change_rpm": cadence_drop,
            "hr_power_decoupling_percent": decoupling,
            "variability_index": vi,
        },
        "interpretation_inputs": _interpretation_inputs(power_fade, speed_fade, cadence_drop, hr_drift, decoupling, vi),
        "caveats": _caveats(power_fade, hr_drift, decoupling),
        "llm_instruction": (
            "请基于 comparison、metrics、interpretation_inputs 和 caveats 自行判断稳定性或疲劳。"
            "不要只因功率下降就判定疲劳；需要结合心率、踏频、速度、路况或主动降强度可能性。"
        ),
    }


def _split_halves(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    work = df.copy()
    work["elapsed_s"] = pd.to_numeric(work["elapsed_s"], errors="coerce")
    work = work.dropna(subset=["elapsed_s"])
    midpoint = work["elapsed_s"].median()
    return {
        "first": work[work["elapsed_s"] <= midpoint],
        "second": work[work["elapsed_s"] > midpoint],
    }


def _decoupling(
    first_power: float | None,
    second_power: float | None,
    first_hr: float | None,
    second_hr: float | None,
) -> float | None:
    if not all([first_power, second_power, first_hr, second_hr]):
        return None
    first_ratio = float(first_hr) / float(first_power)
    second_ratio = float(second_hr) / float(second_power)
    if first_ratio == 0:
        return None
    return round((second_ratio / first_ratio - 1) * 100, 1)


def _variability_index(analysis: dict[str, Any]) -> float | None:
    metrics = analysis.get("activity_metrics", {})
    avg_power = metrics.get("avg_power")
    np_power = metrics.get("np_power")
    if not avg_power or not np_power:
        return None
    return round(float(np_power) / float(avg_power), 3)


def _interpretation_inputs(
    power_change: float | None,
    speed_change: float | None,
    cadence_change: float | None,
    hr_change: float | None,
    decoupling: float | None,
    vi: float | None,
) -> dict[str, Any]:
    return {
        "large_power_drop": power_change is not None and power_change <= -20,
        "large_speed_drop": speed_change is not None and speed_change <= -20,
        "large_cadence_drop": cadence_change is not None and cadence_change <= -10,
        "heart_rate_rise": hr_change is not None and hr_change >= 5,
        "heart_rate_drop": hr_change is not None and hr_change <= -5,
        "decoupling_over_5_percent": decoupling is not None and decoupling > 5,
        "decoupling_over_10_percent": decoupling is not None and decoupling > 10,
        "high_variability_index": vi is not None and vi >= 1.20,
    }


def _caveats(
    power_change: float | None,
    hr_change: float | None,
    decoupling: float | None,
) -> list[str]:
    caveats: list[str] = []
    if power_change is not None and abs(power_change) > 20:
        caveats.append("前后半程功率差异很大，hr_power_decoupling_percent 可能混入主动降强度、滑行、停车或路况变化影响。")
    if power_change is not None and power_change < -20 and hr_change is not None and hr_change <= 0:
        caveats.append("功率下降且心率下降，更像强度切换，不宜直接解释为生理疲劳。")
    if decoupling is None:
        caveats.append("缺少足够的功率或心率数据，无法计算心率-功率解耦。")
    return caveats


def _avg(df: pd.DataFrame, field: str) -> float | None:
    if df.empty or field not in df.columns:
        return None
    series = pd.to_numeric(df[field], errors="coerce").dropna()
    if series.empty:
        return None
    return round(float(series.mean()), 1)


def _avg_any(df: pd.DataFrame, fields: list[str]) -> float | None:
    for field in fields:
        value = _avg(df, field)
        if value is not None:
            return value
    return None


def _percent_change(first: float | None, second: float | None) -> float | None:
    if not first or second is None:
        return None
    return round((float(second) - float(first)) / float(first) * 100, 1)


def _delta(first: float | None, second: float | None) -> float | None:
    if first is None or second is None:
        return None
    return round(float(second) - float(first), 1)
