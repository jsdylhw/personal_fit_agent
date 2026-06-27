"""业务操作工具:下载 / 分析 / 上传.

这些是 CLI / tool runtime 直接调用的 Python 函数,不是 LLM 工具定义。
FIT 数据查询工具的 ToolDef 定义和路由在 fit_query.py。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

MAX_SYNC_COUNT = 20


def sync_garmin_activities_tool(count: int = 5) -> dict[str, Any]:
    """从 Garmin 中国区下载最近 N 条活动的 FIT 文件,自动跳过已下载的。

    Args:
        count: 下载最近几条活动 [1, 20],默认 5。

    Returns:
        dict: {fit_dir, total, downloaded, skipped, downloaded_items, skipped_items}
    """
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0 or count > MAX_SYNC_COUNT:
        raise ValueError(f"count must be an integer between 1 and {MAX_SYNC_COUNT}")

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
    indexed: list[dict[str, Any]] = []
    index_errors: list[dict[str, Any]] = []

    for activity in activities:
        activity_id = activity.get("activityId")
        existing = existing_fit_paths(output_dir, activity)
        if existing:
            _index_fit_paths(existing, activity_id=activity_id, indexed=indexed, errors=index_errors)
            skipped.append({
                "activity_id": activity_id,
                "name": activity.get("activityName"),
                "start_time": activity.get("startTimeLocal"),
                "paths": [str(p) for p in existing],
            })
            continue

        raw_bytes = downloader.download_original(activity_id)
        saved = save_original_as_fit(raw_bytes, output_dir, activity)
        _index_fit_paths(saved, activity_id=activity_id, indexed=indexed, errors=index_errors)
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
        "indexed": len(indexed),
        "indexed_items": indexed,
        "index_errors": index_errors,
    }


def _index_fit_paths(
    paths: list[Path],
    *,
    activity_id: Any,
    indexed: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    from core.activity_index import upsert_activity_from_fit

    for path in paths:
        try:
            entry = upsert_activity_from_fit(
                path,
                source="garmin_cn",
                source_activity_id=str(activity_id) if activity_id is not None else None,
            )
        except Exception as exc:
            errors.append({
                "path": str(path),
                "activity_id": activity_id,
                "error": type(exc).__name__,
                "message": str(exc),
            })
            continue
        indexed.append({
            "path": str(path),
            "activity_id": activity_id,
            "activity_key": entry.get("activity_key"),
            "sport_type": entry.get("sport_type"),
            "start_time_local": entry.get("start_time_local"),
        })


def analyze_fit_file_tool(fit_path: str, *, force: bool = False) -> dict[str, Any]:
    """对指定 FIT 文件运行本地 LLM 分析(hidden tool loop),返回精简摘要。

    Args:
        fit_path: .fit 文件路径。
        force: 强制重新分析(即使已有缓存)。

    Returns:
        dict: 精简活动元数据 + summary_path/markdown_report,供 workflow 直接展示报告.
    """
    from core.file_workflow import analyze_fit_file

    result = analyze_fit_file(fit_path, use_history=True, force=force)
    fit_summary = result.get("fit_summary") or {}
    from core.stats import _meters_to_km, _seconds_to_minutes

    return {
        "activity_key": result.get("activity_key"),
        "fit_path": result.get("fit_path"),
        "summary_path": result.get("summary_path"),
        "sport_type": fit_summary.get("sport_type"),
        "start_time_local": fit_summary.get("start_time_local"),
        "duration_min": _seconds_to_minutes(fit_summary.get("duration_s")),
        "distance_km": _meters_to_km(fit_summary.get("distance_m")),
        "markdown_report": result.get("markdown_report"),
        "strava_summary": result.get("strava_summary"),
        "history_entry": result.get("history_entry") if isinstance(result.get("history_entry"), dict) else {},
        "model": result.get("model"),
        "status": result.get("status"),
    }


def upload_to_strava_tool(fit_path: str, *, confirmed: bool = False, force: bool = False) -> dict[str, Any]:
    """上传 FIT 文件到 Strava 并写入描述。需要两次调用:第一次预览,第二次 confirmed=true 执行。

    Args:
        fit_path: .fit 文件路径。
        confirmed: 是否确认执行上传。只接受 Python True,不接受字符串。
        force: 遇到重复活动时改为更新已有活动的描述。

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
    pending_activity = _pending_strava_activity_info(path, summary, summary_path)

    # 防御层:即使调用方绕过路由直接传字符串,也不会误触发上传
    confirmed = _parse_strict_bool(confirmed)
    if not confirmed:
        return {
            "action_required": "confirm_upload",
            "fit_path": str(path),
            "preview": strava_summary[:120],
            "message": "Are you sure you want to upload to Strava? Call again with confirmed=true to execute.",
        }

    from core.strava_workflow import upload_summary_to_strava

    try:
        result = upload_summary_to_strava(str(summary_path), wait=True, force=force)
    except requests.RequestException as exc:
        return {
            "error": "network_error",
            "message": f"Strava network request failed: {exc}",
            "pending_activity": pending_activity,
        }
    except TimeoutError as exc:
        return {
            "error": "network_error",
            "message": f"Strava upload timed out: {exc}",
            "pending_activity": pending_activity,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "error": "upload_failed",
            "message": str(exc),
            "pending_activity": pending_activity,
        }
    if result.get("status") == "duplicate":
        existing_activity = _existing_strava_activity_info(result.get("strava_activity_id"))
        return {
            "status": "duplicate",
            "strava_activity_id": result.get("strava_activity_id"),
            "existing_activity": existing_activity,
            "pending_activity": pending_activity,
            "message": result.get("message"),
        }
    if result.get("status") == "description_updated":
        existing_activity = _existing_strava_activity_info(result.get("strava_activity_id"))
        return {
            "status": "description_updated",
            "strava_activity_id": result.get("strava_activity_id"),
            "existing_activity": existing_activity,
            "pending_activity": pending_activity,
            "message": f"已更新 Strava 活动 {result.get('strava_activity_id')} 的描述。",
        }
    upload_status = result.get("upload_status") or {}
    activity_id = upload_status.get("activity_id")
    if not activity_id:
        return {"error": "upload_processing_failed", "status": result}
    return {
        "status": "uploaded",
        "strava_activity_id": activity_id,
        "pending_activity": pending_activity,
        "title": result.get("title"),
        "strava_summary_snippet": str(result.get("description", ""))[:120],
    }


def _pending_strava_activity_info(path: Path, summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    fit_summary = summary.get("fit_summary") if isinstance(summary.get("fit_summary"), dict) else {}
    return {
        "activity_key": summary.get("activity_key"),
        "fit_path": str(path),
        "summary_path": str(summary_path),
        "sport_type": fit_summary.get("sport_type"),
        "start_time_local": fit_summary.get("start_time_local") or fit_summary.get("start_time"),
        "title": _default_upload_title(fit_summary, path),
        "strava_summary_snippet": str(summary.get("strava_summary") or "")[:120],
    }


def _existing_strava_activity_info(activity_id: Any) -> dict[str, Any]:
    activity_id_text = str(activity_id or "")
    return {
        "strava_activity_id": activity_id_text or None,
        "url": f"https://www.strava.com/activities/{activity_id_text}" if activity_id_text else None,
    }


def _default_upload_title(fit_summary: dict[str, Any], fit_path: Path) -> str:
    start = str(fit_summary.get("start_time_local") or fit_summary.get("start_time") or "")[:10]
    sport = fit_summary.get("sport_type") or "activity"
    return f"{start} {sport}" if start else fit_path.stem


def _parse_strict_bool(value: Any, default: bool = False) -> bool:
    """严格解析布尔值:只接受 Python True/False,不接受字符串。

    LLM 返回 JSON 时 bool 是原生 true/false,不会被误解析。
    """
    if value is True:
        return True
    if value is False:
        return False
    return default
