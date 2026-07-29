"""单 FIT summary 生成操作适配器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.activity.operations.service import analyze_fit_file_tool


def ensure_summary(fit_path: str | Path, *, force: bool = False) -> dict[str, Any]:
    """确保一个 FIT 有真实存在的 summary 文件。"""
    path = Path(fit_path).expanduser()
    if not path.exists():
        return _failed(path, "fit_not_found", f"FIT file does not exist: {path}")
    if path.suffix.lower() != ".fit":
        return _failed(path, "invalid_fit_path", f"Expected a .fit file: {path}")
    try:
        result = analyze_fit_file_tool(str(path), force=force)
    except Exception as exc:
        return _failed(path, type(exc).__name__, str(exc))

    summary_path = Path(str(result.get("summary_path") or "")).expanduser()
    if result.get("error") or not summary_path.exists():
        return _failed(
            path,
            str(result.get("error") or "summary_not_persisted"),
            str(result.get("message") or "Analysis did not persist a summary file"),
            raw_result=result,
        )
    status = "skipped" if result.get("status") == "skipped_existing_summary" else "completed"
    return {
        "schema_version": "activity_operation_analysis.v1",
        "operation": "ensure_summary",
        "status": status,
        "activity_key": result.get("activity_key"),
        "fit_path": str(path),
        "summary_path": str(summary_path),
        "result_status": result.get("status"),
        "raw_result": result,
    }


def _failed(path: Path, error: str, message: str, *, raw_result: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "activity_operation_analysis.v1",
        "operation": "ensure_summary",
        "status": "failed",
        "fit_path": str(path),
        "error": error,
        "message": message,
    }
    if raw_result is not None:
        result["raw_result"] = raw_result
    return result
