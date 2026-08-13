from agent.main_agent.hooks import _format_tool_args, _summarize_output


def test_tool_logging_uses_business_labels_for_morning_range_summary():
    find_block = {"name": "resolve_activities", "input": {"kind": "recent", "limit": 3, "time_of_day": "morning"}}

    assert _format_tool_args(find_block) == "最近活动 · 3 条 · 上午"
    assert _format_tool_args({"name": "summarize_activities", "input": {}}) == "读取已有报告，缺失时补齐后汇总"
    assert _format_tool_args({"name": "calculate_history_metrics", "input": {"group_by": "month"}}) == "读取结构化指标 · 按 month 聚合"


def test_tool_logging_renders_explicit_date_scope():
    block = {"name": "resolve_activities", "input": {"kind": "date", "date": "today", "time_of_day": "morning", "sport_type": "Ride"}}

    assert _format_tool_args(block) == "指定日期 · 上午 · 今天 · Ride"


def test_tool_logging_identifies_report_source_and_activities():
    find_output = {
        "result": {
            "count": 1,
            "activities": [{"start_time_local": "2026-05-19T08:00:00", "file_name": "morning.fit"}],
        }
    }
    assert _summarize_output("resolve_activities", find_output) == "找到 1 条活动：2026-05-19T08:00:00 morning.fit"
    assert _summarize_output("analyze_activity", {"result": {"source": "existing_summary"}}) == "已读取已有报告"
