from __future__ import annotations

import json
from pathlib import Path

from agent.context import AgentContext
from agent.workflow.plan_schema import WorkflowPlan, WorkflowPlanStep
from agent.workflow.executor import execute_workflow_plan


def _plan(*steps: WorkflowPlanStep, **kwargs) -> WorkflowPlan:
    return WorkflowPlan(
        task_type=kwargs.pop("task_type", "workflow_execution"),
        steps=list(steps),
        **kwargs,
    )


def test_executor_stops_before_selection_when_validation_fails():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(name="sync_garmin_activities", reason="有副作用但未允许"),
        allow_side_effects=False,
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "validation_failed"
    assert result.selection is None
    assert result.step_results == []


def test_executor_runs_activity_resolution_without_output_step():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
        current_activity_key="activity-1",
    )
    plan = _plan(
        WorkflowPlanStep(name="resolve_current_activity", reason="使用当前活动"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert [step.step_name for step in result.step_results] == [
        "resolve_current_activity",
    ]
    assert context.selected_activities[0]["activity_key"] == "activity-1"
    assert result.final_response is None


def test_executor_analysis_handles_empty_activity_resolution():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(
            name="resolve_activity_by_date",
            reason="定位不存在的活动",
            arguments={"date": "2099-01-01"},
        ),
        WorkflowPlanStep(name="analyze_single_activity", reason="说明空结果"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].status == "completed"
    assert result.step_results[0].result["result"]["matched_count"] == 0
    assert result.final_response is not None
    assert "没有找到符合条件的活动" in result.final_response


def test_executor_analysis_handles_empty_selected_activity():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(
            name="resolve_activity_by_date",
            reason="定位不存在的活动",
            arguments={"date": "2099-01-01"},
        ),
        WorkflowPlanStep(name="analyze_single_activity", reason="分析未找到的活动"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].status == "completed"
    assert result.final_response is not None
    assert "没有找到符合条件的活动" in result.final_response


def test_executor_runs_casual_chat_without_dedicated_handler():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(name="casual_chat", reason="普通问候"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].step_name == "casual_chat"
    assert "你好" in (result.final_response or "")


def test_executor_runs_user_clarification_without_dedicated_handler():
    context = AgentContext(session_id="executor-test")
    plan = _plan(
        WorkflowPlanStep(
            name="ask_user_clarification",
            reason="缺少日期范围",
            arguments={"question": "你想分析哪一天的活动？"},
        )
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.final_response == "你想分析哪一天的活动？"


def test_executor_can_use_injected_step_handler():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
    )
    calls = []

    def fake_single_activity_handler(step, context):
        calls.append((step.name, str(context.current_fit_file)))
        return {
            "step": step.name,
            "status": "completed",
            "answer": "活动分析完成",
        }

    result = execute_workflow_plan(
        plan,
        context,
        handlers={"run_single_activity_react_analysis": fake_single_activity_handler},
    )

    assert result.status == "completed"
    assert calls == [("analyze_single_activity", "/tmp/current.fit")]
    assert result.step_results[0].result["answer"] == "活动分析完成"
    assert result.final_response == "活动分析完成"


def test_executor_runs_single_activity_report_from_existing_summary(tmp_path):
    summary = tmp_path / "latest.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_summary": {"start_time_local": "2026-05-18T21:00:00", "sport_type": "cycling"},
                "markdown_report": "# 最新骑行报告\n\n已有报告内容。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/latest.fit"),
        selected_activities=[{"activity_key": "a1", "summary_path": str(summary)}],
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="展示报告"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.final_response is not None
    assert result.final_response.startswith("# 最新骑行报告")


def test_executor_runs_single_activity_analysis_when_summary_missing(monkeypatch):
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
    )

    def fake_analyze_fit_file_tool(fit_path: str, *, force: bool = False):
        return {
            "activity_key": "a1",
            "fit_path": fit_path,
            "summary_path": "/tmp/current.summary.json",
            "markdown_report": "# 新分析报告\n\n分析已完成。",
            "status": "analyzed",
        }

    monkeypatch.setattr("agent.activity.report.analyze_fit_file_tool", fake_analyze_fit_file_tool)

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].status == "completed"
    assert result.final_response is not None
    assert result.final_response.startswith("# 新分析报告")


def test_executor_can_continue_after_step_error_when_requested():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
    )
    plan = _plan(
        WorkflowPlanStep(name="analyze_single_activity", reason="分析当前活动"),
    )

    result = execute_workflow_plan(plan, context, stop_on_error=False)

    assert result.status == "completed"
    assert result.step_results[0].status == "failed"
    assert result.final_response is None


def test_executor_runs_compare_activities_from_existing_summaries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    summary_dir = tmp_path / "data" / "summaries"
    summary_dir.mkdir(parents=True)
    first = summary_dir / "morning.summary.json"
    second = summary_dir / "evening.summary.json"
    first.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_summary": {"start_time_local": "2026-05-18T08:00:00", "sport_type": "cycling"},
                "history_entry": {
                    "summary_label": "晨间轻松骑",
                    "main_stimulus": "低强度耐力",
                    "training_load": "非常轻",
                    "duration_min": 26.9,
                    "distance_km": 9.38,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "activity_key": "a2",
                "fit_summary": {"start_time_local": "2026-05-18T21:00:00", "sport_type": "cycling"},
                "history_entry": {
                    "summary_label": "夜间恢复骑",
                    "main_stimulus": "有氧基础/恢复",
                    "training_load": "极低",
                    "duration_min": 42.8,
                    "distance_km": 15.79,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="executor-test",
        selected_activities=[
            {"activity_key": "a1", "summary_path": str(first)},
            {"activity_key": "a2", "summary_path": str(second)},
        ],
    )
    plan = _plan(
        WorkflowPlanStep(name="compare_activities", reason="对比已有报告"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].step_name == "compare_activities"
    assert result.step_results[0].result["result"]["count"] == 2
    assert result.final_response is not None
    assert "没有重新解析 FIT" in result.final_response


def test_executor_direct_strava_upload_sends_tool_error_to_llm(monkeypatch):
    captured: dict[str, object] = {}

    def fake_upload_to_strava_tool(fit_path: str, *, confirmed: bool = False, force: bool = False):
        captured["upload_call"] = {"fit_path": fit_path, "confirmed": confirmed, "force": force}
        return {"error": "no_summary", "message": "Please analyze the activity first"}

    def fake_analyze_fit_file_tool(*args, **kwargs):
        raise AssertionError("upload step should not analyze FIT")

    class FakeClient:
        def create_message(self, **kwargs):
            captured["llm_payload"] = kwargs
            return {"content": [{"type": "text", "text": "上传失败:缺少 summary。"}]}

    monkeypatch.setattr("agent.workflow.executor.upload_to_strava_tool", fake_upload_to_strava_tool)
    monkeypatch.setattr("agent.workflow.executor.analyze_fit_file_tool", fake_analyze_fit_file_tool)
    monkeypatch.setattr("agent.workflow.executor.AnthropicMessagesClient", lambda: FakeClient())
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
        messages=[{"role": "user", "content": "上传 Strava"}],
    )
    plan = _plan(
        WorkflowPlanStep(name="upload_strava_activity", reason="用户明确要求上传"),
        allow_side_effects=True,
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].status == "completed"
    assert result.step_results[0].result["result"]["upload_result"]["error"] == "no_summary"
    assert result.final_response == "上传失败:缺少 summary。"
    assert captured["upload_call"] == {"fit_path": "/tmp/current.fit", "confirmed": True, "force": False}
    assert "no_summary" in captured["llm_payload"]["user"]


def test_executor_direct_strava_upload_sends_success_to_llm(monkeypatch):
    captured: dict[str, object] = {}

    def fake_upload_to_strava_tool(fit_path: str, *, confirmed: bool = False, force: bool = False):
        captured["upload_call"] = {"fit_path": fit_path, "confirmed": confirmed, "force": force}
        return {"status": "uploaded", "strava_activity_id": 12345}

    class FakeClient:
        def create_message(self, **kwargs):
            captured["llm_payload"] = kwargs
            return {"content": [{"type": "text", "text": "上传成功,Strava 活动 ID 是 12345。"}]}

    monkeypatch.setattr("agent.workflow.executor.upload_to_strava_tool", fake_upload_to_strava_tool)
    monkeypatch.setattr("agent.workflow.executor.AnthropicMessagesClient", lambda: FakeClient())
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
        messages=[{"role": "user", "content": "上传 Strava"}],
    )
    plan = _plan(
        WorkflowPlanStep(
            name="upload_strava_activity",
            reason="用户明确要求上传",
            arguments={"force": True},
        ),
        allow_side_effects=True,
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].result["result"]["upload_result"]["status"] == "uploaded"
    assert result.final_response == "上传成功,Strava 活动 ID 是 12345。"
    assert captured["upload_call"] == {"fit_path": "/tmp/current.fit", "confirmed": True, "force": True}
    assert "12345" in captured["llm_payload"]["user"]


def test_executor_runs_training_load_summary_without_local_answer(tmp_path):
    summary = tmp_path / "activity.summary.json"
    summary.write_text(
        json.dumps(
            {
                "activity_key": "a1",
                "fit_summary": {"start_time_local": "2026-05-18T08:00:00", "sport_type": "cycling"},
                "history_entry": {
                    "summary_label": "耐力骑",
                    "training_load": "TSS 88",
                    "duration_min": 90,
                    "distance_km": 40,
                    "brief": "IF 0.78, TSS 88",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context = AgentContext(
        session_id="executor-test",
        selected_activities=[{"activity_key": "a1", "summary_path": str(summary)}],
    )
    plan = _plan(WorkflowPlanStep(name="summarize_recent_training_load", reason="整理训练负荷"))

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].step_name == "summarize_recent_training_load"
    assert result.step_results[0].result["result"]["totals"]["tss"] == 88.0
    assert result.final_response is None


def test_executor_summarizes_selected_activity_range():
    context = AgentContext(
        session_id="executor-test",
        selected_activities=[
            {
                "activity_index": 1,
                "activity_key": "a1",
                "file_name": "first.fit",
                "start_time_local": "2026-04-01T08:00:00",
                "distance_km": 10.5,
                "duration_min": 30.0,
                "has_summary": False,
            },
            {
                "activity_index": 2,
                "activity_key": "a2",
                "file_name": "second.fit",
                "start_time_local": "2026-04-03T08:00:00",
                "distance_km": 20.0,
                "duration_min": 60.0,
                "summary_label": "周末骑行",
                "has_summary": True,
            },
        ],
        selected_activity_range={
            "type": "date_range",
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
        },
    )
    plan = _plan(
        WorkflowPlanStep(name="summarize_activity_range", reason="汇总上个月活动"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].result["result"]["count"] == 2
    assert result.step_results[0].result["result"]["totals"]["distance_km"] == 30.5
    assert result.final_response is not None
    assert "找到 2 条已索引活动" in result.final_response
    assert "#1" in result.final_response
    assert "周末骑行" in result.final_response


def test_executor_summarizes_range_generates_missing_summary_and_reloads_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing_fit = tmp_path / "missing.fit"
    missing_fit.write_bytes(b"fit")
    existing_summary = tmp_path / "existing.summary.json"
    existing_summary.write_text("{}", encoding="utf-8")
    calls = []

    def fake_analyze_fit_file_tool(fit_path: str, *, force: bool = False):
        calls.append((fit_path, force))
        from core.activity_index import upsert_activity_entry

        upsert_activity_entry({
            "activity_index": 1,
            "activity_key": "a1",
            "fit_path": fit_path,
            "file_name": Path(fit_path).name,
            "start_time_local": "2026-04-01T08:00:00",
            "distance_km": 10.5,
            "duration_min": 30.0,
            "summary_path": "data/summaries/a1.summary.json",
            "has_summary": True,
            "summary_label": "补齐后的报告标签",
        })
        return {"summary_path": "data/summaries/a1.summary.json"}

    monkeypatch.setattr("agent.workflow.executor.analyze_fit_file_tool", fake_analyze_fit_file_tool)
    context = AgentContext(
        session_id="executor-test",
        selected_activities=[
            {
                "activity_index": 1,
                "activity_key": "a1",
                "file_name": "missing.fit",
                "fit_path": str(missing_fit),
                "start_time_local": "2026-04-01T08:00:00",
                "distance_km": 10.5,
                "duration_min": 30.0,
                "has_summary": False,
            },
            {
                "activity_index": 2,
                "activity_key": "a2",
                "file_name": "existing.fit",
                "fit_path": str(tmp_path / "existing.fit"),
                "summary_path": str(existing_summary),
                "summary_label": "已有报告标签",
                "start_time_local": "2026-04-03T08:00:00",
                "distance_km": 20.0,
                "duration_min": 60.0,
                "has_summary": True,
            },
        ],
    )
    plan = _plan(WorkflowPlanStep(name="summarize_activity_range", reason="汇总活动"))

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert calls == [(str(missing_fit), False)]
    generation = result.step_results[0].result["result"]["summary_generation"]
    assert generation["generated_count"] == 1
    assert generation["skipped_count"] == 1
    assert generation["generated"][0]["fit_path"] == str(missing_fit)
    assert generation["generated"][0]["summary_path"] == "data/summaries/a1.summary.json"
    assert context.selected_activities[0]["summary_label"] == "补齐后的报告标签"
    assert "补齐后的报告标签" in (result.final_response or "")
    assert "已有报告标签" in (result.final_response or "")


def test_executor_range_ai_summary_uses_local_report_brief(tmp_path, monkeypatch):
    summary_path = tmp_path / "activity.summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "markdown_report": "# 很长的单活动报告\n这里不应该传给范围总结模型",
                "history_entry": {
                    "summary_label": "夜骑间歇训练",
                    "brief": "43km 夜骑,多组超 FTP 间歇,NP 210W,TSS 114。",
                    "main_stimulus": "间歇爬坡与阈值输出",
                    "training_load": "中等",
                    "quality_notes": ["心率后段明显升高", "功率数据完整"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured = {}

    class FakeClient:
        def create_message(self, **kwargs):
            captured.update(kwargs)
            return {"content": [{"type": "text", "text": "这是 AI 生成的整体总结"}]}

    monkeypatch.setattr("agent.workflow.executor.AnthropicMessagesClient", lambda: FakeClient())
    context = AgentContext(
        session_id="executor-test",
        messages=[{"role": "user", "content": "分析所有活动 生成ai总结报告，详细一点"}],
        selected_activities=[
            {
                "activity_index": 1,
                "activity_key": "a1",
                "file_name": "activity.fit",
                "summary_path": str(summary_path),
                "summary_label": "夜骑间歇训练",
                "start_time_local": "2024-07-26T19:25:13",
                "distance_km": 43.23,
                "duration_min": 111.3,
                "has_summary": True,
            }
        ],
    )
    plan = _plan(
        WorkflowPlanStep(
            name="summarize_activity_range",
            reason="生成 AI 总结报告",
            arguments={"response_mode": "ai_summary", "detail_level": "detailed"},
        )
    )

    result = execute_workflow_plan(plan, context)
    payload = json.loads(captured["user"])

    assert result.final_response == "这是 AI 生成的整体总结"
    assert payload["user_message"] == "分析所有活动 生成ai总结报告，详细一点"
    assert payload["activity_details"][0]["summary_detail"]["brief"].startswith("43km 夜骑")
    assert payload["activity_details"][0]["summary_detail"]["quality_notes"] == ["心率后段明显升高", "功率数据完整"]
    assert "markdown_report" not in json.dumps(payload, ensure_ascii=False)


def test_executor_summarizes_empty_activity_range():
    context = AgentContext(
        session_id="executor-test",
    )
    plan = _plan(
        WorkflowPlanStep(
            name="resolve_activity_range",
            reason="定位没有活动的时间范围",
            arguments={"start_date": "2099-04-01", "end_date": "2099-04-30"},
        ),
        WorkflowPlanStep(name="summarize_activity_range", reason="汇总上个月活动"),
    )

    result = execute_workflow_plan(plan, context)

    assert result.status == "completed"
    assert result.step_results[0].status == "completed"
    assert result.final_response is not None
    assert "没有找到已索引的活动" in result.final_response


def test_executor_serializes_result():
    context = AgentContext(
        session_id="executor-test",
        current_fit_file=Path("/tmp/current.fit"),
        current_activity_key="activity-1",
    )
    plan = _plan(
        WorkflowPlanStep(name="resolve_current_activity", reason="使用当前活动"),
    )

    data = execute_workflow_plan(plan, context).to_dict()

    assert data["status"] == "completed"
    assert data["validation"]["valid"] is True
    assert data["selection"]["valid"] is True
    assert data["step_results"][0]["step_name"] == "resolve_current_activity"
