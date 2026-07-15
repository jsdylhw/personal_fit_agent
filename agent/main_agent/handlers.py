"""Direct business handlers for LLM tool calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.context import AgentContext
from agent.activity.permission import request_analysis_write_confirmation
from agent.llm import AnthropicMessagesClient, extract_text
from agent.operations import analyze_fit_file_tool, upload_to_strava_tool


def execute_analyze_new_fit_files(context: AgentContext, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    permission = request_analysis_write_confirmation(context, tool_name="analyze_new_activities", args=args)
    if permission is not None:
        return permission

    previous = (context.last_tool_result or {}).get("result") or {}
    sync_result = previous.get("result") if isinstance(previous.get("result"), dict) else previous
    items = sync_result.get("downloaded_items") or []
    fit_paths = _fit_paths_from_items(items)
    analyses = [
        analyze_fit_file_tool(str(path), force=False)
        for path in fit_paths
    ]
    return {
        "step": "analyze_new_fit_files",
        "result": {
            "count": len(analyses),
            "analyses": analyses,
        },
    }


def execute_generate_summary_file(
    name: str,
    args: dict[str, Any],
    context: AgentContext,
) -> dict[str, Any]:
    fit_path = _current_fit_path(context)
    permission = request_analysis_write_confirmation(context, tool_name=name, args=args)
    if permission is not None:
        return permission

    result = analyze_fit_file_tool(str(fit_path), force=bool(args.get("force")))
    if result.get("fit_path"):
        context.current_fit_file = Path(str(result["fit_path"])).expanduser()
    return {"step": name, "result": result}


def execute_ensure_activity_summaries(
    name: str,
    args: dict[str, Any],
    context: AgentContext,
) -> dict[str, Any]:
    force = bool(args.get("force"))
    will_write = force or any(
        not (
            isinstance(activity, dict)
            and activity.get("summary_path")
            and Path(str(activity.get("summary_path"))).expanduser().exists()
        )
        for activity in context.selected_activities
    )
    if will_write:
        permission = request_analysis_write_confirmation(context, tool_name=name, args=args)
        if permission is not None:
            return permission

    analyses = []
    for activity in context.selected_activities:
        fit_path = activity.get("fit_path") if isinstance(activity, dict) else None
        if not fit_path:
            continue
        summary_path = activity.get("summary_path") if isinstance(activity, dict) else None
        if summary_path and Path(str(summary_path)).expanduser().exists() and not force:
            analyses.append({
                "fit_path": str(fit_path),
                "summary_path": str(summary_path),
                "status": "skipped_existing_summary",
            })
            continue
        analyses.append(analyze_fit_file_tool(str(fit_path), force=force))
    return {
        "step": name,
        "result": {
            "count": len(analyses),
            "analyses": analyses,
        },
    }


def execute_upload_strava_activity(
    name: str,
    args: dict[str, Any],
    context: AgentContext,
    *,
    reason: str = "tool_use",
) -> dict[str, Any]:
    fit_path = _current_fit_path(context)
    upload_result = upload_to_strava_tool(
        str(fit_path),
        confirmed=True,
        force=bool(args.get("force")),
    )
    return {
        "step": name,
        "status": "completed",
        "result": {
            "schema_version": "strava_upload_execution.v1",
            "fit_path": str(fit_path),
            "upload_result": upload_result,
        },
        "answer": _generate_upload_result_response(
            upload_result,
            {"name": name, "reason": reason, "arguments": args},
            context,
        ),
    }


def execute_summarize_activity_range(
    name: str,
    args: dict[str, Any],
    context: AgentContext,
    *,
    reason: str = "tool_use",
) -> dict[str, Any]:
    activities = [
        activity
        for activity in context.selected_activities
        if isinstance(activity, dict)
    ]
    scope = context.selected_activity_range or {}
    if not activities:
        answer = _empty_range_answer(scope)
        return {
            "step": name,
            "status": "completed",
            "answer": answer,
            "result": {
                "schema_version": "activity_range_summary.v1",
                "count": 0,
                "scope": scope,
                "activities": [],
            },
        }

    force = bool(args.get("force"))
    if _activities_need_summary_generation(activities, force=force):
        permission = request_analysis_write_confirmation(context, tool_name=name, args=args)
        if permission is not None:
            return permission

    summary_generation = _ensure_summaries_for_activities(activities, force=force)

    activities = _reload_activities_from_index(activities)
    context.selected_activities = activities

    normalized = [_compact_range_activity(activity) for activity in activities]
    total_distance = round(sum(float(item.get("distance_km") or 0) for item in normalized), 2)
    total_duration = round(sum(float(item.get("duration_min") or 0) for item in normalized), 1)
    result = {
        "schema_version": "activity_range_summary.v1",
        "count": len(normalized),
        "scope": scope,
        "totals": {
            "distance_km": total_distance,
            "duration_min": total_duration,
        },
        "activities": normalized,
        "summary_generation": summary_generation,
    }
    answer = (
        _generate_range_ai_summary(result, activities, context, args, reason=reason)
        if _should_generate_ai_range_summary(args, reason=reason)
        else _format_range_summary_answer(result)
    )
    return {
        "step": name,
        "status": "completed",
        "answer": answer,
        "result": result,
    }


def empty_activity_resolution_answer(step_name: str, result: dict[str, Any]) -> str | None:
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(payload, dict):
        return None

    matched_count = payload.get("matched_count")
    count = payload.get("count")
    is_empty = matched_count == 0 or count == 0
    if not is_empty:
        return None

    if step_name == "resolve_activity_range":
        start = payload.get("start_date")
        end = payload.get("end_date")
        if start and end:
            return f"{start} 到 {end} 没有找到已索引的活动。"
        return "这个时间范围内没有找到已索引的活动。"
    if step_name == "resolve_recent_activities":
        return "没有找到已索引的最近活动。你可以先重建索引或同步 Garmin 活动。"
    return "没有找到符合条件的活动。你可以先重建索引，或确认日期、序号、活动名称是否正确。"


def _generate_upload_result_response(
    upload_result: dict[str, Any],
    step: dict[str, Any],
    context: AgentContext,
) -> str:
    payload = {
        "user_message": _latest_user_message(context),
        "step": step,
        "upload_result": upload_result,
    }
    response = AnthropicMessagesClient().create_message(
        system=(
            "你是 Personal FIT Agent 的 Strava 上传结果说明助手."
            "只基于 upload_result 用中文简洁说明上传成功、重复、更新描述或失败原因;"
            "不要补充新的活动分析,不要建议重新分析,除非工具错误明确要求先分析生成 summary."
        ),
        user=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        max_tokens=600,
        temperature=0,
    )
    text = extract_text(response).strip()
    return text or _format_upload_result_fallback(upload_result)


def _format_upload_result_fallback(upload_result: dict[str, Any]) -> str:
    if upload_result.get("error"):
        return str(upload_result.get("message") or f"Strava 上传失败:{upload_result.get('error')}")
    status = upload_result.get("status")
    if status == "uploaded":
        return f"Strava 上传成功,活动 ID: {upload_result.get('strava_activity_id')}。"
    if status == "duplicate":
        return str(upload_result.get("message") or "该活动已在 Strava 上存在。")
    if status == "description_updated":
        return str(upload_result.get("message") or "已更新 Strava 活动描述。")
    return f"Strava 上传工具已返回结果: {status or 'unknown'}。"


def _ensure_summaries_for_activities(activities: list[dict[str, Any]], *, force: bool = False) -> dict[str, Any]:
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for activity in activities:
        fit_path = activity.get("fit_path")
        if not fit_path:
            continue
        summary_path = activity.get("summary_path")
        if summary_path and Path(str(summary_path)).expanduser().exists() and not force:
            skipped.append(_summary_generation_item(activity, status="skipped_existing_summary"))
            continue
        result = analyze_fit_file_tool(str(fit_path), force=force)
        generated.append(_summary_generation_item({**activity, **result}, status=str(result.get("status") or "analyzed")))
    return {
        "generated_count": len(generated),
        "skipped_count": len(skipped),
        "generated": generated,
        "skipped": skipped,
    }


def _activities_need_summary_generation(activities: list[dict[str, Any]], *, force: bool = False) -> bool:
    if force:
        return True
    return any(
        not (
            activity.get("summary_path")
            and Path(str(activity.get("summary_path"))).expanduser().exists()
        )
        for activity in activities
    )


def _summary_generation_item(activity: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {
        "activity_index": activity.get("activity_index"),
        "activity_key": activity.get("activity_key"),
        "fit_path": activity.get("fit_path"),
        "summary_path": activity.get("summary_path"),
        "status": status,
    }


def _reload_activities_from_index(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from core.activity_index import load_activity_index

    index = load_activity_index()
    index_map: dict[str, dict[str, Any]] = {}
    for entry in index.get("activities") or []:
        key = entry.get("activity_key")
        if key:
            index_map[key] = entry

    refreshed: list[dict[str, Any]] = []
    for activity in activities:
        key = activity.get("activity_key")
        if key and key in index_map:
            refreshed.append(index_map[key])
        else:
            refreshed.append(activity)
    return refreshed


def _should_generate_ai_range_summary(args: dict[str, Any], *, reason: str = "") -> bool:
    mode = str(args.get("response_mode") or args.get("summary_mode") or "").lower()
    if mode in {"ai", "ai_summary", "llm", "llm_summary", "report"}:
        return True
    text = f"{reason} {args}".lower()
    return any(token in text for token in ("ai", "大模型", "总结报告", "详细", "整体情况", "整体分析"))


def _generate_range_ai_summary(
    summary: dict[str, Any],
    activities: list[dict[str, Any]],
    context: AgentContext,
    args: dict[str, Any] | None = None,
    *,
    reason: str = "",
) -> str:
    args = args or {}
    user_message = _latest_user_message(context)
    detail_level = str(args.get("detail_level") or "normal")
    payload = {
        "user_message": user_message,
        "detail_level": detail_level,
        "range_summary": summary,
        "activity_details": [
            _activity_for_range_llm(activity)
            for activity in activities[:20]
        ],
    }
    response = AnthropicMessagesClient().create_message(
        system=(
            "你是骑行训练分析助手.基于用户请求和本地已保存的活动简要报告,"
            "输出中文活动整体总结报告.不要编造未提供的数据;不要输出 JSON."
        ),
        user=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        max_tokens=1800 if detail_level == "detailed" else 1000,
        temperature=0.2,
    )
    text = extract_text(response)
    return text.strip() or _format_range_summary_answer(summary)


def _latest_user_message(context: AgentContext) -> str:
    for message in reversed(context.messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _activity_for_range_llm(activity: dict[str, Any]) -> dict[str, Any]:
    item = _compact_range_activity(activity)
    summary_path = activity.get("summary_path")
    if summary_path:
        item["summary_detail"] = _read_summary_detail(summary_path)
    return item


def _read_summary_detail(summary_path: Any) -> dict[str, Any]:
    try:
        data = json.loads(Path(str(summary_path)).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    history_entry = data.get("history_entry") if isinstance(data.get("history_entry"), dict) else {}
    return {
        key: history_entry.get(key)
        for key in (
            "summary_label",
            "brief",
            "main_stimulus",
            "training_load",
            "quality_notes",
            "achievement",
            "limiter",
            "next_session_advice",
        )
        if history_entry.get(key) is not None
    }


def _current_fit_path(context: AgentContext) -> Path:
    if not context.current_fit_file:
        raise ValueError("current_fit_file is required")
    return Path(context.current_fit_file).expanduser()


def _fit_paths_from_items(items: list[Any]) -> list[Path]:
    paths: list[Path] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for path in item.get("paths") or []:
            paths.append(Path(str(path)).expanduser())
    return paths


def _compact_range_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_index": activity.get("activity_index"),
        "activity_key": activity.get("activity_key"),
        "file_name": activity.get("file_name"),
        "start_time_local": activity.get("start_time_local"),
        "date_local": activity.get("date_local"),
        "sport_type": activity.get("sport_type"),
        "duration_min": activity.get("duration_min"),
        "distance_km": activity.get("distance_km"),
        "has_summary": activity.get("has_summary"),
        "summary_label": activity.get("summary_label"),
        "main_stimulus": activity.get("main_stimulus"),
        "training_load": activity.get("training_load"),
    }


def _format_range_summary_answer(summary: dict[str, Any]) -> str:
    scope = summary.get("scope") if isinstance(summary.get("scope"), dict) else {}
    title = _range_title(scope)
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    lines = [
        f"{title}找到 {summary.get('count')} 条已索引活动。",
        f"总量: {totals.get('distance_km', 0)} km, {totals.get('duration_min', 0)} 分钟。",
    ]
    for activity in summary.get("activities") or []:
        label = activity.get("summary_label") or activity.get("file_name") or activity.get("activity_key")
        lines.append(
            f"- #{activity.get('activity_index') or '?'} "
            f"{activity.get('start_time_local') or activity.get('date_local') or '未知时间'}: "
            f"{label}, {activity.get('distance_km') or 0} km / {activity.get('duration_min') or 0} 分钟"
        )
    return "\n".join(lines)


def _empty_range_answer(scope: dict[str, Any]) -> str:
    return f"{_range_title(scope)}没有找到已索引的活动。你可以先重建索引，或同步 Garmin 活动后再试。"


def _range_title(scope: dict[str, Any]) -> str:
    start = scope.get("start_date")
    end = scope.get("end_date")
    if start and end:
        return f"{start} 到 {end} "
    return ""
