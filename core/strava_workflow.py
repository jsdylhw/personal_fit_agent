"""Strava 上传工作流:从 summary JSON 读取分析结果,上传 FIT 并写描述.

依赖 sinks/strava.py 的 StravaSink 做实际的 API 调用.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sinks.strava import StravaSink


def upload_summary_to_strava(
    summary_path: str | Path, *, title: str | None = None, wait: bool = True,
) -> dict[str, Any]:
    """从 summary JSON 读取 strava_summary 和 fit_path,上传到 Strava.

    Args:
        summary_path: data/summaries/*.summary.json 路径.
        title: 自定义活动标题,默认用日期+运动类型.
        wait: 是否轮询等待 Strava 处理完成.

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
    return StravaSink().update_description(activity_id, strava_summary)


def _default_title(fit_summary: dict[str, Any], fit_path: Path) -> str:
    start_time = str(fit_summary.get("start_time_local") or fit_summary.get("start_time") or "")[:10]
    sport = fit_summary.get("sport_type") or "activity"
    if start_time:
        return f"{start_time} {sport}"
    return fit_path.stem
