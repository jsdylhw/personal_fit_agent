"""本地活动索引:维护 FIT 文件和 summary 的可发现目录.

activity_index.json 的职责是回答"有哪些活动,日期是什么,文件在哪".
它不是训练分析报告本身,而是 agent 解析"分析 4 月 1 日活动/这一周活动"的
活动目录.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.config import ensure_data_dirs
from core.path_utils import project_relative_or_absolute
from core.stats import _meters_to_km, _round_float, _seconds_to_minutes, prune_empty_values
from core.time_utils import local_time_without_timezone
from fit.parser import parse_fit

DEFAULT_ACTIVITY_INDEX_PATH = Path("data") / "activity_index.json"


def activity_index_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    ensure_data_dirs()
    return DEFAULT_ACTIVITY_INDEX_PATH


def load_activity_index(path: str | Path | None = None) -> dict[str, Any]:
    target = activity_index_path(path)
    if not target.exists():
        return _empty_index()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(data, dict):
        return _empty_index()
    activities = data.get("activities")
    if not isinstance(activities, list):
        data["activities"] = []
    data.setdefault("schema_version", "activity_index.v1")
    return data


def save_activity_index(index: dict[str, Any], path: str | Path | None = None) -> Path:
    target = activity_index_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = index.get("activities") if isinstance(index.get("activities"), list) else []
    rows = _with_activity_indices(rows)
    data = {
        "schema_version": "activity_index.v1",
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "activities": rows,
    }
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target


def upsert_activity_from_fit(
    fit_path: str | Path,
    *,
    source: str = "manual",
    source_activity_id: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """解析 FIT 并写入/更新活动索引."""
    fit = Path(fit_path).expanduser().resolve()
    parsed = parse_fit(fit)
    summary = parsed.get("summary") or {}
    entry = _entry_from_fit_summary(
        fit,
        summary,
        source=source,
        source_activity_id=source_activity_id,
    )
    return upsert_activity_entry(entry, path=path)


def upsert_activity_from_summary(summary_path: str | Path, *, path: str | Path | None = None) -> dict[str, Any]:
    """从 data/summaries/*.summary.json 补全索引信息."""
    summary_file = Path(summary_path).expanduser().resolve()
    data = json.loads(summary_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"summary must be object: {summary_file}")

    fit_path = Path(str(data.get("fit_path") or "")).expanduser()
    fit_summary = data.get("fit_summary") if isinstance(data.get("fit_summary"), dict) else {}
    entry = _entry_from_fit_summary(
        fit_path.resolve() if fit_path.exists() else fit_path,
        fit_summary,
        source=str(data.get("source") or "manual"),
        source_activity_id=data.get("source_activity_id"),
        activity_key=data.get("activity_key"),
    )
    entry.update({
        "summary_path": project_relative_or_absolute(summary_file),
        "has_summary": True,
        "has_strava_summary": bool(data.get("strava_summary")),
        "strava_activity_id": data.get("strava_activity_id"),
        "status": data.get("status"),
        "summary_label": (data.get("history_entry") or {}).get("summary_label") if isinstance(data.get("history_entry"), dict) else None,
        "main_stimulus": (data.get("history_entry") or {}).get("main_stimulus") if isinstance(data.get("history_entry"), dict) else None,
        "training_load": (data.get("history_entry") or {}).get("training_load") if isinstance(data.get("history_entry"), dict) else None,
    })
    return upsert_activity_entry(entry, path=path)


def upsert_activity_entry(entry: dict[str, Any], *, path: str | Path | None = None) -> dict[str, Any]:
    index = load_activity_index(path)
    rows = index.get("activities") or []
    merged_rows: list[dict[str, Any]] = []
    replaced = False
    for row in rows:
        if _same_activity(row, entry):
            merged_rows.append(prune_empty_values({**row, **entry}))
            replaced = True
        else:
            merged_rows.append(row)
    if not replaced:
        merged_rows.append(prune_empty_values(entry))
    index["activities"] = merged_rows
    save_activity_index(index, path)
    return prune_empty_values(entry)


def rebuild_activity_index(
    roots: list[str | Path] | None = None,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """扫描本地 FIT 和 summary,重建活动索引."""
    target = activity_index_path(path)
    index = _empty_index()
    save_activity_index(index, target)

    for fit in _iter_fit_files(roots):
        try:
            upsert_activity_from_fit(fit, path=target)
        except Exception:
            continue

    for summary in sorted((Path("data") / "summaries").glob("*.summary.json")):
        try:
            upsert_activity_from_summary(summary, path=target)
        except Exception:
            continue

    return load_activity_index(target)


def list_activities(
    *,
    limit: int = 20,
    sport_type: str | None = None,
    order: str = "latest",
    path: str | Path | None = None,
) -> dict[str, Any]:
    rows = _filter_rows(load_activity_index(path).get("activities") or [], sport_type=sport_type)
    order_key = _activity_order_key(order)
    if order_key == "earliest":
        rows = rows[: max(1, int(limit))] if limit else rows
    else:
        rows = rows[-max(1, int(limit)) :] if limit else rows
        rows = list(reversed(rows))
    return {
        "schema_version": "activity_list.v1",
        "count": len(rows),
        "order": order_key,
        "activities": [_compact_activity(row) for row in rows],
    }


def resolve_activity(
    *,
    activity_key: str | None = None,
    activity_index: int | str | None = None,
    date_local: str | None = None,
    name: str | None = None,
    sport_type: str | None = None,
    match: str = "latest",
    path: str | Path | None = None,
) -> dict[str, Any]:
    rows = load_activity_index(path).get("activities") or []
    rows = _filter_rows(rows, sport_type=sport_type)
    if activity_key:
        rows = [row for row in rows if str(row.get("activity_key")) == str(activity_key)]
    if activity_index is not None:
        try:
            wanted_index = int(activity_index)
        except (TypeError, ValueError):
            rows = []
        else:
            rows = [row for row in rows if row.get("activity_index") == wanted_index]
    if date_local:
        rows = [row for row in rows if row.get("date_local") == date_local]
    if name:
        needle = _normalize_text(name)
        rows = [
            row for row in rows
            if needle in _normalize_text(row.get("file_name") or "")
            or needle in _normalize_text(Path(str(row.get("fit_path") or "")).stem)
        ]

    if not rows:
        return {"schema_version": "activity_resolve.v1", "matched_count": 0, "activity": None, "candidates": []}

    chosen = rows[0] if _activity_order_key(match) == "earliest" else rows[-1]
    return {
        "schema_version": "activity_resolve.v1",
        "matched_count": len(rows),
        "activity": _compact_activity(chosen),
        "candidates": [_compact_activity(row) for row in rows[-10:]],
    }


def get_activities_in_range(
    *,
    start_date: str,
    end_date: str,
    sport_type: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    rows = load_activity_index(path).get("activities") or []
    rows = _filter_rows(rows, sport_type=sport_type)
    rows = [
        row for row in rows
        if row.get("date_local") and start_date <= str(row.get("date_local")) <= end_date
    ]
    total_duration_s = sum(float(row.get("duration_s") or 0) for row in rows)
    total_distance_m = sum(float(row.get("distance_m") or 0) for row in rows)
    return {
        "schema_version": "activity_range.v1",
        "start_date": start_date,
        "end_date": end_date,
        "sport_type": sport_type,
        "count": len(rows),
        "totals": {
            "duration_min": _seconds_to_minutes(total_duration_s),
            "distance_km": _meters_to_km(total_distance_m),
        },
        "activities": [_compact_activity(row) for row in rows],
    }


def _entry_from_fit_summary(
    fit_path: Path,
    summary: dict[str, Any],
    *,
    source: str,
    source_activity_id: str | None,
    activity_key: str | None = None,
) -> dict[str, Any]:
    start_local = local_time_without_timezone(summary.get("start_time_local") or summary.get("start_time"))
    key = activity_key or (_activity_key(fit_path) if fit_path.exists() else None)
    summary_path = Path("data") / "summaries" / f"{fit_path.stem}.summary.json"
    return prune_empty_values({
        "activity_key": key,
        "fit_path": project_relative_or_absolute(fit_path),
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "file_name": fit_path.name,
        "sport_type": summary.get("sport_type"),
        "sub_sport": summary.get("sub_sport"),
        "start_time_local": start_local,
        "date_local": _date_part(start_local),
        "duration_s": _round_float(summary.get("duration_s"), 3),
        "distance_m": _round_float(summary.get("distance_m"), 1),
        "duration_min": _seconds_to_minutes(summary.get("duration_s")),
        "distance_km": _meters_to_km(summary.get("distance_m")),
        "source": source,
        "source_activity_id": source_activity_id,
        "has_summary": summary_path.exists(),
        "has_strava_summary": False,
    })


def _compact_activity(row: dict[str, Any]) -> dict[str, Any]:
    return prune_empty_values({
        "activity_key": row.get("activity_key"),
        "activity_index": row.get("activity_index"),
        "file_name": row.get("file_name"),
        "fit_path": row.get("fit_path"),
        "summary_path": row.get("summary_path"),
        "sport_type": row.get("sport_type"),
        "sub_sport": row.get("sub_sport"),
        "start_time_local": row.get("start_time_local"),
        "date_local": row.get("date_local"),
        "duration_min": row.get("duration_min") or _seconds_to_minutes(row.get("duration_s")),
        "distance_km": row.get("distance_km") or _meters_to_km(row.get("distance_m")),
        "source": row.get("source"),
        "has_summary": row.get("has_summary"),
        "has_strava_summary": row.get("has_strava_summary"),
        "strava_activity_id": row.get("strava_activity_id"),
        "summary_label": row.get("summary_label"),
        "main_stimulus": row.get("main_stimulus"),
        "training_load": row.get("training_load"),
    })


def _iter_fit_files(roots: list[str | Path] | None = None) -> list[Path]:
    scan_roots = [Path(root) for root in roots] if roots else [
        Path("data") / "fit",
        Path("garmin_cn_fit_files"),
        Path.cwd(),
    ]
    files: list[Path] = []
    for root in scan_roots:
        if root.exists():
            files.extend(path for path in root.glob("*.fit") if path.is_file())
    return sorted(set(path.resolve() for path in files))


def _same_activity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("activity_key") and right.get("activity_key"):
        return left.get("activity_key") == right.get("activity_key")
    if left.get("fit_path") and right.get("fit_path"):
        return left.get("fit_path") == right.get("fit_path")
    return False


def _filter_rows(rows: list[dict[str, Any]], *, sport_type: str | None = None) -> list[dict[str, Any]]:
    indexed_rows = _with_activity_indices(rows)
    filtered = indexed_rows
    if sport_type:
        filtered = [row for row in filtered if row.get("sport_type") == sport_type]
    return sorted(filtered, key=lambda row: row.get("start_time_local") or "")


def _with_activity_indices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda row: (row.get("start_time_local") or "", row.get("file_name") or ""))
    # 只保存一个按时间正序的序号:最早为 1,最后一个就是最大序号.
    return [
        {
            **row,
            "activity_index": index,
        }
        for index, row in enumerate(sorted_rows, start=1)
    ]


def _activity_order_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"earliest", "oldest", "first", "chronological", "asc", "ascending"}:
        return "earliest"
    return "latest"


def _activity_key(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _date_part(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _normalize_text(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def _empty_index() -> dict[str, Any]:
    return {
        "schema_version": "activity_index.v1",
        "updated_at": None,
        "activities": [],
    }
