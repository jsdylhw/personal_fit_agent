from __future__ import annotations

import json
from typing import Any, Callable

from core.file_workflow import analyze_fit_file
from core.history import query_activity_history
from core.storage import (
    get_activity,
    get_activity_analysis,
    latest_activity,
    list_activities,
    list_analysis_reports,
    recent_training_history,
    save_analysis_report,
)
from core.workflow import analyze_activity, import_fit
from analysis.fatigue import analyze_fatigue_and_stability
from analysis.indicators import INDICATOR_HANDLERS, indicator_catalog
from analysis.intensity import analyze_intensity_distribution
from analysis.quality import data_quality_from_analysis
from analysis.recommendation import generate_training_recommendation
from analysis.segments import detect_workout_segments
from analysis.summary import get_activity_summary


ToolHandler = Callable[[dict[str, Any]], Any]


def tool_catalog() -> dict[str, Any]:
    return {
        "schema_version": "tool_catalog.v1",
        "usage": (
            "Model should inspect this catalog, request specific tool calls, "
            "then use returned structured data for reasoning. Tools return data, not coaching advice."
        ),
        "categories": [
            {
                "name": "file_based_analysis",
                "description": "File-based FIT analysis without SQLite. Use history only when the user asks to compare with past training.",
                "tools": [
                    {
                        "name": "analyze_fit_file",
                        "description": "Analyze one local FIT file, write a summary/report, and update JSONL training history.",
                        "side_effect": True,
                        "params": {
                            "fit_path": {"type": "string", "required": True},
                            "use_history": {"type": "boolean", "required": False, "default": False},
                            "force": {"type": "boolean", "required": False, "default": False},
                        },
                        "returns": "file analysis result",
                    },
                    {
                        "name": "get_file_training_history",
                        "description": "Read compact JSONL training history before a given activity time. Call only when history or comparison is requested.",
                        "side_effect": False,
                        "params": {
                            "before": {"type": "string", "required": False},
                            "days": {"type": "integer", "required": False, "default": 90},
                            "limit": {"type": "integer", "required": False, "default": 20},
                        },
                        "returns": "compact training history",
                    },
                ],
            },
            {
                "name": "source_management",
                "description": "数据导入和归档管理。通常由本地程序调用，模型需要导入新 FIT 时才使用。",
                "tools": [
                    {
                        "name": "import_fit_file",
                        "description": "导入一个本地 FIT 文件，复制到 data/fit，并写入 activities 索引。",
                        "side_effect": True,
                        "params": {
                            "path": {"type": "string", "required": True, "description": "本地 FIT 文件路径"},
                            "source": {"type": "string", "required": False, "default": "manual"},
                        },
                        "returns": "activity row",
                    },
                ],
            },
            {
                "name": "history_records",
                "description": "历史运动记录列表。每条活动只暴露基础摘要：时间、距离、卡路里、心率等。",
                "tools": [
                    {
                        "name": "list_activity_history",
                        "description": "列出本地活动历史摘要，不返回单次活动的详细时序或完整分析。",
                        "side_effect": False,
                        "params": {
                            "limit": {"type": "integer", "required": False, "default": 20},
                        },
                        "returns": "history summary rows",
                    },
                ],
            },
            {
                "name": "activity_indicators",
                "description": "低层指标请求函数。普通运动分析优先使用 activity_analysis_tools；只有明确询问单个指标时才调用 request_*。",
                "tools": [
                    {
                        "name": "list_activity_indicators",
                        "description": "列出可单独请求的固定指标函数，如 request_tss、request_distance、request_if。",
                        "side_effect": False,
                        "params": {},
                        "returns": "indicator function catalog",
                    },
                    *_indicator_tool_specs(),
                ],
            },
            {
                "name": "activity_analysis_tools",
                "description": "具体某一次活动的专业分析任务工具。普通表现分析、训练建议、结构判断优先使用这些工具。",
                "tools": [
                    {
                        "name": "get_activity_summary",
                        "description": "返回活动基础摘要：时间、距离、速度、功率、心率、TSS、IF、VI、阈值配置等。",
                        "side_effect": False,
                        "params": _activity_id_params(),
                        "returns": "activity summary",
                    },
                    {
                        "name": "check_activity_data_quality",
                        "description": "返回数据质量检查结果，说明是否有功率、心率、GPS、采样和异常限制。",
                        "side_effect": False,
                        "params": _activity_id_params(),
                        "returns": "data quality report",
                    },
                    {
                        "name": "analyze_intensity_distribution",
                        "description": "分析功率区间、心率区间、高低强度占比和主要训练刺激。",
                        "side_effect": False,
                        "params": _activity_id_params(),
                        "returns": "intensity distribution analysis",
                    },
                    {
                        "name": "detect_workout_segments",
                        "description": "按 10/30/60 秒分桶识别恢复、有氧、节奏、阈值、高强度、滑行/暂停等分段。",
                        "side_effect": False,
                        "params": {
                            **_activity_id_params(),
                            "bucket_seconds": {
                                "type": "integer",
                                "required": False,
                                "default": 60,
                                "enum": [10, 30, 60],
                                "description": "按多少秒分桶。",
                            },
                        },
                        "returns": "workout segment analysis",
                    },
                    {
                        "name": "analyze_fatigue_and_stability",
                        "description": "分析前后半程功率/心率/踏频变化、心率漂移、有氧解耦和稳定性。",
                        "side_effect": False,
                        "params": _activity_id_params(),
                        "returns": "fatigue and stability analysis",
                    },
                    {
                        "name": "generate_training_recommendation",
                        "description": "返回训练建议所需的结构化上下文、候选训练方向和限制条件；最终建议由大模型生成。",
                        "side_effect": False,
                        "params": {
                            **_activity_id_params(),
                            "goal": {
                                "type": "string",
                                "required": False,
                                "default": "general_review",
                                "description": "用户目标，如 general_review、base_endurance、ftp_improvement、vo2max、recovery、fat_loss。",
                            },
                        },
                        "returns": "training recommendation context",
                    },
                ],
            },
            {
                "name": "analysis_reports",
                "description": "保存和读取模型生成的分析报告。写入前建议用户确认。",
                "tools": [
                    {
                        "name": "save_activity_report",
                        "description": "保存模型生成的活动总结或建议到 analysis_reports。",
                        "side_effect": True,
                        "params": {
                            "activity_id": {"type": "integer", "required": True},
                            "markdown": {"type": "string", "required": True},
                            "summary": {"type": "object", "required": False},
                            "report_type": {"type": "string", "required": False, "default": "llm_summary"},
                            "model": {"type": "string", "required": False},
                            "prompt_version": {"type": "string", "required": False},
                        },
                        "returns": "analysis_report row",
                    },
                    {
                        "name": "list_activity_reports",
                        "description": "列出某个活动已保存的模型报告。",
                        "side_effect": False,
                        "params": {
                            "activity_id": {"type": "integer", "required": True},
                        },
                        "returns": "analysis_report rows",
                    },
                ],
            },
            {
                "name": "external_platforms_planned",
                "description": "后续外部平台工具，当前只作为规划占位，不可调用。",
                "tools": [
                    {
                        "name": "upload_activity_to_strava",
                        "description": "计划中：上传 FIT 到 Strava。",
                        "available": False,
                    },
                    {
                        "name": "update_strava_description",
                        "description": "计划中：把模型总结写入 Strava 活动描述。",
                        "available": False,
                    },
                    {
                        "name": "sync_latest_from_garmin",
                        "description": "计划中：从 Garmin 下载最新 FIT 并导入本地。",
                        "available": False,
                    },
                    {
                        "name": "sync_latest_from_magene",
                        "description": "计划中：从迈金下载最新 FIT 并导入本地。",
                        "available": False,
                    },
                ],
            },
        ],
    }


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    arguments = arguments or {}
    handlers: dict[str, ToolHandler] = {
        "import_fit_file": _import_fit_file,
        "analyze_fit_file": _analyze_fit_file,
        "get_file_training_history": _get_file_training_history,
        "list_activities": _list_activities,
        "list_activity_history": _list_activity_history,
        "get_activity": _get_activity,
        "analyze_activity": _analyze_activity,
        "get_activity_raw_analysis": _get_activity_raw_analysis,
        "get_activity_sample_statistics": _get_activity_sample_statistics,
        "get_activity_lap_summaries": _get_activity_lap_summaries,
        "get_activity_data_quality": _get_activity_data_quality,
        "get_activity_summary": _tool_get_activity_summary,
        "check_activity_data_quality": _tool_check_activity_data_quality,
        "analyze_intensity_distribution": _tool_analyze_intensity_distribution,
        "detect_workout_segments": _tool_detect_workout_segments,
        "analyze_fatigue_and_stability": _tool_analyze_fatigue_and_stability,
        "generate_training_recommendation": _tool_generate_training_recommendation,
        "list_activity_indicators": _list_activity_indicators,
        **_indicator_handlers(),
        "get_recent_training_history": _get_recent_training_history,
        "save_activity_report": _save_activity_report,
        "list_activity_reports": _list_activity_reports,
    }
    if name not in handlers:
        raise KeyError(f"unknown or unavailable tool: {name}")
    return handlers[name](arguments)


def _resolve_activity_id(activity_id: int | str | None) -> int:
    if activity_id in (None, "latest"):
        activity = latest_activity()
        if not activity:
            raise RuntimeError("no activities archived")
        return int(activity["id"])
    return int(activity_id)


def _ensure_analysis(activity_id: int | str | None) -> dict[str, Any]:
    resolved = _resolve_activity_id(activity_id)
    analysis = get_activity_analysis(resolved)
    if analysis is None:
        result = analyze_activity(resolved, make_plot=False)
        analysis = result["analysis"]
    return analysis


def _import_fit_file(arguments: dict[str, Any]) -> dict[str, Any]:
    return import_fit(arguments["path"], source=arguments.get("source", "manual"))


def _analyze_fit_file(arguments: dict[str, Any]) -> dict[str, Any]:
    return analyze_fit_file(
        arguments["fit_path"],
        use_history=bool(arguments.get("use_history", False)),
        force=bool(arguments.get("force", False)),
    )


def _get_file_training_history(arguments: dict[str, Any]) -> dict[str, Any]:
    return query_activity_history(
        before=arguments.get("before"),
        days=int(arguments.get("days", 90)) if arguments.get("days") is not None else None,
        limit=int(arguments.get("limit", 20)),
    )


def _list_activities(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [_compact_activity(row) for row in list_activities(limit=int(arguments.get("limit", 20)))]


def _list_activity_history(arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit", 20))
    rows = list_activities(limit=limit)
    activities = [_history_activity(row) for row in rows]
    return {
        "schema_version": "activity_history.v1",
        "limit": limit,
        "activities": activities,
    }


def _get_activity(arguments: dict[str, Any]) -> dict[str, Any]:
    return get_activity(_resolve_activity_id(arguments.get("activity_id", "latest")))


def _analyze_activity(arguments: dict[str, Any]) -> dict[str, Any]:
    return analyze_activity(
        arguments.get("activity_id", "latest"),
        make_plot=bool(arguments.get("make_plot", True)),
    )


def _get_activity_raw_analysis(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return analysis["llm_context"]


def _get_activity_sample_statistics(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return analysis["sample_statistics"]


def _get_activity_lap_summaries(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return analysis["lap_summaries"]


def _get_activity_data_quality(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return analysis["data_quality"]


def _tool_get_activity_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return get_activity_summary(analysis)


def _tool_check_activity_data_quality(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return data_quality_from_analysis(analysis)


def _tool_analyze_intensity_distribution(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return analyze_intensity_distribution(analysis)


def _tool_detect_workout_segments(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return detect_workout_segments(
        analysis,
        bucket_seconds=int(arguments.get("bucket_seconds", 60)),
    )


def _tool_analyze_fatigue_and_stability(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return analyze_fatigue_and_stability(analysis)


def _tool_generate_training_recommendation(arguments: dict[str, Any]) -> dict[str, Any]:
    analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
    return generate_training_recommendation(
        analysis,
        goal=str(arguments.get("goal") or "general_review"),
    )


def _list_activity_indicators(arguments: dict[str, Any]) -> list[dict[str, str]]:
    return indicator_catalog()


def _get_recent_training_history(arguments: dict[str, Any]) -> dict[str, Any]:
    return recent_training_history(days=int(arguments.get("days", 30)))


def _save_activity_report(arguments: dict[str, Any]) -> dict[str, Any]:
    return save_analysis_report(
        int(arguments["activity_id"]),
        arguments["markdown"],
        report_type=arguments.get("report_type", "llm_summary"),
        summary=arguments.get("summary"),
        model=arguments.get("model"),
        prompt_version=arguments.get("prompt_version"),
    )


def _list_activity_reports(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return list_analysis_reports(int(arguments["activity_id"]))


def _compact_activity(row: dict[str, Any]) -> dict[str, Any]:
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


def _history_activity(row: dict[str, Any]) -> dict[str, Any]:
    analysis = _loads_json(row.get("analysis_json")) or {}
    activity_metrics = analysis.get("activity_metrics", {})
    return {
        "activity_id": row.get("id"),
        "sport_type": row.get("sport_type"),
        "start_time": row.get("start_time"),
        "duration_s": row.get("duration_s"),
        "distance_m": row.get("distance_m"),
        "distance_km": _round_or_none((row.get("distance_m") or 0) / 1000, 3)
        if row.get("distance_m") is not None
        else None,
        "calories": activity_metrics.get("calories"),
        "average_heart_rate": activity_metrics.get("avg_hr"),
        "max_heart_rate": activity_metrics.get("max_hr"),
        "has_analysis": bool(row.get("analysis_json")),
    }


def _loads_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _activity_id_params() -> dict[str, Any]:
    return {
        "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
    }


def _indicator_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": item["name"],
            "description": item["description"],
            "side_effect": False,
            "params": _indicator_params(item["name"]),
            "returns": "indicator result",
        }
        for item in indicator_catalog()
    ]


def _indicator_handlers() -> dict[str, ToolHandler]:
    return {
        name: _make_indicator_handler(name)
        for name in INDICATOR_HANDLERS
    }


def _make_indicator_handler(name: str) -> ToolHandler:
    def handler(arguments: dict[str, Any]) -> Any:
        analysis = _ensure_analysis(arguments.get("activity_id", "latest"))
        if name == "request_time_series_summary":
            return INDICATOR_HANDLERS[name](
                analysis,
                bucket_seconds=int(arguments.get("bucket_seconds", 60)),
            )
        return INDICATOR_HANDLERS[name](analysis)

    return handler


def _indicator_params(name: str) -> dict[str, Any]:
    params = {
        "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
    }
    if name == "request_time_series_summary":
        params["bucket_seconds"] = {
            "type": "integer",
            "required": False,
            "default": 60,
            "enum": [10, 30, 60],
            "description": "按多少秒分桶。",
        }
    return params
