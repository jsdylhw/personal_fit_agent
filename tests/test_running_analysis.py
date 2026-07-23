"""Sport-aware running analysis data and prompt tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.prompts import build_fit_analysis_system_prompt
from agent.tools.fit_analysis.data import get_activity_summary_tool, get_distance_intervals_tool
from agent.tools.fit_analysis.scan import scan_activity_segments


def _running_parsed() -> dict:
    start = datetime(2026, 7, 20, 6, 30, tzinfo=timezone.utc)
    records = []
    distance = 0.0
    for second in range(180):
        # 40-119 秒是稳定的加速跑段，其余为轻松跑。
        speed = 4.2 if 40 <= second < 120 else 3.2
        distance += speed
        records.append({
            "timestamp": (start + timedelta(seconds=second)).isoformat(),
            "distance": distance,
            "enhanced_speed": speed,
            "heart_rate": 155 if 40 <= second < 120 else 140,
            # FIT record cadence is running stride cycles/min; user-facing spm is twice it.
            "cadence": 92 if 40 <= second < 120 else 86,
            "enhanced_altitude": 12.0 + second * 0.03,
            "vertical_oscillation": 82.0,
            "stance_time": 245.0,
            "step_length": 1.12,
        })
    return {
        "path": "run.fit",
        "summary": {
            "sport_type": "running",
            "sub_sport": "road",
            "start_time_local": "2026-07-20T14:30:00",
            "duration_s": 180.0,
            "distance_m": distance,
        },
        "records": records,
        "sessions": [{
            "sport": "running",
            "sub_sport": "road",
            "total_timer_time": 180.0,
            "total_elapsed_time": 180.0,
            "total_distance": distance,
            "enhanced_avg_speed": 3.64,
            "enhanced_max_speed": 4.2,
            "avg_heart_rate": 147,
            "max_heart_rate": 160,
            "avg_cadence": 88.5,
            "max_cadence": 93,
        }],
        "laps": [],
        "training_metadata": {"zones_target": {}, "user_profile": {}},
    }


def test_running_summary_exposes_pace_spm_and_present_dynamics():
    result = get_activity_summary_tool(
        _running_parsed(), sections=["pace", "cadence", "running_dynamics"],
    )

    assert result["pace"]["summary"]["avg_pace_s_per_km"] == 274.7
    assert result["cadence"]["summary"]["unit"] == "spm"
    assert result["cadence"]["summary"]["avg_cadence_spm"] == 177.0
    assert result["running_dynamics"]["available"] is True
    assert "stance_time" in result["running_dynamics"]["record_fields"]


def test_running_segment_scan_uses_pace_baseline_not_power():
    result = scan_activity_segments(_running_parsed(), window_seconds=30, step_seconds=10)

    assert result["baselines"]["scan_basis"] == "pace"
    assert result["baselines"].get("high_power_w") is None
    assert any(item["type"] == "fast_running_segment" for item in result["efforts"])


def test_running_distance_intervals_include_pace_and_spm():
    result = get_distance_intervals_tool(_running_parsed(), bucket_distance_m=100)

    assert "avg_pace_s_per_km" in result["series"]
    assert "avg_cadence_spm" in result["series"]


def test_running_prompt_includes_sport_specific_guidance():
    assert "Running analysis mode" in build_fit_analysis_system_prompt("running")
    assert "Running analysis mode" not in build_fit_analysis_system_prompt("cycling")
