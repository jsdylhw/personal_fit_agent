"""Agent 模式工作流工具:下载 / 分析 / 上传.

这些工具有副作用(网络 I/O,写文件,上传 Strava),只在 agent 模式暴露,
不会出现在 analyze-file 的 hidden tool loop 中.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_SYNC_COUNT = 20


def sync_garmin_activities_tool(count: int = 5) -> dict[str, Any]:
    """从 Garmin 中国区下载最近 N 条活动的 FIT 文件,自动跳过已下载的。

    Args:
        count: 下载最近几条活动 [1, 20],默认 5。

    Returns:
        dict: {fit_dir, total, downloaded, skipped, downloaded_items, skipped_items}
    """
    count = max(1, min(int(count), MAX_SYNC_COUNT))

    from core.config import cfg_get, load_config
    from core.garmin_cn import (
        DEFAULT_OUTPUT_DIR,
        build_downloader,
        existing_fit_paths,
        save_original_as_fit,
    )

    config = load_config()
    output_dir = Path(cfg_get(config, "output_dir", DEFAULT_OUTPUT_DIR))
    downloader = build_downloader(config)
    downloader.login()
    activities = downloader.list_activities(count)

    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for activity in activities:
        activity_id = activity.get("activityId")
        existing = existing_fit_paths(output_dir, activity)
        if existing:
            skipped.append({
                "activity_id": activity_id,
                "name": activity.get("activityName"),
                "start_time": activity.get("startTimeLocal"),
                "paths": [str(p) for p in existing],
            })
            continue

        raw_bytes = downloader.download_original(activity_id)
        saved = save_original_as_fit(raw_bytes, output_dir, activity)
        downloaded.append({
            "activity_id": activity_id,
            "name": activity.get("activityName"),
            "start_time": activity.get("startTimeLocal"),
            "paths": [str(p) for p in saved],
        })

    return {
        "fit_dir": str(output_dir),
        "total": len(activities),
        "downloaded": len(downloaded),
        "skipped": len(skipped),
        "downloaded_items": downloaded,
        "skipped_items": skipped,
    }


def analyze_fit_file_tool(fit_path: str, *, force: bool = False) -> dict[str, Any]:
    """对指定 FIT 文件运行本地 LLM 分析(hidden tool loop),返回精简摘要。

    Args:
        fit_path: .fit 文件路径。
        force: 强制重新分析(即使已有缓存)。

    Returns:
        dict: {activity_key, fit_path, sport_type, duration_min, distance_km,
               strava_summary, model, status}
    """
    from core.file_workflow import analyze_fit_file

    result = analyze_fit_file(fit_path, use_history=True, force=force)
    fit_summary = result.get("fit_summary") or {}
    from core.stats import _meters_to_km, _seconds_to_minutes

    return {
        "activity_key": result.get("activity_key"),
        "fit_path": result.get("fit_path"),
        "sport_type": fit_summary.get("sport_type"),
        "start_time_local": fit_summary.get("start_time_local"),
        "duration_min": _seconds_to_minutes(fit_summary.get("duration_s")),
        "distance_km": _meters_to_km(fit_summary.get("distance_m")),
        "strava_summary": result.get("strava_summary"),
        "model": result.get("model"),
        "status": result.get("status"),
    }


def upload_to_strava_tool(fit_path: str, *, confirmed: bool = False) -> dict[str, Any]:
    """上传 FIT 文件到 Strava 并写入描述。需要两次调用:第一次预览,第二次 confirmed=true 执行。

    Args:
        fit_path: .fit 文件路径。
        confirmed: 是否确认执行上传。只接受 Python True,不接受字符串。

    Returns:
        dict: 第一次返回 {action_required, preview},执行成功返回 {status, strava_activity_id}。
    """
    path = Path(fit_path)
    summary_path = Path("data/summaries") / f"{path.stem}.summary.json"

    if not summary_path.exists():
        return {"error": "no_summary", "message": f"Please analyze the activity first: {fit_path}"}

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    strava_summary = summary.get("strava_summary")
    if not strava_summary:
        return {"error": "no_strava_summary", "message": "Summary does not contain strava_summary"}

    # 防御层:即使调用方绕过路由直接传字符串,也不会误触发上传
    confirmed = _parse_strict_bool(confirmed)
    if not confirmed:
        return {
            "action_required": "confirm_upload",
            "fit_path": str(path),
            "preview": strava_summary[:120],
            "message": "Are you sure you want to upload to Strava? Call again with confirmed=true to execute.",
        }

    from sinks.strava import StravaSink

    fit_summary = summary.get("fit_summary") or {}
    sport = fit_summary.get("sport_type") or "activity"
    start = str(fit_summary.get("start_time_local") or fit_summary.get("start_time") or "")[:10]
    title = f"{start} {sport}" if start else path.stem

    sink = StravaSink()
    upload = sink.upload_fit(
        str(path), title=title, description=strava_summary,
        external_id=summary.get("activity_key"),
    )
    upload_id = upload.get("id")
    if not upload_id:
        return {"error": "upload_failed", "message": "Strava did not return an upload ID", "raw": upload}

    status = sink.wait_for_upload(upload_id)
    activity_id = status.get("activity_id") if status else None
    if not activity_id:
        return {"error": "upload_processing_failed", "upload_id": upload_id, "status": status}

    return {
        "status": "uploaded",
        "strava_activity_id": activity_id,
        "upload_id": upload_id,
        "title": title,
        "strava_summary_snippet": strava_summary[:120],
    }


def _parse_strict_bool(value: Any, default: bool = False) -> bool:
    """严格解析布尔值:只接受 Python True/False,不接受字符串。

    LLM 返回 JSON 时 bool 是原生 true/false,不会被误解析。
    """
    if value is True:
        return True
    if value is False:
        return False
    return default
