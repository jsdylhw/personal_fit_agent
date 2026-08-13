"""SQLite connection and schema management.

The schema intentionally mirrors Rider Tracker's activity columns.  FIT files
remain immutable files on disk; SQLite owns their metadata and all generated
report state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.config import ensure_data_dirs


DEFAULT_DATABASE_PATH = Path("data") / "personal-fit-agent.db"
SCHEMA_VERSION = 1


def database_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    ensure_data_dirs()
    return DEFAULT_DATABASE_PATH


def connect_database(path: str | Path | None = None) -> sqlite3.Connection:
    target = database_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    initialize_database(connection)
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_activity_id TEXT,
            sport_type TEXT NOT NULL,
            sub_sport TEXT,
            name TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            elapsed_seconds REAL,
            distance_km REAL,
            ascent_meters REAL,
            average_power REAL,
            normalized_power REAL,
            average_hr REAL,
            estimated_tss REAL,
            has_gps_track INTEGER NOT NULL DEFAULT 0,
            fit_file_path TEXT NOT NULL UNIQUE,
            fit_file_size_bytes INTEGER,
            fit_file_created_at TEXT,
            strava_activity_id TEXT,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_activities_started_at
            ON activities(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_activities_source
            ON activities(source, source_activity_id);
        CREATE INDEX IF NOT EXISTS idx_activities_sport_type
            ON activities(sport_type, started_at DESC);

        CREATE TABLE IF NOT EXISTS activity_reports (
            activity_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            status TEXT NOT NULL,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            analysis_json TEXT NOT NULL DEFAULT '{}',
            markdown_report TEXT,
            strava_summary TEXT,
            model TEXT,
            prompt_version TEXT,
            input_hash TEXT,
            revision INTEGER NOT NULL DEFAULT 1,
            export_path TEXT,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_activity_reports_schema_version
            ON activity_reports(schema_version, updated_at DESC);
        """
    )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
