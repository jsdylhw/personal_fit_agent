from __future__ import annotations

from typing import Any

from .fatigue import analyze_fatigue_and_stability
from .intensity import analyze_intensity_distribution
from .summary import get_activity_summary


def generate_training_recommendation(
    analysis: dict[str, Any],
    goal: str = "general_review",
) -> dict[str, Any]:
    """Return recommendation context for the LLM, not final coaching prose."""
    summary = get_activity_summary(analysis)
    intensity = analyze_intensity_distribution(analysis)
    fatigue = analyze_fatigue_and_stability(analysis)

    tss = summary.get("tss")
    intensity_factor = summary.get("intensity_factor")
    fatigue_inputs = fatigue.get("interpretation_inputs", {}) if fatigue.get("available") else {}
    fatigue_metrics = fatigue.get("metrics", {}) if fatigue.get("available") else {}
    fatigue_caveats = fatigue.get("caveats", []) if fatigue.get("available") else []
    stimulus = intensity.get("main_stimulus")

    return {
        "schema_version": "training_recommendation_context.v1",
        "goal": goal,
        "purpose": "给大模型生成训练建议的结构化上下文；这里不直接输出最终建议文本。",
        "evidence": {
            "summary_label": summary.get("summary_label"),
            "main_stimulus": stimulus,
            "intensity_label": intensity.get("intensity_label"),
            "fatigue_metrics": fatigue_metrics,
            "fatigue_interpretation_inputs": fatigue_inputs,
            "fatigue_caveats": fatigue_caveats,
            "tss": tss,
            "intensity_factor": intensity_factor,
            "duration_min": summary.get("duration_min"),
            "distance_km": summary.get("distance_km"),
            "average_power": summary.get("average_power"),
            "normalized_power": summary.get("normalized_power"),
            "average_heart_rate": summary.get("average_heart_rate"),
            "variability_index": summary.get("variability_index"),
        },
        "readiness_signals": _readiness_signals(tss, intensity_factor, fatigue_inputs),
        "training_focus_candidates": _training_focus_candidates(goal, stimulus, tss, intensity_factor),
        "avoid_or_be_careful_with": _avoid_or_be_careful_with(intensity_factor, fatigue_inputs),
        "recovery_context": _recovery_context(fatigue_inputs),
        "llm_instruction": (
            "请基于 evidence、readiness_signals、training_focus_candidates 和用户问题生成中文训练建议。"
            "不要照抄工具字段；需要给出明天、本周、长期建议，并说明建议依据。"
        ),
    }


def _readiness_signals(
    tss: float | None,
    intensity_factor: float | None,
    fatigue_inputs: dict[str, Any],
) -> dict[str, Any]:
    signals: list[str] = []
    if tss is not None:
        if tss < 30:
            signals.append("low_training_load")
        elif tss < 80:
            signals.append("moderate_training_load")
        else:
            signals.append("high_training_load")
    if intensity_factor is not None:
        if intensity_factor < 0.75:
            signals.append("low_to_moderate_intensity")
        elif intensity_factor < 0.9:
            signals.append("moderately_high_intensity")
        else:
            signals.append("high_intensity")
    if fatigue_inputs.get("large_power_drop"):
        signals.append("large_power_drop")
    if fatigue_inputs.get("heart_rate_rise"):
        signals.append("heart_rate_rise")
    if fatigue_inputs.get("heart_rate_drop"):
        signals.append("heart_rate_drop")
    if fatigue_inputs.get("decoupling_over_10_percent"):
        signals.append("high_decoupling")
    elif fatigue_inputs.get("decoupling_over_5_percent"):
        signals.append("moderate_decoupling")
    return {
        "signals": signals,
        "recovery_priority": "high_intensity" in signals or "high_decoupling" in signals,
        "load_level": _load_level(tss),
        "intensity_level": _intensity_level(intensity_factor),
    }


def _training_focus_candidates(
    goal: str,
    stimulus: str | None,
    tss: float | None,
    intensity_factor: float | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if goal in {"base_endurance", "general_review", "fat_loss"}:
        candidates.append(
            {
                "focus": "base_endurance",
                "priority": "high",
                "reason": "适合用稳定低中强度时长建立有氧基础。",
            }
        )
    if goal == "ftp_improvement" or (stimulus and "节奏" in stimulus):
        candidates.append(
            {
                "focus": "tempo_or_sweet_spot",
                "priority": "medium",
                "reason": "本次已有节奏/阈值刺激，可由大模型根据疲劳情况决定是否安排下一次质量课。",
            }
        )
    if goal == "vo2max":
        candidates.append(
            {
                "focus": "vo2max_intervals",
                "priority": "conditional",
                "reason": "只有在恢复充分且近期高强度不多时才适合安排。",
            }
        )
    if intensity_factor is not None and intensity_factor >= 0.85:
        candidates.append(
            {
                "focus": "recovery",
                "priority": "high",
                "reason": "本次强度较高，下一次训练应优先考虑恢复。",
            }
        )
    if intensity_factor is not None and intensity_factor < 0.75 and (tss is None or tss < 50):
        candidates.append(
            {
                "focus": "extend_duration",
                "priority": "medium",
                "reason": "本次负荷较低，可考虑逐步增加单次训练时长。",
            }
        )
    return candidates


def _avoid_or_be_careful_with(
    intensity_factor: float | None,
    fatigue_inputs: dict[str, Any],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if intensity_factor is not None and intensity_factor >= 0.85:
        items.append(
            {
                "item": "back_to_back_high_intensity",
                "reason": "连续高强度会增加疲劳积累风险。",
            }
        )
    if fatigue_inputs.get("decoupling_over_10_percent") or (
        fatigue_inputs.get("large_power_drop") and fatigue_inputs.get("heart_rate_rise")
    ):
        items.append(
            {
                "item": "hard_intervals",
                "reason": "疲劳相关指标存在风险信号，是否安排高强度需要由大模型结合用户状态判断。",
            }
        )
    return items


def _recovery_context(fatigue_inputs: dict[str, Any]) -> dict[str, Any]:
    if fatigue_inputs.get("decoupling_over_10_percent") or fatigue_inputs.get("heart_rate_rise"):
        level = "high"
    elif fatigue_inputs.get("large_power_drop") or fatigue_inputs.get("large_cadence_drop"):
        level = "medium"
    else:
        level = "normal"
    return {
        "recovery_need": level,
        "include_mobility_or_stretching": True,
        "include_cross_training": True,
        "notes": [
            "拉伸、交叉训练、力量训练的具体内容由大模型结合用户目标生成。",
            "后端只提供恢复需求等级和限制条件。",
        ],
    }


def _load_level(tss: float | None) -> str:
    if tss is None:
        return "unknown"
    if tss < 30:
        return "low"
    if tss < 80:
        return "moderate"
    return "high"


def _intensity_level(intensity_factor: float | None) -> str:
    if intensity_factor is None:
        return "unknown"
    if intensity_factor < 0.55:
        return "low"
    if intensity_factor < 0.75:
        return "low_to_moderate"
    if intensity_factor < 0.9:
        return "moderately_high"
    return "high"
