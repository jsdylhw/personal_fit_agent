"""训练活动历史存储与查询.

使用 JSONL 文件存储,每行一条活动记录.适合几十到几百条规模,
超出后建议切到 SQLite.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_dirs

DEFAULT_HISTORY_PATH = Path("data") / "activity_history.jsonl"


def history_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    ensure_data_dirs()
    return DEFAULT_HISTORY_PATH


def load_activity_history(path: str | Path | None = None) -> list[dict[str, Any]]:
    """加载全部历史活动,按 start_time 排序.

    Args:
        path: JSONL 文件路径,默认 data/activity_history.jsonl.

    Returns:
        list[dict]: 按时间升序排列的活动记录.文件不存在返回 [].
    """
    target = history_path(path)
    if not target.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return sorted(rows, key=lambda row: row.get("start_time") or "")


def save_activity_history(rows: list[dict[str, Any]], path: str | Path | None = None) -> Path:
    """全量覆写历史文件.

    Args:
        rows: 要保存的活动记录列表.
        path: 目标文件路径.

    Returns:
        Path: 写入的文件路径.
    """
    target = history_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: row.get("start_time") or "")
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    target.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return target


def upsert_activity_history(entry: dict[str, Any], path: str | Path | None = None) -> Path:
    """按 activity_key 或 file_path 去重后插入/更新历史.

    Args:
        entry: 要 upsert 的活动记录.
        path: 目标文件路径.

    Returns:
        Path: 写入的文件路径.
    """
    rows = load_activity_history(path)
    activity_key = entry.get("activity_key")
    file_path = entry.get("file_path")
    updated: list[dict[str, Any]] = []
    replaced = False

    for row in rows:
        same_key = activity_key and row.get("activity_key") == activity_key
        same_file = file_path and row.get("file_path") == file_path
        if same_key or same_file:
            if not replaced:
                updated.append(entry)
                replaced = True
            continue
        updated.append(row)

    if not replaced:
        updated.append(entry)
    return save_activity_history(updated, path)


def query_activity_history(
    *,
    before: str | None = None,
    days: int | None = None,
    limit: int = 20,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """按时间窗口查询历史活动.

    Args:
        before: 截止时间(ISO 格式),不含该时间之后的活动.
        days: 往回查的天数(配合 before 使用).
        limit: 最多返回条数.
        path: 历史文件路径.

    Returns:
        dict: {schema_version, before, days, limit, count, activities}
    """
    rows = load_activity_history(path)
    before_dt = _parse_datetime(before) if before else None
    after_dt = before_dt - timedelta(days=int(days)) if before_dt and days else None

    filtered: list[dict[str, Any]] = []
    for row in rows:
        start_dt = _parse_datetime(row.get("start_time"))
        if before_dt and start_dt and start_dt >= before_dt:
            continue
        if after_dt and start_dt and start_dt < after_dt:
            continue
        filtered.append(row)

    filtered = filtered[-int(limit) :] if limit else filtered
    return {
        "schema_version": "file_training_history.v1",
        "before": before,
        "days": days,
        "limit": limit,
        "count": len(filtered),
        "activities": filtered,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
