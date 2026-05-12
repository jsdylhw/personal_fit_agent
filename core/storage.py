import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_dirs, get_data_dir


def db_path(data_dir: Path | None = None) -> Path:
    return (data_dir or get_data_dir()) / "state.sqlite"


def connect_db(data_dir: Path | None = None) -> sqlite3.Connection:
    paths = ensure_data_dirs(data_dir)
    con = sqlite3.connect(paths["root"] / "state.sqlite")
    con.row_factory = sqlite3.Row
    init_db(con)
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_activity_id TEXT,
            fit_path TEXT NOT NULL,
            fit_sha256 TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            sport_type TEXT,
            start_time TEXT,
            duration_s REAL,
            distance_m REAL,
            summary_json TEXT,
            analysis_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            model TEXT,
            prompt_version TEXT,
            summary_json TEXT,
            markdown TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(activity_id) REFERENCES activities(id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS athlete_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT,
            weight_kg REAL,
            ftp REAL,
            resting_hr REAL,
            max_hr REAL,
            goals_json TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    con.commit()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_fit(path: str | Path, source: str = "manual", data_dir: Path | None = None) -> dict[str, Any]:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    if src.suffix.lower() != ".fit":
        raise ValueError(f"只支持 .fit 文件: {src}")

    paths = ensure_data_dirs(data_dir)
    digest = sha256_file(src)
    target = paths["fit"] / f"{digest[:12]}_{src.name}"
    if not target.exists():
        shutil.copy2(src, target)

    now = datetime.now(timezone.utc).isoformat()
    con = connect_db(data_dir)
    existing = con.execute(
        "SELECT * FROM activities WHERE fit_sha256 = ?",
        (digest,),
    ).fetchone()
    if existing:
        return dict(existing)

    con.execute(
        """
        INSERT INTO activities (
            source, fit_path, fit_sha256, file_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source, str(target), digest, src.name, now, now),
    )
    con.commit()
    row = con.execute("SELECT * FROM activities WHERE fit_sha256 = ?", (digest,)).fetchone()
    return dict(row)


def latest_activity(data_dir: Path | None = None) -> dict[str, Any] | None:
    con = connect_db(data_dir)
    row = con.execute(
        "SELECT * FROM activities ORDER BY COALESCE(start_time, created_at) DESC, id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_activity(activity_id: int, data_dir: Path | None = None) -> dict[str, Any]:
    con = connect_db(data_dir)
    row = con.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if not row:
        raise KeyError(f"activity not found: {activity_id}")
    return dict(row)


def list_activities(limit: int = 20, data_dir: Path | None = None) -> list[dict[str, Any]]:
    con = connect_db(data_dir)
    rows = con.execute(
        "SELECT * FROM activities ORDER BY COALESCE(start_time, created_at) DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_activity_analysis(activity_id: int, data_dir: Path | None = None) -> dict[str, Any] | None:
    activity = get_activity(activity_id, data_dir=data_dir)
    if not activity.get("analysis_json"):
        return None
    return json.loads(activity["analysis_json"])


def recent_training_history(days: int = 30, data_dir: Path | None = None) -> dict[str, Any]:
    con = connect_db(data_dir)
    rows = con.execute(
        """
        SELECT * FROM activities
        WHERE start_time IS NOT NULL
          AND datetime(start_time) >= datetime('now', ?)
        ORDER BY start_time DESC
        """,
        (f"-{int(days)} days",),
    ).fetchall()
    activities = [_compact_activity_row(dict(row)) for row in rows]
    totals = {
        "activity_count": len(activities),
        "duration_s": sum(float(a.get("duration_s") or 0) for a in activities),
        "distance_m": sum(float(a.get("distance_m") or 0) for a in activities),
        "by_sport": {},
    }
    for activity in activities:
        sport = activity.get("sport_type") or "unknown"
        bucket = totals["by_sport"].setdefault(
            sport,
            {"activity_count": 0, "duration_s": 0.0, "distance_m": 0.0},
        )
        bucket["activity_count"] += 1
        bucket["duration_s"] += float(activity.get("duration_s") or 0)
        bucket["distance_m"] += float(activity.get("distance_m") or 0)

    return {
        "days": int(days),
        "totals": totals,
        "activities": activities,
    }


def _compact_activity_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "source": row.get("source"),
        "source_activity_id": row.get("source_activity_id"),
        "file_name": row.get("file_name"),
        "sport_type": row.get("sport_type"),
        "start_time": row.get("start_time"),
        "duration_s": row.get("duration_s"),
        "distance_m": row.get("distance_m"),
        "fit_path": row.get("fit_path"),
        "has_summary": bool(row.get("summary_json")),
        "has_analysis": bool(row.get("analysis_json")),
    }


def save_analysis_report(
    activity_id: int,
    markdown: str,
    *,
    report_type: str = "llm_summary",
    summary: dict[str, Any] | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    get_activity(activity_id, data_dir=data_dir)
    now = datetime.now(timezone.utc).isoformat()
    con = connect_db(data_dir)
    con.execute(
        """
        INSERT INTO analysis_reports (
            activity_id, report_type, model, prompt_version,
            summary_json, markdown, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id,
            report_type,
            model,
            prompt_version,
            json.dumps(summary or {}, ensure_ascii=False),
            markdown,
            now,
        ),
    )
    con.commit()
    row = con.execute(
        "SELECT * FROM analysis_reports WHERE id = last_insert_rowid()"
    ).fetchone()
    return dict(row)


def list_analysis_reports(activity_id: int, data_dir: Path | None = None) -> list[dict[str, Any]]:
    con = connect_db(data_dir)
    rows = con.execute(
        "SELECT * FROM analysis_reports WHERE activity_id = ? ORDER BY created_at DESC",
        (activity_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_activity_summary(
    activity_id: int,
    *,
    summary: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    data_dir: Path | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con = connect_db(data_dir)
    con.execute(
        """
        UPDATE activities
        SET sport_type = ?,
            start_time = ?,
            duration_s = ?,
            distance_m = ?,
            summary_json = ?,
            analysis_json = COALESCE(?, analysis_json),
            updated_at = ?
        WHERE id = ?
        """,
        (
            summary.get("sport_type"),
            summary.get("start_time"),
            summary.get("duration_s"),
            summary.get("distance_m"),
            json.dumps(summary, ensure_ascii=False),
            json.dumps(analysis, ensure_ascii=False) if analysis is not None else None,
            now,
            activity_id,
        ),
    )
    con.commit()
