"""运动员档案管理与区间计算.

从 data/athlete.json 加载 FTP/最大心率/静息心率等个人数据,
在 FIT 文件缺少区间设定时作为 fallback,并基于 Coggan 功率区间
和 5 区心率模型自行计算区间边界.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_ATHLETE_PATH = Path("data") / "athlete.json"


def load_athlete_profile(path: str | Path = DEFAULT_ATHLETE_PATH) -> dict[str, Any]:
    """加载运动员档案,文件不存在返回空 dict."""
    target = Path(path)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_athlete_profile(profile: dict[str, Any], path: str | Path = DEFAULT_ATHLETE_PATH) -> Path:
    """保存运动员档案."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def get_ftp(profile: dict[str, Any]) -> float | None:
    """从档案中提取 FTP(瓦)."""
    value = profile.get("ftp")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_max_hr(profile: dict[str, Any]) -> float | None:
    """从档案中提取最大心率(bpm)."""
    value = profile.get("max_heart_rate")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_resting_hr(profile: dict[str, Any]) -> float | None:
    """从档案中提取静息心率(bpm)."""
    value = profile.get("resting_heart_rate")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_threshold_hr(profile: dict[str, Any]) -> float | None:
    """从档案中提取阈值心率(bpm)."""
    value = profile.get("threshold_heart_rate")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- 功率区间 (Coggan 7 区) ---------------------------------------------------

def power_zone_boundaries(ftp: float) -> list[float]:
    """返回 Coggan 功率区间上界列表(瓦).

    区间定义(占 FTP 百分比):
      Z1 恢复     < 55%
      Z2 耐力   55-75%
      Z3 节奏   75-90%
      Z4 阈值   90-105%
      Z5 VO2Max 105-120%
      Z6 无氧   120-150%
      Z7 冲刺      > 150%

    返回 6 个上界: [0.55*ftp, 0.75*ftp, 0.90*ftp, 1.05*ftp, 1.20*ftp, 1.50*ftp]
    """
    ftp = float(ftp)
    return [round(ftp * pct, 1) for pct in (0.55, 0.75, 0.90, 1.05, 1.20, 1.50)]


# -- 心率区间 (5 区模型,基于最大心率百分比) ------------------------------------

def hr_zone_boundaries(max_hr: float, *, resting_hr: float | None = None) -> list[float]:
    """返回心率区间上界列表(bpm).

    采用储备心率(HRR)百分比模型,若缺静息心率则退化为最大心率百分比:
      Z1 恢复  < 60% (HRR) / < 60% MHR
      Z2 耐力  60-70%
      Z3 节奏  70-80%
      Z4 阈值  80-90%
      Z5 最大  90-100%

    返回 4 个上界.
    """
    max_hr_f = float(max_hr)
    if resting_hr is not None:
        reserve = max_hr_f - float(resting_hr)
        return [round(float(resting_hr) + reserve * pct, 1) for pct in (0.60, 0.70, 0.80, 0.90)]
    return [round(max_hr_f * pct, 1) for pct in (0.60, 0.70, 0.80, 0.90)]


# -- 从 FIT training_metadata 中提取已有值 ------------------------------------

def _has_ftp(metadata: dict[str, Any]) -> bool:
    zones = metadata.get("zones_target") or {}
    return zones.get("functional_threshold_power") is not None


def _has_max_hr(metadata: dict[str, Any]) -> bool:
    zones = metadata.get("zones_target") or {}
    user_profile = metadata.get("user_profile") or {}
    return (
        zones.get("max_heart_rate") is not None
        or user_profile.get("default_max_biking_heart_rate") is not None
        or user_profile.get("default_max_heart_rate") is not None
    )


def _has_hr_zones(metadata: dict[str, Any]) -> bool:
    """检查 time_in_zone 中是否已有心率区间边界."""
    tiz = metadata.get("time_in_zone") or []
    for entry in tiz:
        if entry.get("hr_zone_high_boundary") is not None:
            return True
    return False


def _has_power_zones(metadata: dict[str, Any]) -> bool:
    """检查 time_in_zone 中是否已有功率区间边界."""
    tiz = metadata.get("time_in_zone") or []
    for entry in tiz:
        if entry.get("power_zone_high_boundary") is not None:
            return True
    return False


# -- 主入口:用运动员档案补全 training_metadata ---------------------------------

def enrich_training_metadata(
    metadata: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """用运动员档案补全 FIT training_metadata 中缺失的 FTP/心率/区间设定.

    Args:
        metadata: FIT summarize_training_metadata() 的返回值.
        profile: load_athlete_profile() 的返回值,传 None 则自动加载.

    Returns:
        dict: 补全后的 metadata 副本.
    """
    if profile is None:
        profile = load_athlete_profile()
    if not profile:
        return metadata

    enriched = _deep_copy_metadata(metadata)
    ftp = get_ftp(profile)
    max_hr = get_max_hr(profile)
    resting_hr = get_resting_hr(profile)
    threshold_hr = get_threshold_hr(profile)

    # 补 zones_target
    zones = enriched.setdefault("zones_target", {})
    if not _has_ftp(enriched) and ftp is not None:
        zones["functional_threshold_power"] = ftp
        zones["pwr_calc_type"] = "athlete_profile"
    if not _has_max_hr(enriched) and max_hr is not None:
        zones["max_heart_rate"] = max_hr
        zones["hr_calc_type"] = "athlete_profile"
    if zones.get("threshold_heart_rate") is None and threshold_hr is not None:
        zones["threshold_heart_rate"] = threshold_hr

    # 补 time_in_zone 区间边界
    tiz = enriched.setdefault("time_in_zone", [])
    if not _has_power_zones(enriched) and ftp is not None:
        boundaries = power_zone_boundaries(ftp)
        tiz.append({
            "reference_mesg": "athlete_profile",
            "reference_index": 0,
            "functional_threshold_power": ftp,
            "pwr_calc_type": "coggan_7_zone",
            "power_zone_high_boundary": boundaries,
        })
    if not _has_hr_zones(enriched) and max_hr is not None:
        boundaries = hr_zone_boundaries(max_hr, resting_hr=resting_hr)
        tiz.append({
            "reference_mesg": "athlete_profile",
            "reference_index": 0,
            "max_heart_rate": max_hr,
            "resting_heart_rate": resting_hr,
            "hr_calc_type": "heart_rate_reserve" if resting_hr is not None else "max_hr_percent",
            "hr_zone_high_boundary": boundaries,
        })

    # 补 user_profile 基础字段
    profile_fields = {
        "resting_heart_rate": resting_hr,
        "weight": profile.get("weight"),
        "height": profile.get("height"),
    }
    user_profile = enriched.setdefault("user_profile", {})
    for key, value in profile_fields.items():
        if value is not None and user_profile.get(key) is None:
            user_profile[key] = value

    return enriched


def _deep_copy_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """浅拷贝足够,因为 metadata 值都是基础类型或 list[dict]."""
    import copy
    return copy.deepcopy(metadata)
