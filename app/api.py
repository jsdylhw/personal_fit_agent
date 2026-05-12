from fastapi import FastAPI
from pydantic import BaseModel

from agent.chat import chat_about_activity
from agent.tools import call_tool, tool_catalog
from core.storage import list_activities
from core.workflow import analyze_activity, import_fit


app = FastAPI(title="Personal FIT Agent API")


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tools/import_fit")
def import_fit_endpoint(request: ImportFitRequest):
    return import_fit(request.path, source=request.source)


@app.get("/tools/list_activities")
def list_activities_endpoint(limit: int = 20):
    return {"activities": list_activities(limit)}


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
