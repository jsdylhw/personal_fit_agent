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
    target = history_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: row.get("start_time") or "")
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    target.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return target


def upsert_activity_history(entry: dict[str, Any], path: str | Path | None = None) -> Path:
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
