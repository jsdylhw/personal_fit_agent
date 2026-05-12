from __future__ import annotations

from typing import Any

import pandas as pd


def data_quality(summary: dict[str, Any], sample_statistics: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    record_count = int(summary.get("record_count") or 0)
    zero_power = sample_statistics.get("power_w", {}).get("zero_count") if sample_statistics.get("power_w") else None
    zero_speed = sample_statistics.get("speed_mps", {}).get("zero_count") if sample_statistics.get("speed_mps") else None
    flags = []
    if summary.get("duration_s") and summary.get("duration_s") >= 12 * 3600:
        flags.append("very_long_duration")
    if summary.get("distance_m") == 0:
        flags.append("zero_distance")
    if zero_power is not None and record_count and zero_power / record_count > 0.95:
        flags.append("mostly_zero_power")
    if zero_speed is not None and record_count and zero_speed / record_count > 0.95:
        flags.append("mostly_zero_speed")
    return {
        "record_count": record_count,
        "available_columns": sorted(map(str, df.columns.tolist())) if not df.empty else [],
        "flags": flags,
    }
