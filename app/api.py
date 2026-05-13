from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.chat import chat_about_activity
from agent.tools import call_tool, tool_catalog
from core.config import load_config
from core.file_workflow import analyze_fit_file, analyze_fit_folder
from core.storage import get_activity, list_activities, list_analysis_reports
from core.strava_workflow import upload_summary_to_strava
from core.workflow import analyze_activity, import_fit
from download_garmin_cn_fit import (
    DEFAULT_OUTPUT_DIR,
    activity_base_name,
    build_downloader,
    cfg_get,
    existing_fit_paths,
    save_original_as_fit,
)
from fit.parser import parse_fit


app = FastAPI(title="Personal FIT Agent API")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ImportFitRequest(BaseModel):
    path: str
    source: str = "manual"


class AnalyzeRequest(BaseModel):
    activity_id: int | str = "latest"
    make_plot: bool = True


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict = {}


class ChatActivityRequest(BaseModel):
    question: str
    activity_id: int | str = "latest"
    history_days: int = 30
    save_report: bool = False


class DownloadGarminRequest(BaseModel):
    count: int | None = None


class AnalyzeFitRequest(BaseModel):
    path: str
    history: bool = True
    force: bool = False


class AnalyzeFolderRequest(BaseModel):
    history: bool = True
    force: bool = False


class UploadStravaRequest(BaseModel):
    summary_path: str
    title: str | None = None
    wait: bool = True


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard/status")
def dashboard_status_endpoint() -> dict[str, Any]:
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
def garmin_connect_endpoint() -> dict[str, Any]:
    downloader = build_downloader(load_config())
    downloader.login()
    activities = downloader.list_activities(1)
    return {"status": "connected", "latest_activity": activities[0] if activities else None}


@app.post("/api/garmin/download")
def garmin_download_endpoint(request: DownloadGarminRequest) -> dict[str, Any]:
    config = load_config()
    output_dir = _fit_output_dir(config)
    count = request.count or int(cfg_get(config, "download_count", 5))

    downloader = build_downloader(config)
    downloader.login()
    activities = downloader.list_activities(count)
    results: list[dict[str, Any]] = []
    for activity in activities:
        existing_paths = existing_fit_paths(output_dir, activity)
        if existing_paths:
            results.append(
                {
                    "activity_id": activity.get("activityId"),
                    "name": activity.get("activityName"),
                    "status": "skipped_existing",
                    "paths": [str(path) for path in existing_paths],
                }
            )
            continue

        raw_bytes = downloader.download_original(activity.get("activityId"))
        saved_paths = save_original_as_fit(raw_bytes, output_dir, activity)
        results.append(
            {
                "activity_id": activity.get("activityId"),
                "name": activity.get("activityName"),
                "status": "downloaded",
                "paths": [str(path) for path in saved_paths],
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


@app.get("/api/fit-files")
def fit_files_endpoint() -> dict[str, Any]:
    config = load_config()
    output_dir = _fit_output_dir(config)
    files = [_fit_file_info(path) for path in _fit_files(output_dir)]
    files.sort(key=_activity_sort_key, reverse=True)
    return {"fit_dir": str(output_dir), "files": files}


@app.post("/api/fit-files/analyze")
def analyze_fit_endpoint(request: AnalyzeFitRequest) -> dict[str, Any]:
    return analyze_fit_file(request.path, use_history=request.history, force=request.force)


@app.post("/api/fit-files/analyze-folder")
def analyze_fit_folder_endpoint(request: AnalyzeFolderRequest) -> dict[str, Any]:
    return analyze_fit_folder(_fit_output_dir(load_config()), use_history=request.history, force=request.force)


@app.get("/api/report")
def report_endpoint(path: str) -> PlainTextResponse:
    report_path = Path(path)
    if not report_path.exists():
        raise FileNotFoundError(report_path)
    return PlainTextResponse(report_path.read_text(encoding="utf-8"))


@app.post("/api/strava/upload")
def strava_upload_endpoint(request: UploadStravaRequest) -> dict[str, Any]:
    return upload_summary_to_strava(request.summary_path, title=request.title, wait=request.wait)


@app.post("/tools/import_fit")
def import_fit_endpoint(request: ImportFitRequest):
    return import_fit(request.path, source=request.source)


@app.get("/tools/list_activities")
def list_activities_endpoint(limit: int = 20):
    return {"activities": list_activities(limit)}


@app.get("/api/activities")
def activities_endpoint(limit: int = 50):
    return {"activities": list_activities(limit)}


@app.get("/api/activities/{activity_id}")
def activity_detail_endpoint(activity_id: int):
    return {
        "activity": get_activity(activity_id),
        "summary": call_tool("get_activity_summary", {"activity_id": activity_id}),
        "data_quality": call_tool("check_activity_data_quality", {"activity_id": activity_id}),
        "intensity_distribution": call_tool("analyze_intensity_distribution", {"activity_id": activity_id}),
        "workout_segments": call_tool(
            "detect_workout_segments",
            {"activity_id": activity_id, "bucket_seconds": 60},
        ),
        "fatigue_and_stability": call_tool("analyze_fatigue_and_stability", {"activity_id": activity_id}),
        "recommendation_context": call_tool(
            "generate_training_recommendation",
            {"activity_id": activity_id, "goal": "general_review"},
        ),
        "reports": list_analysis_reports(activity_id),
    }


@app.post("/api/activities/{activity_id}/analyze")
def analyze_activity_api_endpoint(activity_id: int):
    return analyze_activity(activity_id, make_plot=True)


@app.get("/api/activities/{activity_id}/reports")
def activity_reports_endpoint(activity_id: int):
    return {"reports": list_analysis_reports(activity_id)}


@app.post("/tools/analyze_activity")
def analyze_activity_endpoint(request: AnalyzeRequest):
    return analyze_activity(request.activity_id, make_plot=request.make_plot)


@app.get("/tools/catalog")
def tool_catalog_endpoint():
    return tool_catalog()


@app.post("/tools/call")
def tool_call_endpoint(request: ToolCallRequest):
    return {
        "tool": request.name,
        "result": call_tool(request.name, request.arguments),
    }


@app.post("/chat/activity")
def chat_activity_endpoint(request: ChatActivityRequest):
    return chat_about_activity(
        request.question,
        activity_id=request.activity_id,
        history_days=request.history_days,
        save_report=request.save_report,
    )


@app.post("/api/chat/activity")
def chat_activity_api_endpoint(request: ChatActivityRequest):
    return chat_about_activity(
        request.question,
        activity_id=request.activity_id,
        history_days=request.history_days,
        save_report=request.save_report,
    )


def _fit_output_dir(config: dict[str, Any]) -> Path:
    return Path(cfg_get(config, "output_dir", DEFAULT_OUTPUT_DIR)).expanduser().resolve()


def _fit_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob("*.fit"), key=lambda path: path.name)


def _fit_file_info(path: Path) -> dict[str, Any]:
    summary_path = _matching_summary_path(path)
    report_path = _matching_report_path(path)
    info: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "report_path": str(report_path) if report_path.exists() else None,
        "has_summary": summary_path.exists(),
        "has_report": report_path.exists(),
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
        "start_time": history_entry.get("start_time") or fit_summary.get("start_time"),
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
        "start_time": fit_summary.get("start_time"),
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


def _matching_report_path(path: Path) -> Path:
    exact = Path("data") / "reports" / f"{path.stem}.md"
    if exact.exists():
        return exact
    activity_id = _activity_id_from_stem(path.stem)
    if activity_id:
        matches = sorted((Path("data") / "reports").glob(f"*_{activity_id}.md"))
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
