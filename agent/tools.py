from __future__ import annotations

from typing import Any, Callable

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
from analysis.indicators import INDICATOR_HANDLERS, indicator_catalog


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
                "name": "activity_archive",
                "description": "FIT 文件导入、归档、去重和本地活动索引。",
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
                    {
                        "name": "list_activities",
                        "description": "列出本地已归档活动，默认按开始时间倒序。",
                        "side_effect": False,
                        "params": {
                            "limit": {"type": "integer", "required": False, "default": 20},
                        },
                        "returns": "activity rows",
                    },
                    {
                        "name": "get_activity",
                        "description": "读取单个活动的数据库摘要和 FIT 文件路径。",
                        "side_effect": False,
                        "params": {
                            "activity_id": {"type": "integer|string", "required": True, "description": "活动 ID 或 latest"},
                        },
                        "returns": "activity row",
                    },
                ],
            },
            {
                "name": "activity_raw_analysis",
                "description": "单次活动的结构化原始分析数据。供模型分析使用，不包含训练建议。",
                "tools": [
                    {
                        "name": "analyze_activity",
                        "description": "解析 FIT 并计算详细原始指标，同时更新本地 activities.analysis_json。",
                        "side_effect": True,
                        "params": {
                            "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
                            "make_plot": {"type": "boolean", "required": False, "default": True},
                        },
                        "returns": "summary, analysis, plot_path, report_path",
                    },
                    {
                        "name": "get_activity_raw_analysis",
                        "description": "返回 activity_raw_analysis.v1 结构，包含 activity/samples/laps/data_quality。",
                        "side_effect": False,
                        "params": {
                            "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
                        },
                        "returns": "llm_context object",
                    },
                    {
                        "name": "get_activity_sample_statistics",
                        "description": "只读取时序采样字段统计，如心率、功率、速度、海拔、温度。",
                        "side_effect": False,
                        "params": {
                            "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
                        },
                        "returns": "sample_statistics",
                    },
                    {
                        "name": "get_activity_lap_summaries",
                        "description": "只读取每圈摘要，适合模型比较前后半程或分段表现。",
                        "side_effect": False,
                        "params": {
                            "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
                        },
                        "returns": "lap_summaries",
                    },
                    {
                        "name": "get_activity_data_quality",
                        "description": "读取数据质量标记，例如零距离、功率全 0、超长测试活动。",
                        "side_effect": False,
                        "params": {
                            "activity_id": {"type": "integer|string", "required": False, "default": "latest"},
                        },
                        "returns": "data_quality",
                    },
                ],
            },
            {
                "name": "activity_indicators",
                "description": "固定名称的单指标请求函数。模型需要哪个指标就调用对应 request_* 工具。",
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
                "name": "training_history",
                "description": "全局运动记录和近期训练历史。用于周总结、负荷趋势和计划上下文。",
                "tools": [
                    {
                        "name": "get_recent_training_history",
                        "description": "返回最近 N 天的活动列表和按运动类型聚合的训练总量。",
                        "side_effect": False,
                        "params": {
                            "days": {"type": "integer", "required": False, "default": 30},
                        },
                        "returns": "history totals and activity rows",
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
        "list_activities": _list_activities,
        "get_activity": _get_activity,
        "analyze_activity": _analyze_activity,
        "get_activity_raw_analysis": _get_activity_raw_analysis,
        "get_activity_sample_statistics": _get_activity_sample_statistics,
        "get_activity_lap_summaries": _get_activity_lap_summaries,
        "get_activity_data_quality": _get_activity_data_quality,
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


def _list_activities(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [_compact_activity(row) for row in list_activities(limit=int(arguments.get("limit", 20)))]


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
