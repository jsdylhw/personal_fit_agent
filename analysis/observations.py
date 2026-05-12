from __future__ import annotations

from typing import Any


def build_observations(metrics: dict[str, Any]) -> list[str]:
    observations: list[str] = []
    summary = metrics["summary"]
    derived = metrics["derived"]
    samples = metrics["sample_statistics"]

    if derived.get("distance_km"):
        observations.append(
            f"本次活动距离约 {derived['distance_km']} km，时长约 {derived.get('duration_min')} 分钟。"
        )
    if samples.get("heart_rate_bpm"):
        hr = samples["heart_rate_bpm"]
        observations.append(f"平均心率约 {hr['avg']:.0f} bpm，最高心率约 {hr['max']:.0f} bpm。")
    if samples.get("power_w"):
        power = samples["power_w"]
        observations.append(f"平均功率约 {power['avg']:.0f} W，最高功率约 {power['max']:.0f} W。")
    drift = derived.get("hr_drift_simple")
    if drift:
        direction = "高" if drift["delta_bpm"] >= 0 else "低"
        observations.append(
            f"后半程平均心率比前半程{direction} {abs(drift['delta_bpm'])} bpm，可作为疲劳或强度变化线索。"
        )
    if summary.get("record_count"):
        observations.append(f"FIT 中包含 {summary['record_count']} 条时序记录。")
    return observations
