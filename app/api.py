from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.chat import chat_about_activity
from agent.tools import call_tool, tool_catalog
from core.storage import get_activity, list_activities, list_analysis_reports
from core.workflow import analyze_activity, import_fit


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


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
