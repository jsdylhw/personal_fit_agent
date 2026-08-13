"""Garmin 同步操作适配器。"""

from __future__ import annotations

from typing import Any

from operations.activity.service import sync_garmin_activities_tool


def sync_recent(*, count: int = 5) -> dict[str, Any]:
    """同步并索引最近活动，返回稳定的结构化结果。"""
    try:
        result = sync_garmin_activities_tool(count=count)
    except Exception as exc:
        return {
            "schema_version": "activity_operation_garmin_sync.v1",
            "operation": "sync_recent",
            "status": "failed",
            "error": type(exc).__name__,
            "message": str(exc),
            "activities": [],
        }

    failed = int(result.get("failed") or 0)
    return {
        "schema_version": "activity_operation_garmin_sync.v1",
        "operation": "sync_recent",
        "status": "partial" if failed else "completed",
        "activities": result.get("indexed_items") or [],
        "downloaded": int(result.get("downloaded") or 0),
        "skipped": int(result.get("skipped") or 0),
        "failed": failed,
        "failed_items": result.get("failed_items") or [],
        "raw_result": result,
    }
