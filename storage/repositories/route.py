"""SQLite repository for full route-plan artifacts and compact recovery state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from storage.database import connect_database


class RoutePlanStore:
    def __init__(self, path: str | Path | None = None):
        self.path = path

    def save(self, plan: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(plan.get("plan_id") or "").strip()
        workspace_id = str(plan.get("workspace_id") or "").strip()
        if not plan_id or not workspace_id:
            raise ValueError("plan_id and workspace_id are required")
        now = _now()
        with connect_database(self.path) as connection:
            existing = connection.execute(
                "SELECT revision, created_at FROM route_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            revision = int(existing["revision"] or 0) + 1 if existing else 1
            created_at = str(existing["created_at"]) if existing else now
            stored = {
                **plan,
                "revision": revision,
                "created_at": created_at,
                "updated_at": now,
            }
            connection.execute(
                """
                INSERT INTO route_plans (
                    id, workspace_id, revision, active_candidate_id,
                    plan_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    revision = excluded.revision,
                    active_candidate_id = excluded.active_candidate_id,
                    plan_json = excluded.plan_json,
                    updated_at = excluded.updated_at
                """,
                (
                    plan_id,
                    workspace_id,
                    revision,
                    stored.get("active_candidate_id"),
                    json.dumps(stored, ensure_ascii=False, default=str),
                    created_at,
                    now,
                ),
            )
        return stored

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with connect_database(self.path) as connection:
            row = connection.execute(
                "SELECT plan_json FROM route_plans WHERE id = ?",
                (str(plan_id),),
            ).fetchone()
        return _json_object(row["plan_json"]) if row else None

    def get_latest(self, workspace_id: str) -> dict[str, Any] | None:
        with connect_database(self.path) as connection:
            row = connection.execute(
                """
                SELECT plan_json FROM route_plans
                WHERE workspace_id = ?
                ORDER BY updated_at DESC, rowid DESC LIMIT 1
                """,
                (str(workspace_id),),
            ).fetchone()
        return _json_object(row["plan_json"]) if row else None


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
