"""FastAPI Web API:9 个接口,提供 Web UI 后端的活动管理能力.

注意:所有接口是同步的,LLM 分析接口会阻塞事件循环(30-120s).
后续应改为 async + run_in_executor.
"""

from __future__ import annotations

import hmac
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import cfg_get, load_config
from core.activity_index import upsert_activity_from_fit
from agent.activity.analysis_agent import analyze_fit_file
from core.garmin_cn import (
    DEFAULT_OUTPUT_DIR,
    build_downloader,
    existing_fit_paths,
    save_original_as_fit,
)
from core.strava_upload import upload_summary_to_strava
from fit.parser import parse_fit


app = FastAPI(title="Personal FIT Agent API")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class DownloadGarminRequest(BaseModel):
    count: int | None = None


class AnalyzeFitRequest(BaseModel):
    path: str
    history: bool = True
    force: bool = False


class UploadStravaRequest(BaseModel):
    summary_path: str
    title: str | None = None
    wait: bool = True
    confirmed: bool = False
    force: bool = False


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard/status")
def dashboard_status_endpoint(request: Request) -> dict[str, Any]:
    _require_api_access(request)
    config = load_config()
    output_dir = _fit_output_dir(config)
    return {
        "garmin_configured": bool(config.get("garmin_username") and config.get("garmin_password")),
        "strava_configured": bool(
            config.get("strava", {}).get("access_token")
            or (
                config.get("strava", {}).get("client_id")
                and config.get("strava", {}).get("client_secret")
                and config.get("strava", {}).get("refresh_token")
            )
        ),
        "fit_dir": str(output_dir),
        "fit_count": len(_fit_files(output_dir)),
    }


@app.post("/api/garmin/connect")
def garmin_connect_endpoint(request: Request) -> dict[str, Any]:
    _require_api_access(request)
    downloader = build_downloader(load_config())
    downloader.login()
    activities = downloader.list_activities(1)
    return {"status": "connected", "latest_activity": activities[0] if activities else None}


@app.post("/api/garmin/download")
def garmin_download_endpoint(request: DownloadGarminRequest, http_request: Request) -> dict[str, Any]:
    _require_api_access(http_request)
    config = load_config()
    output_dir = _fit_output_dir(config)
    count = request.count or int(cfg_get(config, "download_count", 5))

    downloader = build_downloader(config)
    downloader.login()
    activities = downloader.list_activities(count)
    results: list[dict[str, Any]] = []
    for activity in activities:
        activity_id = activity.get("activityId")
        existing_paths = existing_fit_paths(output_dir, activity)
        if existing_paths:
            index_results = _index_downloaded_fit_paths(existing_paths, activity_id)
            results.append(
                {
                    "activity_id": activity_id,
                    "name": activity.get("activityName"),
                    "status": "skipped_existing",
                    "paths": [str(path) for path in existing_paths],
                    "index_results": index_results,
                }
            )
            continue

        raw_bytes = downloader.download_original(activity_id)
        saved_paths = save_original_as_fit(raw_bytes, output_dir, activity)
        index_results = _index_downloaded_fit_paths(saved_paths, activity_id)
        results.append(
            {
                "activity_id": activity_id,
                "name": activity.get("activityName"),
                "status": "downloaded",
                "paths": [str(path) for path in saved_paths],
                "index_results": index_results,
            }
        )

    return {
        "status": "ok",
        "fit_dir": str(output_dir),
        "count": len(results),
        "downloaded": sum(1 for item in results if item["status"] == "downloaded"),
        "skipped": sum(1 for item in results if item["status"] == "skipped_existing"),
        "results": results,
    }


def _index_downloaded_fit_paths(paths: list[Path], activity_id: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in paths:
        try:
            entry = upsert_activity_from_fit(
                path,
                source="garmin_cn",
                source_activity_id=str(activity_id) if activity_id is not None else None,
            )
        except Exception as exc:
            results.append({
                "path": str(path),
                "status": "failed",
                "error": type(exc).__name__,
                "message": str(exc),
            })
            continue
        results.append({
            "path": str(path),
            "status": "indexed",
            "activity_key": entry.get("activity_key"),
            "sport_type": entry.get("sport_type"),
            "start_time_local": entry.get("start_time_local"),
        })
    return results


@app.get("/api/fit-files")
def fit_files_endpoint(request: Request) -> dict[str, Any]:
    _require_api_access(request)
    config = load_config()
    output_dir = _fit_output_dir(config)
    files = [_fit_file_info(path) for path in _fit_files(output_dir)]
    files.sort(key=_activity_sort_key, reverse=True)
    return {"fit_dir": str(output_dir), "files": files}


@app.post("/api/fit-files/analyze")
def analyze_fit_endpoint(request: AnalyzeFitRequest, http_request: Request) -> dict[str, Any]:
    _require_api_access(http_request)
    config = load_config()
    fit_path = _require_managed_path(
        request.path,
        allowed_root=_fit_output_dir(config),
        suffix=".fit",
        label="FIT file",
    )
    return analyze_fit_file(fit_path, use_history=request.history, force=request.force)


@app.get("/api/summary")
def summary_endpoint(path: str, request: Request):
    """读取 summary JSON,返回 markdown_report 用于前端展示.

    只允许 data/summaries/ 下的 .summary.json 文件.
    """
    _require_api_access(request)
    requested = _require_managed_path(
        path,
        allowed_root=Path("data/summaries"),
        suffix=".summary.json",
        label="summary file",
    )
    data = json.loads(requested.read_text(encoding="utf-8"))
    return {"markdown_report": data.get("markdown_report", "")}


@app.post("/api/strava/upload")
def strava_upload_endpoint(request: UploadStravaRequest, http_request: Request) -> dict[str, Any]:
    _require_api_access(http_request)
    summary_path = _require_managed_path(
        request.summary_path,
        allowed_root=Path("data/summaries"),
        suffix=".summary.json",
        label="summary file",
    )
    if not request.confirmed:
        raise HTTPException(status_code=409, detail="Set confirmed=true to upload to Strava.")
    return upload_summary_to_strava(
        summary_path,
        title=request.title,
        wait=request.wait,
        force=request.force,
    )


def _fit_output_dir(config: dict[str, Any]) -> Path:
    return Path(cfg_get(config, "output_dir", DEFAULT_OUTPUT_DIR)).expanduser().resolve()


def _require_api_access(request: Request) -> None:
    """Keep the local control plane local unless a configured token is supplied.

    A configured token is required even from localhost. Without it, only a
    loopback client may call `/api/*`; this prevents an accidental `--host
    0.0.0.0` deployment from exposing Garmin, LLM, and Strava capabilities.
    """
    configured_token = str(cfg_get(load_config(), "web_api_token", "") or "")
    supplied_token = request.headers.get("X-API-Token", "")
    if configured_token:
        if hmac.compare_digest(supplied_token, configured_token):
            return
        raise HTTPException(status_code=401, detail="Valid X-API-Token is required.")

    client_host = request.client.host if request.client else ""
    if client_host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return
    raise HTTPException(
        status_code=401,
        detail="Web API is local-only. Configure web_api_token for remote access.",
    )


def _require_managed_path(
    value: str,
    *,
    allowed_root: Path,
    suffix: str,
    label: str,
) -> Path:
    root = allowed_root.expanduser().resolve()
    candidate = Path(value).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=f"{label} must be inside {root}.") from exc
    if not candidate.name.lower().endswith(suffix):
        raise HTTPException(status_code=422, detail=f"{label} must end with {suffix}.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"{label} does not exist.")
    return candidate


def _fit_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob("*.fit"), key=lambda path: path.name)


def _fit_file_info(path: Path) -> dict[str, Any]:
    summary_path = _matching_summary_path(path)
    info: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "has_summary": summary_path.exists(),
    }

    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            info["fit_summary"] = summary.get("fit_summary")
            info["history_entry"] = summary.get("history_entry")
            info["display_summary"] = _display_summary_from_analysis(summary)
            info["strava_summary"] = summary.get("strava_summary")
            info["strava_summary_tone"] = summary.get("strava_summary_tone")
        except (OSError, json.JSONDecodeError):
            info["summary_error"] = "Failed to read summary JSON"
    else:
        try:
            fit_summary = parse_fit(path).get("summary")
            info["fit_summary"] = fit_summary
            info["display_summary"] = _display_summary_from_fit(fit_summary)
        except Exception as exc:
            info["parse_error"] = str(exc)

    return info


def _display_summary_from_analysis(summary: dict[str, Any]) -> dict[str, Any]:
    fit_summary = summary.get("fit_summary") or {}
    history_entry = summary.get("history_entry") or {}
    return {
        "start_time": (
            history_entry.get("start_time_local")
            or fit_summary.get("start_time_local")
            or history_entry.get("start_time")
            or fit_summary.get("start_time")
        ),
        "sport_type": history_entry.get("sport_type") or fit_summary.get("sport_type"),
        "sub_sport": history_entry.get("sub_sport") or fit_summary.get("sub_sport"),
        "distance_km": history_entry.get("distance_km") or _meters_to_km(fit_summary.get("distance_m")),
        "duration_min": history_entry.get("duration_min") or _seconds_to_min(fit_summary.get("duration_s")),
        "summary_label": history_entry.get("summary_label") or "",
        "main_stimulus": history_entry.get("main_stimulus") or "",
        "training_load": history_entry.get("training_load") or "",
        "brief": history_entry.get("brief") or "",
    }


def _display_summary_from_fit(fit_summary: dict[str, Any] | None) -> dict[str, Any]:
    fit_summary = fit_summary or {}
    return {
        "start_time": fit_summary.get("start_time_local") or fit_summary.get("start_time"),
        "sport_type": fit_summary.get("sport_type"),
        "sub_sport": fit_summary.get("sub_sport"),
        "distance_km": _meters_to_km(fit_summary.get("distance_m")),
        "duration_min": _seconds_to_min(fit_summary.get("duration_s")),
        "summary_label": "",
        "main_stimulus": "",
        "training_load": "",
        "brief": "",
    }


def _activity_sort_key(item: dict[str, Any]) -> float | str:
    display = item.get("display_summary") or {}
    fit_summary = item.get("fit_summary") or {}
    value = display.get("start_time") or fit_summary.get("start_time")
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.timestamp()
    return str(value or item.get("name") or "")


def _matching_summary_path(path: Path) -> Path:
    exact = Path("data") / "summaries" / f"{path.stem}.summary.json"
    if exact.exists():
        return exact
    activity_id = _activity_id_from_stem(path.stem)
    if activity_id:
        matches = sorted((Path("data") / "summaries").glob(f"*_{activity_id}.summary.json"))
        if matches:
            return matches[0]
    return exact


def _activity_id_from_stem(stem: str) -> str | None:
    match = re.search(r"_(\d{6,})$", stem)
    return match.group(1) if match else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _meters_to_km(value: Any) -> float | None:
    try:
        return round(float(value) / 1000, 2)
    except (TypeError, ValueError):
        return None


def _seconds_to_min(value: Any) -> float | None:
    try:
        return round(float(value) / 60, 1)
    except (TypeError, ValueError):
        return None
