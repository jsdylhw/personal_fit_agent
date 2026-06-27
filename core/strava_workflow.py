"""Strava 上传工作流:从 summary JSON 读取分析结果,上传 FIT 并写描述.

依赖 sinks/strava.py 的 StravaSink 做实际的 API 调用.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.activity_index import upsert_activity_from_summary
from sinks.strava import StravaSink


def upload_summary_to_strava(
    summary_path: str | Path, *, title: str | None = None, wait: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """从 summary JSON 读取 strava_summary 和 fit_path,上传到 Strava.

    Args:
        summary_path: data/summaries/*.summary.json 路径.
        title: 自定义活动标题,默认用日期+运动类型.
        wait: 是否轮询等待 Strava 处理完成.
        force: 遇到 duplicate 时不报错,改为更新已有活动的描述.

    Returns:
        dict: {summary_path, fit_path, title, description, upload, upload_status?}
    """
    path = Path(summary_path)
    if not path.exists():
        raise FileNotFoundError(path)
    summary = json.loads(path.read_text(encoding="utf-8"))

    fit_path = summary.get("fit_path")
    if not fit_path:
        raise RuntimeError(f"summary does not contain fit_path: {path}")
    strava_summary = summary.get("strava_summary")
    if not strava_summary:
        raise RuntimeError(f"summary does not contain strava_summary: {path}")

    fit_summary = summary.get("fit_summary") or {}
    upload_title = title or _default_title(fit_summary, Path(fit_path))
    sink = StravaSink()

    known_activity_id = _known_strava_activity_id(summary)
    if force and known_activity_id:
        updated = sink.update_description(known_activity_id, strava_summary)
        _remember_strava_activity_id(path, summary, known_activity_id)
        return {
            "summary_path": str(path),
            "fit_path": fit_path,
            "status": "description_updated",
            "strava_activity_id": known_activity_id,
            "update_result": updated,
            "message": f"已更新 Strava 活动 {known_activity_id} 的描述。",
        }

    upload = sink.upload_fit(
        fit_path, title=upload_title, description=strava_summary,
        external_id=summary.get("activity_key"),
    )

    result: dict[str, Any] = {
        "summary_path": str(path), "fit_path": fit_path,
        "title": upload_title, "description": strava_summary, "upload": upload,
    }
    upload_id = upload.get("id")
    if wait and upload_id is not None:
        result["upload_status"] = sink.wait_for_upload(upload_id)
    elif not wait and upload_id is None:
        # upload_fit 直接返回了错误(如 duplicate)
        result["upload_status"] = upload

    # 处理 duplicate 错误:提取已有活动 ID,根据 force 决定报错还是更新描述
    duplicate_id = _parse_duplicate_activity_id(result.get("upload_status") or {})
    if duplicate_id:
        _remember_strava_activity_id(path, summary, duplicate_id)
        if force:
            updated = sink.update_description(duplicate_id, strava_summary)
            result["status"] = "description_updated"
            result["strava_activity_id"] = duplicate_id
            result["update_result"] = updated
            result.pop("upload_status", None)
        else:
            return {
                "summary_path": str(path),
                "fit_path": fit_path,
                "status": "duplicate",
                "strava_activity_id": duplicate_id,
                "message": f"该活动已上传到 Strava (activity_id={duplicate_id})。使用 --force 更新描述,或手动调用 update-strava-description。",
            }

    uploaded_activity_id = (result.get("upload_status") or {}).get("activity_id")
    if uploaded_activity_id:
        _remember_strava_activity_id(path, summary, str(uploaded_activity_id))
    return result


def update_strava_description_from_summary(
    activity_id: str, summary_path: str | Path,
) -> dict[str, Any]:
    """仅更新已上传活动的描述,不上传 FIT.

    Args:
        activity_id: Strava 活动 ID.
        summary_path: summary JSON 路径.

    Returns:
        dict: Strava API 响应.
    """
    path = Path(summary_path)
    if not path.exists():
        raise FileNotFoundError(path)
    summary = json.loads(path.read_text(encoding="utf-8"))
    strava_summary = summary.get("strava_summary")
    if not strava_summary:
        raise RuntimeError(f"summary does not contain strava_summary: {path}")
    result = StravaSink().update_description(activity_id, strava_summary)
    _remember_strava_activity_id(path, summary, str(activity_id))
    return result


def _known_strava_activity_id(summary: dict[str, Any]) -> str | None:
    value = summary.get("strava_activity_id")
    if value:
        return str(value)
    upload_status = summary.get("strava_upload_status")
    if isinstance(upload_status, dict) and upload_status.get("activity_id"):
        return str(upload_status["activity_id"])
    return None


def _remember_strava_activity_id(summary_path: Path, summary: dict[str, Any], activity_id: str) -> None:
    """把 Strava 活动 ID 写回 summary,并刷新 activity_index 中的同一行."""
    if not activity_id:
        return
    updated = dict(summary)
    updated["strava_activity_id"] = str(activity_id)
    if summary.get("strava_activity_id") != str(activity_id):
        summary_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    try:
        upsert_activity_from_summary(summary_path)
    except Exception:
        # summary 是主缓存;index 刷新失败不应影响上传/更新描述主流程.
        pass


def _parse_duplicate_activity_id(status: dict[str, Any]) -> str | None:
    """从 Strava upload status 的 error 字段提取已有活动 ID.

    Strava duplicate 错误格式:
      "xxx.fit duplicate of <a href='/activities/18619000064' ...>Title</a>"
    """
    import re
    error = status.get("error")
    if not isinstance(error, str):
        return None
    match = re.search(r"/activities/(\d+)", error)
    return match.group(1) if match else None


def _default_title(fit_summary: dict[str, Any], fit_path: Path) -> str:
    start_time = str(fit_summary.get("start_time_local") or fit_summary.get("start_time") or "")[:10]
    sport = fit_summary.get("sport_type") or "activity"
    if start_time:
        return f"{start_time} {sport}"
    return fit_path.stem
