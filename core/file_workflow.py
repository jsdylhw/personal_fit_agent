from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from agent.chat_logger import append_chat_log, new_session_id, readable_chat_log_path
from agent.llm import AnthropicMessagesClient, extract_text
from agent.prompts import LLM_FIT_ANALYSIS_SYSTEM_PROMPT
from agent.tools import call_fit_analysis_tool, fit_analysis_tool_catalog
from fit.parser import parse_fit

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

MAX_TOOL_LOOP_STEPS = 8


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
                build_initial_loop_payload(path, parsed, history_before=history_before, strava_summary_tone=strava_summary_tone),
                ensure_ascii=False, indent=2, default=str,
            ),
        }
    ]
    turns: list[dict[str, Any]] = []
    data: dict[str, Any] | None = None
    last_response: dict[str, Any] | None = None

    for step in range(1, MAX_TOOL_LOOP_STEPS + 1):
        response = client.create_messages(
            system=LLM_FIT_ANALYSIS_SYSTEM_PROMPT, messages=messages, max_tokens=4000,
        )
        last_response = response
        response_text = extract_text(response)
        action = _extract_json_object(response_text)
        turns.append({
            "step": step, "type": "llm_response",
            "raw_text": response_text, "parsed": action, "response": response,
        })
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
        messages.append({
            "role": "user",
            "content": json.dumps(
                {"tool_result": tool_result, "instruction": "Continue. Request another tool if needed, otherwise return action=final."},
                ensure_ascii=False, indent=2, default=str,
            ),
        })

    if data is None:
        raise RuntimeError("LLM did not return final analysis within tool-loop steps")

    if not isinstance(data.get("markdown_report"), str) or not data["markdown_report"].strip():
        raise RuntimeError("LLM response must include non-empty markdown_report")
    if not isinstance(data.get("strava_summary"), str) or not data["strava_summary"].strip():
        raise RuntimeError("LLM response must include non-empty strava_summary")
    data["model"] = (last_response or {}).get("model")
    data["raw_response_id"] = (last_response or {}).get("id")
    data["strava_summary_tone"] = strava_summary_tone
    log_path = append_chat_log(session_id, {
        "event": "fit_analysis_tool_loop",
        "fit_path": str(path),
        "activity_key": _activity_key(path),
        "history_included": history_before is not None,
        "strava_summary_tone": strava_summary_tone,
        "system": LLM_FIT_ANALYSIS_SYSTEM_PROMPT,
        "messages": messages,
        "turns": turns,
        "parsed_response": data,
    })
    data["session_id"] = session_id
    data["log_path"] = str(log_path)
    data["readable_log_path"] = str(readable_chat_log_path(log_path))
    return data


def build_initial_loop_payload(
    path: Path, parsed: dict[str, Any], *,
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
        "fit_file": {"path": str(path), "name": path.name, "activity_key": _activity_key(path)},
        "fit_summary": parsed.get("summary", {}),
        "history_available": history_before is not None,
        "available_tools": fit_analysis_tool_catalog(),
    }


def choose_strava_summary_tone() -> dict[str, str]:
    tone = random.choices(
        STRAVA_SUMMARY_TONES,
        weights=[int(tone.get("weight", 1)) for tone in STRAVA_SUMMARY_TONES],
        k=1,
    )[0]
    return {key: value for key, value in tone.items() if key != "weight"}


def normalize_history_entry(entry: dict[str, Any], *, path: Path, parsed: dict[str, Any]) -> dict[str, Any]:
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


# -- internal helpers --------------------------------------------------------

def _summary_path(path: Path) -> Path:
    ensure_data_dirs()
    return Path("data") / "summaries" / f"{path.stem}.summary.json"


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
