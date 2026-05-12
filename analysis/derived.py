from __future__ import annotations

from typing import Any

import pandas as pd


def derived_metrics(summary: dict[str, Any], sample_statistics: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    distance_m = summary.get("distance_m")
    duration_s = summary.get("duration_s")
    derived: dict[str, Any] = {}
    if distance_m and duration_s:
        derived["distance_km"] = round(distance_m / 1000, 2)
        derived["duration_min"] = round(duration_s / 60, 1)
        derived["avg_speed_kmh"] = round(distance_m / duration_s * 3.6, 2)

    power = sample_statistics.get("power_w")
    if power and duration_s:
        derived["work_kj_estimate"] = round(power["avg"] * duration_s / 1000, 1)

    if not df.empty and "heart_rate" in df.columns and "elapsed_s" in df.columns:
        derived["hr_drift_simple"] = simple_hr_drift(df)
    return derived


def simple_hr_drift(df: pd.DataFrame) -> dict[str, Any] | None:
    heart_rate = pd.to_numeric(df["heart_rate"], errors="coerce")
    valid = df[heart_rate.notna()].copy()
    if len(valid) < 20:
        return None
    midpoint = valid["elapsed_s"].median()
    first = valid[valid["elapsed_s"] <= midpoint]["heart_rate"].mean()
    second = valid[valid["elapsed_s"] > midpoint]["heart_rate"].mean()
    if pd.isna(first) or pd.isna(second):
        return None
    return {
        "first_half_avg_hr": round(float(first), 1),
        "second_half_avg_hr": round(float(second), 1),
        "delta_bpm": round(float(second - first), 1),
    }
