from __future__ import annotations

from typing import Any

from .utils import num, serialize


def lap_summaries(laps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for index, lap in enumerate(laps, start=1):
        summaries.append(
            {
                "lap_index": index,
                "start_time": serialize(lap.get("start_time")),
                "elapsed_seconds": num(lap.get("total_elapsed_time")),
                "timer_seconds": num(lap.get("total_timer_time")),
                "distance_m": num(lap.get("total_distance")),
                "ascent_m": num(lap.get("total_ascent")),
                "descent_m": num(lap.get("total_descent")),
                "avg_power": num(lap.get("avg_power")),
                "np_power": num(lap.get("normalized_power")),
                "max_power": num(lap.get("max_power")),
                "avg_hr": num(lap.get("avg_heart_rate")),
                "max_hr": num(lap.get("max_heart_rate")),
                "avg_speed_mps": num(lap.get("enhanced_avg_speed")),
                "max_speed_mps": num(lap.get("enhanced_max_speed")),
                "avg_cadence": num(lap.get("avg_cadence")),
                "max_cadence": num(lap.get("max_cadence")),
                "calories": num(lap.get("total_calories")),
            }
        )
    return summaries
