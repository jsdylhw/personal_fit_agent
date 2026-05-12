from __future__ import annotations

from typing import Any

import pandas as pd


def sample_statistics(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "heart_rate_bpm": series_stats(df, "heart_rate"),
        "power_w": series_stats(df, "power"),
        "cadence_rpm": series_stats(df, "cadence"),
        "speed_mps": series_stats_any(df, ["enhanced_speed", "speed"]),
        "altitude_m": series_stats_any(df, ["enhanced_altitude", "altitude"]),
        "temperature_c": series_stats(df, "temperature"),
        "distance_m": series_stats(df, "distance"),
    }


def series_stats_any(df: pd.DataFrame, fields: list[str]) -> dict[str, Any] | None:
    for field in fields:
        stats = series_stats(df, field)
        if stats:
            stats["source_field"] = field
            return stats
    return None


def series_stats(df: pd.DataFrame, field: str) -> dict[str, Any] | None:
    if df.empty or field not in df.columns:
        return None
    series = pd.to_numeric(df[field], errors="coerce").dropna()
    if series.empty:
        return None

    zero_count = int((series == 0).sum())
    nonzero = series[series != 0]
    return {
        "field": field,
        "count": int(series.count()),
        "missing_count": int(len(df) - series.count()),
        "zero_count": zero_count,
        "min": float(series.min()),
        "max": float(series.max()),
        "avg": float(series.mean()),
        "median": float(series.median()),
        "std": float(series.std()) if series.count() > 1 else 0.0,
        "p05": float(series.quantile(0.05)),
        "p25": float(series.quantile(0.25)),
        "p75": float(series.quantile(0.75)),
        "p95": float(series.quantile(0.95)),
        "nonzero_avg": float(nonzero.mean()) if not nonzero.empty else None,
    }
