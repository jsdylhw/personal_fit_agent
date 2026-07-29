"""通用 Workflow Run 的原子 JSON 存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_WORKFLOW_DIRECTORY = Path("data") / "runs"


def workflow_path(workflow_id: str, *, directory: str | Path | None = None) -> Path:
    """返回受限的 workflow 文件路径，禁止路径穿越。"""
    workflow_id = str(workflow_id).strip()
    if not workflow_id or any(value in workflow_id for value in ("/", "\\", "..")):
        raise ValueError("invalid workflow_id")
    root = Path(directory) if directory is not None else DEFAULT_WORKFLOW_DIRECTORY
    return root / f"{workflow_id}.json"


def save_workflow(run: dict[str, Any], *, directory: str | Path | None = None) -> Path:
    """原子写入完整运行快照。"""
    workflow_id = str(run.get("workflow_id") or "")
    target = workflow_path(workflow_id, directory=directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(run, handle, ensure_ascii=False, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_workflow(workflow_id: str, *, directory: str | Path | None = None) -> dict[str, Any] | None:
    """读取单个运行快照；不存在或损坏时返回 None。"""
    try:
        payload = json.loads(workflow_path(workflow_id, directory=directory).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
