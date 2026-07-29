from __future__ import annotations

import json

from agent.activity.report import query_selected_activity_detail_tool, show_selected_activity_report_tool
from agent.main_agent.handlers import execute_summarize_activity_range
from agent.context import AgentContext


def test_show_selected_activity_report_reads_markdown_report(tmp_path):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_path": "/tmp/latest.fit",
                "fit_summary": {"sport_type": "cycling"},
                "markdown_report": "# 最新骑行报告\n\n这是一份已有报告。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[
            {
                "activity_key": "a1",
                "summary_path": str(summary),
            }
        ],
    )

    result = show_selected_activity_report_tool(context)

    assert result["status"] == "completed"
    assert result["answer"].startswith("# 最新骑行报告")
    assert result["result"]["source"] == "existing_summary"


def test_existing_summary_is_read_without_reanalysis_when_analyze_has_user_request(tmp_path, monkeypatch):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_path": "/tmp/latest.fit",
                "markdown_report": "# 通用报告",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run_activity_analysis_agent(fit_path: str, **kwargs):
        calls.append((fit_path, kwargs))
        return {
            "activity_key": "a1",
            "fit_path": fit_path,
            "summary_path": str(summary),
            "markdown_report": "# 短冲刺检查\n\n100-200 秒有一次冲刺。",
            "status": "analyzed_query",
            "agent": "ActivityAnalysisAgent",
        }

    monkeypatch.setattr("agent.activity.report.run_activity_analysis_agent", fake_run_activity_analysis_agent)
    context = AgentContext(
        session_id="targeted-question-test",
        selected_activities=[{"activity_key": "a1", "summary_path": str(summary)}],
    )

    result = show_selected_activity_report_tool(context, args={"user_request": "检查 100-200 秒是否有短冲刺"})

    assert result["answer"] == "# 通用报告"
    assert result["result"]["source"] == "existing_summary"
    assert calls == []


def test_explicit_detail_query_uses_read_only_agent_for_existing_summary(tmp_path, monkeypatch):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(json.dumps({"activity_key": "a1", "fit_path": "/tmp/latest.fit", "markdown_report": "# 通用报告"}), encoding="utf-8")
    calls = []

    def fake_run_activity_analysis_agent(fit_path: str, **kwargs):
        calls.append((fit_path, kwargs))
        return {"activity_key": "a1", "fit_path": fit_path, "summary_path": str(summary), "markdown_report": "# 短冲刺检查", "status": "analyzed_query", "agent": "ActivityAnalysisAgent"}

    monkeypatch.setattr("agent.activity.report.run_activity_analysis_agent", fake_run_activity_analysis_agent)
    context = AgentContext(session_id="targeted-question-test", selected_activities=[{"activity_key": "a1", "summary_path": str(summary)}])

    result = query_selected_activity_detail_tool(context, question="检查 100-200 秒是否有短冲刺")

    assert result["answer"] == "# 短冲刺检查"
    assert result["result"]["source"] == "targeted_query"
    assert calls == [("/tmp/latest.fit", {"user_request": "检查 100-200 秒是否有短冲刺", "persist": False})]


def test_show_selected_activity_report_reports_missing_summary():
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[{"activity_key": "a1"}],
    )

    result = show_selected_activity_report_tool(context)

    assert result["error"] == "missing_activity_summary"


def test_range_summary_uses_existing_reports_without_calling_fit_analysis(tmp_path, monkeypatch):
    summary = tmp_path / "morning.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_path": "/tmp/morning.fit",
                "markdown_report": "# 晨骑报告",
                "history_entry": {"summary_label": "晨骑", "duration_min": 25, "distance_km": 9.5},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent.main_agent.handlers.analyze_fit_file_tool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("existing summary must not analyze FIT")),
    )
    context = AgentContext(
        session_id="range-summary-test",
        selected_activities=[{
            "activity_key": "a1",
            "fit_path": "/tmp/morning.fit",
            "summary_path": str(summary),
            "start_time_local": "2026-05-19T08:00:00",
            "duration_min": 25,
            "distance_km": 9.5,
        }],
        selected_activity_range={"type": "recent_activities", "limit": 1, "time_of_day": "morning"},
    )

    result = execute_summarize_activity_range("summarize_activities", {}, context)

    assert result["status"] == "completed"
    assert result["result"]["summary_generation"]["skipped_count"] == 1
    assert result["result"]["summary_generation"]["generated_count"] == 0


def test_show_selected_activity_report_generates_summary_when_fit_exists(monkeypatch):
    calls: list[tuple[str, bool, str]] = []

    def fake_run_activity_analysis_agent(fit_path: str, *, force: bool = False, user_request: str = ""):
        calls.append((fit_path, force, user_request))
        return {
            "activity_key": "a1",
            "fit_path": fit_path,
            "summary_path": "data/summaries/latest.summary.json",
            "markdown_report": "# 新生成报告\n\n文件分析完成。",
            "status": "analyzed",
            "agent": "ActivityAnalysisAgent",
            "history_entry": {"summary_label": "高功率区间"},
        }

    monkeypatch.setattr("agent.activity.report.run_activity_analysis_agent", fake_run_activity_analysis_agent)
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[{"activity_key": "a1", "fit_path": "/tmp/latest.fit"}],
    )

    result = show_selected_activity_report_tool(context, args={"force": True, "user_request": "看功率"})

    assert result["status"] == "completed"
    assert result["answer"].startswith("# 新生成报告")
    assert result["result"]["source"] == "generated_summary"
    assert result["result"]["agent"] == "ActivityAnalysisAgent"
    assert calls == [("/tmp/latest.fit", True, "看功率")]
    assert str(context.current_fit_file) == "/tmp/latest.fit"


def test_show_selected_activity_report_force_refreshes_existing_summary(tmp_path, monkeypatch):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_path": "/tmp/latest.fit",
                "markdown_report": "# 旧报告",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, bool, str]] = []

    def fake_run_activity_analysis_agent(fit_path: str, *, force: bool = False, user_request: str = ""):
        calls.append((fit_path, force, user_request))
        return {
            "activity_key": "a1",
            "fit_path": fit_path,
            "summary_path": str(summary),
            "markdown_report": "# 刷新报告\n\n已重新分析。",
            "status": "analyzed",
            "agent": "ActivityAnalysisAgent",
            "history_entry": {"summary_label": "刷新"},
        }

    monkeypatch.setattr("agent.activity.report.run_activity_analysis_agent", fake_run_activity_analysis_agent)
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[{"activity_key": "a1", "summary_path": str(summary)}],
    )

    result = show_selected_activity_report_tool(context, args={"force": True, "user_request": "重新分析"})

    assert result["status"] == "completed"
    assert result["answer"].startswith("# 刷新报告")
    assert result["result"]["source"] == "generated_summary"
    assert calls == [("/tmp/latest.fit", True, "重新分析")]



def test_show_selected_activity_report_returns_analysis_agent_error(monkeypatch):
    def fake_run_activity_analysis_agent(fit_path: str, *, force: bool = False, user_request: str = ""):
        return {
            "fit_path": fit_path,
            "markdown_report": "# 活动分析暂时不可用\n\n内部分析超时。",
            "status": "analysis_error",
            "agent": "ActivityAnalysisAgent",
            "analysis_error": {"type": "RuntimeError", "message": "timeout"},
            "history_entry": {},
        }

    monkeypatch.setattr("agent.activity.report.run_activity_analysis_agent", fake_run_activity_analysis_agent)
    context = AgentContext(
        session_id="activity-report-test",
        selected_activities=[{"activity_key": "a1", "fit_path": "/tmp/latest.fit"}],
    )

    result = show_selected_activity_report_tool(context, args={"user_request": "分析"})

    assert result["status"] == "completed"
    assert result["result"]["source"] == "analysis_agent_error"
    assert result["result"]["analysis_error"]["type"] == "RuntimeError"
