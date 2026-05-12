from __future__ import annotations

from typing import Any

import pandas as pd

from .utils import num


def activity_metrics(summary: dict[str, Any], parsed: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    session = parsed.get("sessions", [{}])[-1] if parsed.get("sessions") else {}
    distance_m = summary.get("distance_m")
    duration_s = summary.get("duration_s")

    metrics: dict[str, Any] = {
        "sport_type": summary.get("sport_type"),
        "sub_sport": summary.get("sub_sport"),
        "start_time": summary.get("start_time"),
        "elapsed_seconds": num(session.get("total_elapsed_time")),
        "moving_seconds": estimate_moving_seconds(df),
        "timer_seconds": duration_s,
        "distance_m": distance_m,
        "ascent_m": num(session.get("total_ascent")),
        "descent_m": num(session.get("total_descent")),
        "energy_kj": num(session.get("total_work")),
        "calories": num(session.get("total_calories")),
        "avg_power": num(session.get("avg_power")),
        "np_power": num(session.get("normalized_power")),
        "max_power": num(session.get("max_power")),
        "avg_hr": num(session.get("avg_heart_rate")),
        "max_hr": num(session.get("max_heart_rate")),
        "avg_speed_mps": num(session.get("enhanced_avg_speed")),
        "max_speed_mps": num(session.get("enhanced_max_speed")),
        "tss": num(session.get("training_stress_score")),
        "intensity_factor": num(session.get("intensity_factor")),
        "training_effect": num(session.get("total_training_effect")),
        "anaerobic_training_effect": num(session.get("total_anaerobic_training_effect")),
        "training_load_peak": num(session.get("training_load_peak")),
        "record_count": summary.get("record_count"),
        "lap_count": summary.get("lap_count"),
    }
    if distance_m and duration_s:
        metrics["distance_km"] = round(distance_m / 1000, 3)
        metrics["avg_speed_kmh_from_distance"] = round(distance_m / duration_s * 3.6, 3)
    return metrics


def estimate_moving_seconds(df: pd.DataFrame) -> float | None:
    if df.empty or "elapsed_s" not in df.columns:
        return None
    speed_field = "enhanced_speed" if "enhanced_speed" in df.columns else "speed" if "speed" in df.columns else None
    if not speed_field:
        return None
    speed = pd.to_numeric(df[speed_field], errors="coerce")
    moving = df[speed.fillna(0) > 0.5]
    if moving.empty:
        return 0.0
    return float(len(moving))
