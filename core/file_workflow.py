from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from agent.chat_logger import append_chat_log, new_session_id, readable_chat_log_path
from agent.llm import AnthropicMessagesClient, extract_text
from agent.prompts import LLM_FIT_ANALYSIS_SYSTEM_PROMPT
from fit.parser import parse_fit, records_dataframe

from .config import ensure_data_dirs
from .history import query_activity_history, upsert_activity_history


STRAVA_SUMMARY_TONES: list[dict[str, str]] = [
    {
        "name": "training_log",
        "description": "正常训练日志口吻：朴素、克制、像 Strava 日志，重点写本次训练刺激、节奏和身体反馈。",
        "weight": 2,
    },
    {
        "name": "professional_coach",
        "description": "专业教练口吻：直接给训练判断和下一步建议，语气理性，尽量少用玩笑。",
        "weight": 2,
    },
    {
        "name": "minimal_brief",
        "description": "简洁复盘口吻：短句、高信息密度，读起来干净利落，适合直接贴到 Strava。",
        "weight": 2,
    },
    {
        "name": "soft_catgirl",
        "description": "猫娘口吻：可爱、轻快、带一点鼓励，但保持训练判断清楚，不要每句都卖萌。",
        "weight": 10,
    },
]

def analyze_fit_file(
    fit_path: str | Path,
    *,
    use_history: bool = False,
    update_history: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    path = Path(fit_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".fit":
        raise ValueError(f"Only .fit files are supported: {path}")

    summary_path = _summary_path(path)
    previous_summary = _read_existing_summary(summary_path)
    if summary_path.exists() and not force:
        result = previous_summary
        if result.get("schema_version") == "llm_fit_file_analysis.v1":
            result["summary_path"] = str(summary_path)
            result.setdefault("report_path", str(_report_path(path)))
            if update_history:
                upsert_activity_history(result["history_entry"])
            result["status"] = "skipped_existing_summary"
            return result

    parsed = parse_fit(path)
    history_before = (
        query_activity_history(before=parsed["summary"].get("start_time"), days=90, limit=50)
        if use_history
        else None
    )
    model_result = analyze_with_llm(path, parsed, history_before=history_before)
    history_entry = normalize_history_entry(
        model_result.get("history_entry") or {},
        path=path,
        parsed=parsed,
    )

    result = {
        "schema_version": "llm_fit_file_analysis.v1",
        "status": "analyzed",
        "activity_key": _activity_key(path),
        "fit_path": str(path),
        "fit_summary": parsed["summary"],
        "model": model_result.get("model"),
        "session_id": model_result.get("session_id"),
        "log_path": model_result.get("log_path"),
        "readable_log_path": model_result.get("readable_log_path"),
        "strava_summary_tone": model_result.get("strava_summary_tone"),
        "markdown_report": model_result["markdown_report"],
        "strava_summary": model_result["strava_summary"],
        "history_entry": history_entry,
        "history_before": history_before,
    }
    _preserve_guided_analysis(result, previous_summary)

    report_path = write_brief_report(result)
    result["summary_path"] = str(summary_path)
    result["report_path"] = str(report_path)

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if update_history:
        upsert_activity_history(result["history_entry"])

    return result


def analyze_with_llm(
    path: Path,
    parsed: dict[str, Any],
    *,
    history_before: dict[str, Any] | None,
) -> dict[str, Any]:
    client = AnthropicMessagesClient()
    session_id = new_session_id("fit_analysis")
    strava_summary_tone = choose_strava_summary_tone()
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": json.dumps(
                build_initial_loop_payload(
                    path,
                    parsed,
                    history_before=history_before,
                    strava_summary_tone=strava_summary_tone,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        }
    ]
    turns: list[dict[str, Any]] = []
    data: dict[str, Any] | None = None
    last_response: dict[str, Any] | None = None

    for step in range(1, 9):
        response = client.create_messages(
            system=LLM_FIT_ANALYSIS_SYSTEM_PROMPT,
            messages=messages,
            max_tokens=4000,
        )
        last_response = response
        response_text = extract_text(response)
        action = _extract_json_object(response_text)
        turns.append(
            {
                "step": step,
                "type": "llm_response",
                "raw_text": response_text,
                "parsed": action,
                "response": response,
            }
        )
        messages.append({"role": "assistant", "content": response_text})

        if action.get("action") == "final" or "markdown_report" in action:
            data = action.get("result") if isinstance(action.get("result"), dict) else action
            break

        if action.get("action") != "tool":
            tool_result = {
                "error": "invalid_action",
                "message": "Return action=tool to request data or action=final to finish.",
            }
        else:
            tool_result = call_fit_analysis_tool(
                str(action.get("tool") or ""),
                action.get("arguments") if isinstance(action.get("arguments"), dict) else {},
                parsed=parsed,
                history_before=history_before,
            )

        turns.append({"step": step, "type": "tool_result", **tool_result})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "tool_result": tool_result,
                        "instruction": "Continue. Request another tool if needed, otherwise return action=final.",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
            }
        )

    if data is None:
        raise RuntimeError("LLM did not return final analysis within 8 tool-loop steps")

    if not isinstance(data.get("markdown_report"), str) or not data["markdown_report"].strip():
        raise RuntimeError("LLM response must include non-empty markdown_report")
    if not isinstance(data.get("strava_summary"), str) or not data["strava_summary"].strip():
        raise RuntimeError("LLM response must include non-empty strava_summary")
    data["model"] = (last_response or {}).get("model")
    data["raw_response_id"] = (last_response or {}).get("id")
    data["strava_summary_tone"] = strava_summary_tone
    log_path = append_chat_log(
        session_id,
        {
            "event": "fit_analysis_tool_loop",
            "fit_path": str(path),
            "activity_key": _activity_key(path),
            "history_included": history_before is not None,
            "strava_summary_tone": strava_summary_tone,
            "system": LLM_FIT_ANALYSIS_SYSTEM_PROMPT,
            "messages": messages,
            "turns": turns,
            "parsed_response": data,
        },
    )
    data["session_id"] = session_id
    data["log_path"] = str(log_path)
    data["readable_log_path"] = str(readable_chat_log_path(log_path))
    return data


def build_initial_loop_payload(
    path: Path,
    parsed: dict[str, Any],
    *,
    history_before: dict[str, Any] | None,
    strava_summary_tone: dict[str, str],
) -> dict[str, Any]:
    return {
        "instruction": (
            "You are in a hidden FIT analysis tool loop. The user asked to analyze this activity. "
            "Start from this brief FIT summary. Request extra data only when you need it."
        ),
        "output_contract": {
            "tool_request": {"action": "tool", "tool": "tool_name", "arguments": {}},
            "final": {
                "action": "final",
                "markdown_report": "Chinese markdown report.",
                "strava_summary": "About 200 Chinese characters for Strava. Follow strava_summary_style; it may be normal, professional, playful, minimal, humorous, or occasionally catgirl.",
                "history_entry": "Compact JSON object for future comparisons.",
            },
        },
        "strava_summary_style": strava_summary_tone,
        "fit_file": {
            "path": str(path),
            "name": path.name,
            "activity_key": _activity_key(path),
        },
        "fit_summary": parsed.get("summary", {}),
        "history_available": history_before is not None,
        "available_tools": fit_analysis_tool_catalog(),
    }


def fit_analysis_tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "get_activity_overview",
            "description": "Return a compact high-level activity overview for first-pass understanding: sport, local start time, duration, distance, calories, basic load, and data availability.",
            "arguments": {},
        },
        {
            "name": "get_activity_summary",
            "description": "Return structured objective activity summary by sections. Use sections to request activity_identity, duration_distance, speed_pace, power, heart_rate, cadence, elevation, energy_load, training_zones, laps, device_profile, data_availability, or all.",
            "arguments": {"sections": ["all"]},
        },
        {
            "name": "get_time_intervals",
            "description": "Return fixed time-window averages. bucket_seconds supports 1-600 seconds; prefer 30s/60s/5min for normal analysis. Use start_s/end_s for a focused window such as 100-200s sprint. Power/cadence/speed include non-zero averages and zero fractions to distinguish coasting or stopping.",
            "arguments": {"bucket_seconds": 60, "start_s": None, "end_s": None},
        },
        {
            "name": "get_distance_intervals",
            "description": "Return fixed distance-window averages. Use bucket_distance_m for every 1km/3km/5km; use start_d/end_d for a focused window such as 2km-3km climb. Power/cadence/speed include non-zero averages and zero fractions to distinguish coasting or stopping.",
            "arguments": {"bucket_distance_m": 1000, "start_d": None, "end_d": None},
        },
        {
            "name": "get_history",
            "description": "Return prior compact training history if history is enabled for this analysis.",
            "arguments": {},
        },
    ]


def choose_strava_summary_tone() -> dict[str, str]:
    tone = random.choices(
        STRAVA_SUMMARY_TONES,
        weights=[int(tone.get("weight", 1)) for tone in STRAVA_SUMMARY_TONES],
        k=1,
    )[0]
    return {key: value for key, value in tone.items() if key != "weight"}


def call_fit_analysis_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    parsed: dict[str, Any],
    history_before: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        if name == "get_activity_overview":
            result = get_activity_overview_tool(parsed)
        elif name == "get_activity_summary":
            result = get_activity_summary_tool(parsed, sections=arguments.get("sections"))
        elif name == "get_fit_summary":
            result = {
                "summary": parsed.get("summary", {}),
                "sessions": parsed.get("sessions", []),
                "record_count": len(parsed.get("records", [])),
                "lap_count": len(parsed.get("laps", [])),
            }
        elif name == "get_laps":
            result = {"laps": parsed.get("laps", [])}
        elif name == "get_numeric_stats":
            result = {"numeric_field_stats": _numeric_field_stats(records_dataframe(parsed.get("records", [])))}
        elif name == "get_sampled_records":
            result = get_sampled_records_tool(parsed, max_records=int(arguments.get("max_records", 80)))
        elif name == "get_time_intervals":
            result = get_time_intervals_tool(
                parsed,
                bucket_seconds=int(arguments.get("bucket_seconds", 60)),
                start_s=arguments.get("start_s"),
                end_s=arguments.get("end_s"),
            )
        elif name == "get_distance_intervals":
            result = get_distance_intervals_tool(
                parsed,
                bucket_distance_m=arguments.get("bucket_distance_m", 1000),
                start_d=arguments.get("start_d"),
                end_d=arguments.get("end_d"),
            )
        elif name == "get_interval_series":
            result = get_time_intervals_tool(parsed, bucket_seconds=int(arguments.get("bucket_seconds", 60)))
        elif name == "get_training_metadata":
            result = {"training_metadata": parsed.get("training_metadata", {})}
        elif name == "get_history":
            result = history_before or {
                "schema_version": "file_training_history.v1",
                "count": 0,
                "activities": [],
                "note": "History was not enabled or no previous activities exist.",
            }
        else:
            return {"tool": name, "arguments": arguments, "error": "unknown_tool"}
        return {"tool": name, "arguments": arguments, "result": prune_empty_values(result)}
    except Exception as exc:
        return {
            "tool": name,
            "arguments": arguments,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def get_sampled_records_tool(parsed: dict[str, Any], *, max_records: int = 80) -> dict[str, Any]:
    records = parsed.get("records", [])
    record_count = len(records)
    max_records = max(1, min(int(max_records), 300))
    sample_step = max(1, record_count // max_records) if record_count else 1
    sampled_records = [
        _compact_record(record)
        for index, record in enumerate(records)
        if index % sample_step == 0 or index == record_count - 1
    ]
    return {
        "record_count": record_count,
        "sample_step": sample_step,
        "sampled_records": sampled_records[:max_records],
    }


def get_activity_overview_tool(parsed: dict[str, Any]) -> dict[str, Any]:
    summary = parsed.get("summary") or {}
    session = _last_item(parsed.get("sessions")) or {}
    stats = _numeric_field_stats(records_dataframe(parsed.get("records", [])))

    duration_s = _first_number(summary.get("duration_s"), session.get("total_timer_time"), session.get("total_elapsed_time"))
    distance_m = _first_number(summary.get("distance_m"), session.get("total_distance"))
    calories = _first_number(session.get("total_calories"))
    avg_power = _first_number(session.get("avg_power"), _stats_value(stats, "power", "avg"))
    max_power = _first_number(session.get("max_power"), _stats_value(stats, "power", "max"))
    avg_hr = _first_number(session.get("avg_heart_rate"), _stats_value(stats, "heart_rate", "avg"))
    max_hr = _first_number(session.get("max_heart_rate"), _stats_value(stats, "heart_rate", "max"))
    avg_cadence = _first_number(session.get("avg_cadence"), _stats_value(stats, "cadence", "avg"))
    avg_speed = _first_number(session.get("enhanced_avg_speed"), session.get("avg_speed"), _stats_value(stats, "enhanced_speed", "avg"))

    return {
        "schema_version": "activity_overview.v1",
        "activity_identity": {
            "sport_type": summary.get("sport_type"),
            "sub_sport": summary.get("sub_sport"),
            "start_time_local": summary.get("start_time_local"),
            "start_time_utc": summary.get("start_time_utc") or summary.get("start_time"),
        },
        "scale": {
            "duration_min": _seconds_to_minutes(duration_s),
            "distance_km": _meters_to_km(distance_m),
            "calories": _round_float(calories, 0),
        },
        "basic_metrics": {
            "avg_speed_kmh": _mps_to_kmh(avg_speed),
            "avg_power_w": _round_float(avg_power, 1),
            "max_power_w": _round_float(max_power, 1),
            "avg_hr_bpm": _round_float(avg_hr, 1),
            "max_hr_bpm": _round_float(max_hr, 1),
            "avg_cadence_rpm": _round_float(avg_cadence, 1),
            "normalized_power_w": _round_float(session.get("normalized_power"), 1),
            "tss": _round_float(session.get("training_stress_score"), 1),
            "intensity_factor": _round_float(session.get("intensity_factor"), 3),
        },
        "data_availability": {
            "record_count": summary.get("record_count"),
            "lap_count": summary.get("lap_count"),
            "has_power": summary.get("has_power"),
            "has_heart_rate": summary.get("has_heart_rate"),
            "has_position": summary.get("has_position"),
            "has_cadence": "cadence" in stats,
            "has_altitude": "enhanced_altitude" in stats or "altitude" in stats,
        },
    }


def get_activity_summary_tool(parsed: dict[str, Any], *, sections: Any = None) -> dict[str, Any]:
    requested = _normalize_summary_sections(sections)
    summary = parsed.get("summary") or {}
    session = _last_item(parsed.get("sessions")) or {}
    metadata = parsed.get("training_metadata") or {}
    stats = _numeric_field_stats(records_dataframe(parsed.get("records", [])))

    section_builders = {
        "activity_identity": lambda: _summary_activity_identity(parsed, summary),
        "duration_distance": lambda: _summary_duration_distance(summary, session),
        "speed_pace": lambda: _summary_speed_pace(session, stats),
        "power": lambda: _summary_power(session, stats, metadata),
        "heart_rate": lambda: _summary_heart_rate(session, stats, metadata),
        "cadence": lambda: _summary_cadence(session, stats),
        "elevation": lambda: _summary_elevation(session, stats),
        "energy_load": lambda: _summary_energy_load(session),
        "training_zones": lambda: _summary_training_zones(metadata),
        "laps": lambda: _summary_laps(parsed.get("laps") or []),
        "device_profile": lambda: _summary_device_profile(metadata),
        "data_availability": lambda: _summary_data_availability(summary, stats),
    }

    result: dict[str, Any] = {
        "schema_version": "activity_summary.v1",
        "sections": requested,
    }
    for section in requested:
        builder = section_builders.get(section)
        if builder:
            result[section] = builder()
    return result


def get_time_intervals_tool(
    parsed: dict[str, Any],
    *,
    bucket_seconds: int = 60,
    start_s: Any = None,
    end_s: Any = None,
) -> dict[str, Any]:
    df = records_dataframe(parsed.get("records", []))
    if df.empty or "elapsed_s" not in df.columns:
        return {
            "available": False,
            "reason": "No records or elapsed_s data available.",
        }

    bucket_seconds = _normalize_bucket_seconds(bucket_seconds)
    working = _filter_numeric_window(df, "elapsed_s", start=start_s, end=end_s)
    if working.empty:
        return {
            "available": False,
            "reason": "No records in requested time window.",
            "mode": "time",
            "bucket_seconds": bucket_seconds,
            "window": {"start_s": _round_float(start_s, 1), "end_s": _round_float(end_s, 1)},
        }
    working["bucket_index"] = (working["elapsed_s"] // bucket_seconds).astype(int)
    rows: list[dict[str, Any]] = []

    for bucket_index, group in working.groupby("bucket_index", sort=True):
        bucket_start_s = float(bucket_index) * bucket_seconds
        bucket_end_s = bucket_start_s + bucket_seconds
        row: dict[str, Any] = {
            "start_s": _round_float(bucket_start_s, 1),
            "end_s": _round_float(bucket_end_s, 1),
            "duration_s": _round_float(_duration_from_group(group), 1),
            "samples": int(len(group)),
        }
        row.update(_distance_delta(group))
        row.update(_series_stats(group, "heart_rate", "hr_bpm"))
        row.update(_series_stats(group, "power", "power_w", include_zero_stats=True))
        row.update(_series_stats(group, "cadence", "cadence_rpm", include_zero_stats=True))
        row.update(_series_stats(group, "enhanced_speed", "speed_mps", include_zero_stats=True))
        row.update(_series_stats(group, "enhanced_altitude", "altitude_m"))
        rows.append(prune_empty_values(row))

    return {
        "available": True,
        "mode": "time",
        "bucket_seconds": bucket_seconds,
        "record_count": int(len(df)),
        "filtered_count": int(len(working)),
        "bucket_count": len(rows),
        "window": {"start_s": _round_float(start_s, 1), "end_s": _round_float(end_s, 1)},
        "format": "column_arrays",
        "series": _rows_to_column_arrays(rows),
    }


def get_distance_intervals_tool(
    parsed: dict[str, Any],
    *,
    bucket_distance_m: Any = 1000,
    start_d: Any = None,
    end_d: Any = None,
) -> dict[str, Any]:
    df = records_dataframe(parsed.get("records", []))
    if df.empty or "distance" not in df.columns:
        return {
            "available": False,
            "reason": "No records or distance data available.",
        }

    bucket_distance_m = _normalize_bucket_distance_m(bucket_distance_m)
    working = _filter_numeric_window(df, "distance", start=start_d, end=end_d)
    if working.empty:
        return {
            "available": False,
            "reason": "No records in requested distance window.",
            "mode": "distance",
            "bucket_distance_m": bucket_distance_m,
            "window": {"start_d": _round_float(start_d, 1), "end_d": _round_float(end_d, 1)},
        }

    working["bucket_index"] = (working["distance"].astype(float) // bucket_distance_m).astype(int)
    rows: list[dict[str, Any]] = []

    for bucket_index, group in working.groupby("bucket_index", sort=True):
        start_d_bucket = float(bucket_index) * bucket_distance_m
        end_d_bucket = start_d_bucket + bucket_distance_m
        row: dict[str, Any] = {
            "start_d": _round_float(start_d_bucket, 1),
            "end_d": _round_float(end_d_bucket, 1),
            "duration_s": _round_float(_duration_from_group(group), 1),
            "samples": int(len(group)),
        }
        row.update(_distance_delta(group))
        row.update(_series_stats(group, "heart_rate", "hr_bpm"))
        row.update(_series_stats(group, "power", "power_w", include_zero_stats=True))
        row.update(_series_stats(group, "cadence", "cadence_rpm", include_zero_stats=True))
        row.update(_series_stats(group, "enhanced_speed", "speed_mps", include_zero_stats=True))
        row.update(_series_stats(group, "enhanced_altitude", "altitude_m"))
        rows.append(prune_empty_values(row))

    return {
        "available": True,
        "mode": "distance",
        "bucket_distance_m": bucket_distance_m,
        "record_count": int(len(df)),
        "filtered_count": int(len(working)),
        "bucket_count": len(rows),
        "window": {"start_d": _round_float(start_d, 1), "end_d": _round_float(end_d, 1)},
        "format": "column_arrays",
        "series": _rows_to_column_arrays(rows),
    }


def normalize_history_entry(
    entry: dict[str, Any],
    *,
    path: Path,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    summary = parsed.get("summary", {})
    normalized = dict(entry)
    normalized.setdefault("schema_version", "llm_activity_history_entry.v1")
    normalized["activity_key"] = _activity_key(path)
    normalized["file_path"] = str(path)
    normalized.setdefault("start_time", summary.get("start_time"))
    normalized.setdefault("start_time_local", summary.get("start_time_local"))
    normalized.setdefault("sport_type", summary.get("sport_type"))
    normalized.setdefault("sub_sport", summary.get("sub_sport"))
    normalized.setdefault("duration_s", summary.get("duration_s"))
    normalized.setdefault("distance_m", summary.get("distance_m"))
    normalized.setdefault("brief", "")
    return normalized


def write_brief_report(result: dict[str, Any]) -> Path:
    report_path = _report_path(Path(result["fit_path"]))
    lines = [
        result["markdown_report"].strip(),
        "",
        "## Strava Summary",
        "",
        result.get("strava_summary", "").strip(),
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _summary_path(path: Path) -> Path:
    ensure_data_dirs()
    summaries = Path("data") / "summaries"
    return summaries / f"{path.stem}.summary.json"


def _read_existing_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _preserve_guided_analysis(result: dict[str, Any], previous: dict[str, Any]) -> None:
    if not previous:
        return
    if "guided_analysis" in previous:
        result["guided_analysis"] = previous["guided_analysis"]
    if "guided_analysis_history" in previous:
        result["guided_analysis_history"] = previous["guided_analysis_history"]


def _report_path(path: Path) -> Path:
    paths = ensure_data_dirs()
    return paths["reports"] / f"{path.stem}.md"


def _activity_key(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "timestamp",
        "elapsed_s",
        "distance",
        "enhanced_speed",
        "speed",
        "heart_rate",
        "power",
        "cadence",
        "enhanced_altitude",
        "altitude",
        "position_lat",
        "position_long",
    ]
    return prune_empty_values({field: record.get(field) for field in fields if field in record})


def prune_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            pruned = prune_empty_values(item)
            if _is_empty_value(pruned):
                continue
            cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        cleaned_list = [prune_empty_values(item) for item in value]
        return [item for item in cleaned_list if not _is_empty_value(item)]
    return value


def _is_empty_value(value: Any) -> bool:
    return value is None or value == {} or value == []


SUMMARY_SECTIONS = [
    "activity_identity",
    "duration_distance",
    "speed_pace",
    "power",
    "heart_rate",
    "cadence",
    "elevation",
    "energy_load",
    "training_zones",
    "laps",
    "device_profile",
    "data_availability",
]

DEFAULT_SUMMARY_SECTIONS = [
    "activity_identity",
    "duration_distance",
    "speed_pace",
    "power",
    "heart_rate",
    "cadence",
    "elevation",
    "energy_load",
    "data_availability",
]


def _normalize_summary_sections(value: Any) -> list[str]:
    if value in (None, "", []):
        return list(DEFAULT_SUMMARY_SECTIONS)
    if isinstance(value, str):
        raw_sections = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        raw_sections = [str(part).strip() for part in value if str(part).strip()]
    else:
        raw_sections = []
    if not raw_sections or "all" in raw_sections:
        return list(SUMMARY_SECTIONS)
    return [section for section in SUMMARY_SECTIONS if section in raw_sections]


def _summary_activity_identity(parsed: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_file": parsed.get("path"),
        "sport_type": summary.get("sport_type"),
        "sub_sport": summary.get("sub_sport"),
        "start_time_local": summary.get("start_time_local"),
        "start_time_utc": summary.get("start_time_utc") or summary.get("start_time"),
        "timezone_note": summary.get("timezone_note"),
    }


def _summary_duration_distance(summary: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    duration_s = _first_number(summary.get("duration_s"), session.get("total_timer_time"))
    elapsed_s = _first_number(session.get("total_elapsed_time"), duration_s)
    distance_m = _first_number(summary.get("distance_m"), session.get("total_distance"))
    return {
        "duration_s": _round_float(duration_s, 1),
        "duration_min": _seconds_to_minutes(duration_s),
        "elapsed_s": _round_float(elapsed_s, 1),
        "elapsed_min": _seconds_to_minutes(elapsed_s),
        "distance_m": _round_float(distance_m, 1),
        "distance_km": _meters_to_km(distance_m),
    }


def _summary_speed_pace(session: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    avg_speed = _first_number(session.get("enhanced_avg_speed"), session.get("avg_speed"), _stats_value(stats, "enhanced_speed", "avg"))
    max_speed = _first_number(session.get("enhanced_max_speed"), session.get("max_speed"), _stats_value(stats, "enhanced_speed", "max"))
    return {
        "avg_speed_mps": _round_float(avg_speed, 3),
        "max_speed_mps": _round_float(max_speed, 3),
        "avg_speed_kmh": _mps_to_kmh(avg_speed),
        "max_speed_kmh": _mps_to_kmh(max_speed),
        "speed_stats_mps": _select_stats(stats, "enhanced_speed"),
    }


def _summary_power(session: dict[str, Any], stats: dict[str, dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    zones_target = metadata.get("zones_target") or {}
    avg_power = _first_number(session.get("avg_power"), _stats_value(stats, "power", "avg"))
    normalized_power = _first_number(session.get("normalized_power"))
    return {
        "avg_power_w": _round_float(avg_power, 1),
        "max_power_w": _round_float(_first_number(session.get("max_power"), _stats_value(stats, "power", "max")), 1),
        "normalized_power_w": _round_float(normalized_power, 1),
        "threshold_power_w": _round_float(_first_number(session.get("threshold_power"), zones_target.get("functional_threshold_power")), 1),
        "intensity_factor": _round_float(session.get("intensity_factor"), 3),
        "variability_index": _round_float((normalized_power / avg_power) if avg_power and normalized_power else None, 3),
        "total_work_kj": _round_float(_first_number(session.get("total_work")) / 1000 if _first_number(session.get("total_work")) is not None else None, 1),
        "power_stats_w": _select_stats(stats, "power"),
    }


def _summary_heart_rate(session: dict[str, Any], stats: dict[str, dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    zones_target = metadata.get("zones_target") or {}
    profile = metadata.get("user_profile") or {}
    return {
        "avg_hr_bpm": _round_float(_first_number(session.get("avg_heart_rate"), _stats_value(stats, "heart_rate", "avg")), 1),
        "max_hr_bpm": _round_float(_first_number(session.get("max_heart_rate"), _stats_value(stats, "heart_rate", "max")), 1),
        "resting_hr_bpm": _round_float(profile.get("resting_heart_rate"), 1),
        "max_hr_setting_bpm": _round_float(_first_number(zones_target.get("max_heart_rate"), profile.get("default_max_biking_heart_rate"), profile.get("default_max_heart_rate")), 1),
        "threshold_hr_bpm": _round_float(zones_target.get("threshold_heart_rate"), 1),
        "heart_rate_stats_bpm": _select_stats(stats, "heart_rate"),
    }


def _summary_cadence(session: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "avg_cadence_rpm": _round_float(_first_number(session.get("avg_cadence"), _stats_value(stats, "cadence", "avg")), 1),
        "max_cadence_rpm": _round_float(_first_number(session.get("max_cadence"), _stats_value(stats, "cadence", "max")), 1),
        "cadence_stats_rpm": _select_stats(stats, "cadence"),
    }


def _summary_elevation(session: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    altitude_stats = _select_stats(stats, "enhanced_altitude") or _select_stats(stats, "altitude")
    return {
        "total_ascent_m": _round_float(session.get("total_ascent"), 1),
        "total_descent_m": _round_float(session.get("total_descent"), 1),
        "altitude_stats_m": altitude_stats,
    }


def _summary_energy_load(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "calories": _round_float(session.get("total_calories"), 0),
        "tss": _round_float(session.get("training_stress_score"), 1),
        "training_load_peak": _round_float(session.get("training_load_peak"), 1),
        "aerobic_training_effect": _round_float(session.get("total_training_effect"), 1),
        "anaerobic_training_effect": _round_float(session.get("total_anaerobic_training_effect"), 1),
    }


def _summary_training_zones(metadata: dict[str, Any]) -> dict[str, Any]:
    zones_target = metadata.get("zones_target") or {}
    return {
        "zones_target": zones_target,
        "time_in_zone": metadata.get("time_in_zone"),
    }


def _summary_laps(laps: list[dict[str, Any]]) -> dict[str, Any]:
    compact_laps: list[dict[str, Any]] = []
    for index, lap in enumerate(laps, start=1):
        compact_laps.append(
            {
                "index": index,
                "start_time": lap.get("start_time"),
                "total_timer_time": _round_float(lap.get("total_timer_time"), 1),
                "total_elapsed_time": _round_float(lap.get("total_elapsed_time"), 1),
                "total_distance": _round_float(lap.get("total_distance"), 1),
                "avg_speed": _round_float(_first_number(lap.get("enhanced_avg_speed"), lap.get("avg_speed")), 3),
                "avg_power": _round_float(lap.get("avg_power"), 1),
                "max_power": _round_float(lap.get("max_power"), 1),
                "avg_heart_rate": _round_float(lap.get("avg_heart_rate"), 1),
                "max_heart_rate": _round_float(lap.get("max_heart_rate"), 1),
                "avg_cadence": _round_float(lap.get("avg_cadence"), 1),
                "total_ascent": _round_float(lap.get("total_ascent"), 1),
                "total_descent": _round_float(lap.get("total_descent"), 1),
            }
        )
    return {"lap_count": len(laps), "laps": compact_laps}


def _summary_device_profile(metadata: dict[str, Any]) -> dict[str, Any]:
    devices = metadata.get("device_info") or []
    device = devices[-1] if isinstance(devices, list) and devices else {}
    return {
        "user_profile": metadata.get("user_profile"),
        "device": device,
        "device_settings": metadata.get("device_settings"),
    }


def _summary_data_availability(summary: dict[str, Any], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": summary.get("record_count"),
        "lap_count": summary.get("lap_count"),
        "has_power": summary.get("has_power"),
        "has_heart_rate": summary.get("has_heart_rate"),
        "has_position": summary.get("has_position"),
        "has_cadence": "cadence" in stats,
        "has_speed": "enhanced_speed" in stats or "speed" in stats,
        "has_altitude": "enhanced_altitude" in stats or "altitude" in stats,
    }


def _select_stats(stats: dict[str, dict[str, Any]], field: str) -> dict[str, Any]:
    values = stats.get(field) or {}
    return {
        key: values.get(key)
        for key in ["count", "min", "max", "avg", "median", "p25", "p75"]
        if key in values
    }


def _last_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value:
        item = value[-1]
        return item if isinstance(item, dict) else None
    return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _round_float(value)
        if number is not None:
            return number
    return None


def _stats_value(stats: dict[str, dict[str, Any]], field: str, metric: str) -> Any:
    return (stats.get(field) or {}).get(metric)


def _seconds_to_minutes(value: Any) -> float | None:
    number = _round_float(value)
    if number is None:
        return None
    return _round_float(number / 60, 1)


def _meters_to_km(value: Any) -> float | None:
    number = _round_float(value)
    if number is None:
        return None
    return _round_float(number / 1000, 2)


def _mps_to_kmh(value: Any) -> float | None:
    number = _round_float(value)
    if number is None:
        return None
    return _round_float(number * 3.6, 1)


def _rows_to_column_arrays(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    if not rows:
        return {}
    ordered_keys = [
        "start_s",
        "end_s",
        "start_d",
        "end_d",
        "duration_s",
        "samples",
        "distance_start_m",
        "distance_end_m",
        "distance_delta_m",
        "avg_hr_bpm",
        "max_hr_bpm",
        "avg_power_w",
        "avg_nonzero_power_w",
        "max_power_w",
        "power_w_zero_samples",
        "power_w_zero_fraction",
        "avg_cadence_rpm",
        "avg_nonzero_cadence_rpm",
        "max_cadence_rpm",
        "cadence_rpm_zero_samples",
        "cadence_rpm_zero_fraction",
        "avg_speed_mps",
        "avg_nonzero_speed_mps",
        "max_speed_mps",
        "speed_mps_zero_samples",
        "speed_mps_zero_fraction",
        "avg_altitude_m",
        "max_altitude_m",
    ]
    common_keys = set(rows[0])
    for row in rows[1:]:
        common_keys &= set(row)
    return {
        key: [row[key] for row in rows]
        for key in ordered_keys
        if key in common_keys
    }


def _normalize_bucket_seconds(value: int) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 60
    return max(1, min(seconds, 600))


def _normalize_bucket_distance_m(value: Any) -> int:
    allowed = [100, 200, 500, 1000, 3000, 5000, 10000]
    try:
        distance = int(float(value))
    except (TypeError, ValueError):
        return 1000
    if distance in allowed:
        return distance
    return min(allowed, key=lambda candidate: abs(candidate - distance))


def _filter_numeric_window(df: Any, column: str, *, start: Any = None, end: Any = None) -> Any:
    working = df.copy()
    try:
        values = working[column].astype(float)
    except (KeyError, TypeError, ValueError):
        return working.iloc[0:0]
    start_value = _round_float(start)
    end_value = _round_float(end)
    if start_value is not None:
        working = working[values >= start_value]
        values = working[column].astype(float)
    if end_value is not None:
        working = working[values <= end_value]
    return working.copy()


def _duration_from_group(group: Any) -> float | None:
    try:
        elapsed = group["elapsed_s"].dropna().astype(float)
    except (KeyError, TypeError, ValueError):
        return None
    if elapsed.empty:
        return None
    if len(elapsed) == 1:
        return 0.0
    return float(elapsed.max() - elapsed.min())


def _distance_delta(group: Any) -> dict[str, float | None]:
    if "distance" not in group.columns:
        return {}
    try:
        values = group["distance"].dropna().astype(float)
    except (TypeError, ValueError):
        return {}
    if values.empty:
        return {}
    return {
        "distance_start_m": _round_float(values.iloc[0], 1),
        "distance_end_m": _round_float(values.iloc[-1], 1),
        "distance_delta_m": _round_float(values.iloc[-1] - values.iloc[0], 1),
    }


def _series_stats(
    group: Any,
    column: str,
    prefix: str,
    *,
    include_zero_stats: bool = False,
) -> dict[str, float | int | None]:
    if column not in group.columns:
        return {}
    try:
        values = group[column].dropna().astype(float)
    except (TypeError, ValueError):
        return {}
    if values.empty:
        return {}
    result: dict[str, float | int | None] = {
        f"avg_{prefix}": _round_float(values.mean(), 1),
        f"max_{prefix}": _round_float(values.max(), 1),
    }
    if include_zero_stats:
        zero_count = int((values == 0).sum())
        nonzero_values = values[values != 0]
        result.update(
            {
                f"avg_nonzero_{prefix}": _round_float(nonzero_values.mean(), 1)
                if not nonzero_values.empty
                else 0.0,
                f"{prefix}_zero_samples": zero_count,
                f"{prefix}_zero_fraction": _round_float(zero_count / len(values), 3),
            }
        )
    return result


def _numeric_field_stats(df: Any) -> dict[str, dict[str, Any]]:
    if df.empty:
        return {}
    stats: dict[str, dict[str, Any]] = {}
    for column in df.columns:
        values = df[column]
        if not hasattr(values, "dropna"):
            continue
        numeric = None
        try:
            numeric = values.dropna().astype(float)
        except (TypeError, ValueError):
            continue
        if numeric is None or numeric.empty:
            continue
        stats[str(column)] = {
            "count": int(numeric.count()),
            "min": _round_float(numeric.min()),
            "max": _round_float(numeric.max()),
            "avg": _round_float(numeric.mean()),
            "median": _round_float(numeric.median()),
            "p25": _round_float(numeric.quantile(0.25)),
            "p75": _round_float(numeric.quantile(0.75)),
        }
    return stats


def _round_float(value: Any, digits: int = 3) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("LLM response must be a JSON object")
    return data
