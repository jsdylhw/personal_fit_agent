from __future__ import annotations

import json

from evaluation.graders import grade_case
from evaluation.report import summarize_results, write_report
from evaluation.runner import run_case, run_suite
from evaluation.schema import EvalCase, EvalCaseError, load_cases


def test_load_cases_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "cases.jsonl"
    row = {"case_id": "same", "input": "你好", "mode": "router", "expected": {"intent": "chat"}}
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False), encoding="utf-8")

    try:
        load_cases(path)
    except EvalCaseError as exc:
        assert "duplicate case_id" in str(exc)
    else:
        raise AssertionError("duplicate IDs must be rejected")


def test_router_suite_loads_regression_cases_and_grader_reports_mismatch():
    results = run_suite("evaluation/cases/router.jsonl", mode="router")
    by_id = {result["case"]["case_id"]: result for result in results}

    assert len(results) == 14
    assert by_id["chat_friend_memory"]["grade"]["passed"] is True
    mismatch = run_case(EvalCase.from_dict({
        "case_id": "synthetic-mismatch",
        "input": "你好",
        "mode": "router",
        "expected": {"intent": "upload"},
    }))
    assert mismatch["grade"]["passed"] is False
    assert "intent expected" in mismatch["grade"]["failures"][0]


def test_tool_grader_supports_argument_constraints_and_completion():
    case = EvalCase.from_dict({
        "case_id": "tool-grade",
        "input": "sync",
        "mode": "live",
        "expected": {
            "required_tools": [{
                "name": "sync_and_run_activity_workflow",
                "arguments": {"count": 3, "goals": {"contains": "upload_strava"}},
            }],
            "forbidden_tools": ["run_activity_workflow"],
            "completion": {
                "result_status": "completed",
                "tool_results": [{
                    "name": "sync_and_run_activity_workflow", "path": "status", "equals": "completed",
                }],
            },
        },
    })
    trace = {
        "elapsed_ms": 12,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "tool_calls": [{
            "name": "sync_and_run_activity_workflow",
            "arguments": {"count": 3, "goals": ["ensure_summary", "upload_strava"]},
            "output": {"status": "completed"},
            "success": True,
        }],
    }

    grade = grade_case(
        case,
        result={"status": "completed", "intent": "mixed", "answer": "done"},
        trace=trace,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
        cache_write_price_per_million=1.0,
        cache_read_price_per_million=0.1,
    )

    assert grade["passed"] is True
    assert grade["scores"]["tool_selection"] == 1.0
    assert grade["scores"]["task_completion"] == 1.0
    assert grade["estimated_cost_usd"] == 0.00014


def test_live_runner_uses_sandbox_and_captures_tool_trace():
    case = EvalCase.from_dict({
        "case_id": "safe-live",
        "input": "同步最近三个活动",
        "mode": "live",
        "expected": {
            "intent": "sync",
            "required_tools": [{"name": "sync_garmin_activities", "arguments": {"count": 3}}],
            "completion": {"result_status": "completed"},
        },
    })

    class FakeClient:
        def __init__(self):
            self.responses = iter([
                {
                    "content": [{
                        "type": "tool_use", "id": "tu-sync", "name": "sync_garmin_activities", "input": {"count": 3},
                    }],
                    "stop_reason": "tool_use",
                },
                {"content": [{"type": "text", "text": "同步完成"}], "stop_reason": "end_turn"},
            ])

        def create_messages(self, **kwargs):
            return next(self.responses)

    result = run_case(case, client=FakeClient())

    assert result["grade"]["passed"] is True
    call = result["trace"]["tool_calls"][0]
    assert call["name"] == "sync_garmin_activities"
    assert call["output"]["downloaded"] == 2


def test_report_writes_jsonl_summary_and_markdown(tmp_path):
    cases = load_cases("evaluation/cases/router.jsonl")[:2]
    results = [run_case(case) for case in cases]

    artifact = write_report(results, output_dir=tmp_path / "report")

    assert artifact["summary"]["case_runs"] == 2
    assert artifact["summary"]["metric_coverage"]["intent_accuracy"] == 2
    assert (tmp_path / "report" / "results.jsonl").exists()
    assert (tmp_path / "report" / "summary.json").exists()
    report = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "Tool selection" not in report  # metric names stay machine-stable
    assert "intent_accuracy" in report
    assert summarize_results(results)["pass_rate"] == 1.0
