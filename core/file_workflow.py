from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from agent.chat_logger import append_chat_log, new_session_id
from agent.llm import AnthropicMessagesClient, extract_text
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
    make_plot: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    path = Path(fit_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".fit":
        raise ValueError(f"Only .fit files are supported: {path}")

    summary_path = _summary_path(path)
    if summary_path.exists() and not force:
        result = json.loads(summary_path.read_text(encoding="utf-8"))
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
        "strava_summary_tone": model_result.get("strava_summary_tone"),
        "markdown_report": model_result["markdown_report"],
        "strava_summary": model_result["strava_summary"],
        "history_entry": history_entry,
        "history_before": history_before,
    }

    if make_plot:
        result["plot_note"] = "Plotting is disabled for the LLM-only workflow."

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
            "name": "get_fit_summary",
            "description": "Return basic summary, sessions, and record/lap counts.",
            "arguments": {},
        },
        {
            "name": "get_laps",
            "description": "Return lap details from the FIT file.",
            "arguments": {},
        },
        {
            "name": "get_numeric_stats",
            "description": "Return stats for numeric record fields such as power, heart_rate, cadence, speed, altitude.",
            "arguments": {},
        },
        {
            "name": "get_sampled_records",
            "description": "Return evenly sampled time-series records. Use max_records to control size.",
            "arguments": {"max_records": 80},
        },
        {
            "name": "get_training_metadata",
            "description": "Return FIT training metadata such as time-in-zone, user profile, device info, events, splits.",
            "arguments": {},
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
        if name == "get_fit_summary":
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
        return {"tool": name, "arguments": arguments, "result": result}
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
    normalized.setdefault("sport_type", summary.get("sport_type"))
    normalized.setdefault("sub_sport", summary.get("sub_sport"))
    normalized.setdefault("duration_s", summary.get("duration_s"))
    normalized.setdefault("distance_m", summary.get("distance_m"))
    normalized.setdefault("brief", "")
    return normalized


def analyze_fit_folder(
    folder: str | Path,
    *,
    use_history: bool = True,
    update_history: bool = True,
    make_plot: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    root = Path(folder).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    fit_files = sorted(root.glob("*.fit"), key=_fit_sort_key)

    results = [
        analyze_fit_file(
            path,
            use_history=use_history,
            update_history=update_history,
            make_plot=make_plot,
            force=force,
        )
        for path in fit_files
    ]
    return {
        "schema_version": "fit_folder_analysis.v1",
        "folder": str(root),
        "count": len(results),
        "analyzed": sum(1 for item in results if item.get("status") == "analyzed"),
        "skipped": sum(1 for item in results if item.get("status") == "skipped_existing_summary"),
        "results": [_compact_folder_result(item) for item in results],
    }


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


def _report_path(path: Path) -> Path:
    paths = ensure_data_dirs()
    return paths["reports"] / f"{path.stem}.md"


def _activity_key(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _fit_sort_key(path: Path) -> tuple[str, str]:
    try:
        parsed = parse_fit(path)
        start_time = parsed.get("summary", {}).get("start_time") or ""
    except Exception:
        start_time = ""
    return (start_time, path.name)


def _compact_folder_result(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("fit_summary") or result.get("summary", {})
    return {
        "status": result.get("status"),
        "fit_path": result.get("fit_path"),
        "summary_path": result.get("summary_path"),
        "report_path": result.get("report_path"),
        "log_path": result.get("log_path"),
        "start_time": summary.get("start_time"),
        "sport_type": summary.get("sport_type"),
        "duration_min": summary.get("duration_min"),
        "distance_km": summary.get("distance_km"),
        "brief": result.get("history_entry", {}).get("brief"),
    }


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
    return {field: record.get(field) for field in fields if field in record}


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


LLM_FIT_ANALYSIS_SYSTEM_PROMPT = """You are an endurance training analysis assistant working inside a hidden local FIT analysis tool loop.

The local program only extracts objective data from FIT files. You are responsible for judgment, synthesis, and writing.

You must either request one internal tool or finish with one final JSON object. Do not return Markdown outside JSON. Do not expose the tool loop to the end user.

If you need more data, reply exactly as JSON:
{
  "action": "tool",
  "tool": "get_numeric_stats",
  "arguments": {}
}

Available tools:
- get_fit_summary: objective high-level FIT summary
- get_laps: lap/segment records
- get_numeric_stats: numeric field statistics
- get_sampled_records: sampled record rows for pacing/power/heart-rate trend checks
- get_training_metadata: sport/profile/device/file metadata
- get_history: compact prior activity history, only useful when historical comparison is needed

Decision guidance:
1. Start from the initial fit_summary.
2. Request get_numeric_stats when you need objective distribution, intensity, power, heart-rate, cadence, or speed details.
3. Request get_laps or get_sampled_records when you need segment, first/second half, or trend judgment.
4. Request get_history only when the user asked to reference history or when longitudinal comparison materially improves the answer.
5. When the data is enough, output final.

Final response must be exactly one JSON object:
{
  "action": "final",
  "markdown_report": "# ...",
  "strava_summary": "About 200 Chinese characters, suitable for Strava activity description. Follow strava_summary_style from the user payload. The tone may be normal, professional, playful, minimal, humorous, or occasionally catgirl; do not force catgirl wording unless that selected style asks for it. Avoid repeating basics Strava already displays, such as distance, duration, average speed, elevation gain, and route. Prefer training stimulus, perceived rhythm judgment, TSS/IF/NP or other metrics Strava may not show, data-quality reminders, and next-session advice.",
  "history_entry": {
    "schema_version": "llm_activity_history_entry.v1",
    "start_time": "...",
    "sport_type": "...",
    "duration_min": 0,
    "distance_km": 0,
    "summary_label": "...",
    "main_stimulus": "...",
    "training_load": "...",
    "quality_notes": ["..."],
    "brief": "A compact Chinese note for future comparison."
  }
}
"""
