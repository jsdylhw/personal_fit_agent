from __future__ import annotations

import pytest

from agent.tools import agent_workflow_tool_catalog, call_fit_analysis_tool, fit_data_tool_catalog
from core.data_tools import (
    DEFAULT_SECTIONS,
    SUMMARY_SECTIONS,
    _normalize_summary_sections,
    get_activity_overview_tool,
    get_activity_summary_tool,
)
from core.file_workflow import (
    _extract_json_object,
    analyze_fit_file,
    build_initial_loop_payload,
    choose_strava_summary_tone,
    normalize_history_entry,
)
from core.stats import (
    _normalize_bucket_distance_m,
    _normalize_bucket_seconds,
    _round_float,
    _seconds_to_minutes,
    prune_empty_values,
)


class TestRoundFloat:
    def test_round_number(self):
        assert _round_float(3.14159, 2) == 3.14

    def test_round_none_returns_none(self):
        assert _round_float(None) is None

    def test_round_string_number(self):
        assert _round_float("3.14", 1) == 3.1

    def test_round_invalid_string(self):
        assert _round_float("abc") is None


class TestPruneEmptyValues:
    def test_removes_none_values(self):
        assert prune_empty_values({"a": 1, "b": None}) == {"a": 1}

    def test_removes_empty_dict(self):
        assert prune_empty_values({"a": 1, "b": {}}) == {"a": 1}

    def test_removes_empty_list(self):
        assert prune_empty_values({"a": 1, "b": []}) == {"a": 1}

    def test_keeps_zero_and_false(self):
        assert prune_empty_values({"a": 0, "b": False, "c": ""}) == {"a": 0, "b": False, "c": ""}

    def test_nested_pruning(self):
        result = prune_empty_values({"a": {"b": None, "c": 1}, "d": [None, {}, 2]})
        assert result == {"a": {"c": 1}, "d": [2]}

    def test_plain_value_passes_through(self):
        assert prune_empty_values(42) == 42
        assert prune_empty_values("hello") == "hello"


class TestExtractJsonObject:
    def test_plain_json_object(self):
        result = _extract_json_object('{"action": "final", "markdown_report": "hi"}')
        assert result["action"] == "final"

    def test_json_in_markdown_fence(self):
        text = '```json\n{"action": "tool", "tool": "get_history"}\n```'
        result = _extract_json_object(text)
        assert result["action"] == "tool"

    def test_json_with_surrounding_text(self):
        text = 'Some prefix text {"action": "final"} trailing text'
        result = _extract_json_object(text)
        assert result["action"] == "final"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _extract_json_object("not json at all {broken")

    def test_array_raises(self):
        with pytest.raises(RuntimeError, match="JSON object"):
            _extract_json_object("[1, 2, 3]")


class TestNormalizeBucketSeconds:
    def test_valid_value(self):
        assert _normalize_bucket_seconds(30) == 30

    def test_below_minimum_clamps_to_1(self):
        assert _normalize_bucket_seconds(0) == 1
        assert _normalize_bucket_seconds(-5) == 1

    def test_above_maximum_clamps_to_600(self):
        assert _normalize_bucket_seconds(1000) == 600

    def test_invalid_input_defaults_to_60(self):
        assert _normalize_bucket_seconds("abc") == 60

    def test_none_defaults_to_60(self):
        assert _normalize_bucket_seconds(None) == 60


class TestNormalizeBucketDistance:
    def test_exact_allowed_value(self):
        assert _normalize_bucket_distance_m(1000) == 1000
        assert _normalize_bucket_distance_m(3000) == 3000

    def test_rounds_to_nearest_allowed(self):
        assert _normalize_bucket_distance_m(900) == 1000
        assert _normalize_bucket_distance_m(2500) == 3000

    def test_invalid_defaults_to_1000(self):
        assert _normalize_bucket_distance_m("abc") == 1000

    def test_float_conversion(self):
        assert _normalize_bucket_distance_m("500.0") == 500


class TestNormalizeSummarySections:
    def test_empty_returns_defaults(self):
        result = _normalize_summary_sections(None)
        assert len(result) == len(DEFAULT_SECTIONS)
        assert "activity_identity" in result
        assert "training_zones" not in result  # not in defaults

    def test_all_returns_all(self):
        result = _normalize_summary_sections("all")
        assert len(result) == len(SUMMARY_SECTIONS)
        assert "training_zones" in result

    def test_specific_sections(self):
        result = _normalize_summary_sections(["power", "heart_rate"])
        assert result == ["power", "heart_rate"]

    def test_invalid_section_filtered_out(self):
        result = _normalize_summary_sections(["power", "nonexistent"])
        assert result == ["power"]

    def test_comma_string(self):
        result = _normalize_summary_sections("power, heart_rate")
        assert result == ["power", "heart_rate"]


class TestSecondsToMinutes:
    def test_conversion(self):
        assert _seconds_to_minutes(60) == 1.0
        assert _seconds_to_minutes(90) == 1.5

    def test_none_returns_none(self):
        assert _seconds_to_minutes(None) is None


class TestChooseStravaSummaryTone:
    def test_returns_dict_without_weight(self):
        tone = choose_strava_summary_tone()
        assert isinstance(tone, dict)
        assert "name" in tone
        assert "description" in tone
        assert "weight" not in tone

    def test_name_is_valid(self):
        valid_names = {"training_log", "professional_coach", "minimal_brief", "soft_catgirl"}
        tone = choose_strava_summary_tone()
        assert tone["name"] in valid_names


class TestFitAnalysisToolCatalog:
    def test_data_catalog_has_only_5_readonly_tools(self):
        """Hidden tool loop 只能看到 5 个只读数据工具,不能看到副作用工具."""
        tools = fit_data_tool_catalog()
        tool_names = {t["name"] for t in tools}
        assert tool_names == {
            "get_activity_overview", "get_activity_summary",
            "get_time_intervals", "get_distance_intervals", "get_history",
        }

    def test_agent_catalog_has_all_11_tools(self):
        """Agent 模式可以看到 数据查询 + 活动发现 + 下载/分析/上传."""
        tools = agent_workflow_tool_catalog()
        tool_names = {t["name"] for t in tools}
        assert tool_names == {
            "get_activity_overview", "get_activity_summary",
            "get_time_intervals", "get_distance_intervals", "get_history",
            "list_activities", "resolve_activity", "get_activities_in_range",
            "sync_garmin_activities", "analyze_fit_file", "upload_to_strava",
        }

    def test_no_side_effect_tools_in_data_catalog(self, sample_parsed_fit):
        """确认 sync/upload 不在 data catalog 中,analyze-file 不会触发副作用."""
        data_tools = {t["name"] for t in fit_data_tool_catalog()}
        assert "sync_garmin_activities" not in data_tools
        assert "upload_to_strava" not in data_tools
        assert "analyze_fit_file" not in data_tools

    def test_each_tool_has_description(self):
        for tool in fit_data_tool_catalog():
            assert "description" in tool
            assert len(tool["description"]) > 0


class TestWorkflowAgentCliRunner:
    def test_workflow_agent_exposes_all_11_tools_without_fit(self, tmp_path, monkeypatch):
        """终端 agent 模式首轮 payload 应暴露完整 11 工具 catalog."""
        from agent.workflow_chat import run_workflow_agent

        captured: dict[str, object] = {}

        class FakeClient:
            def create_messages(self, **kwargs):
                captured.update(kwargs)
                return {
                    "model": "fake-model",
                    "content": [
                        {
                            "type": "text",
                            "text": '{"action":"final","answer":"你好,我可以帮你下载、分析或上传 FIT。"}',
                        }
                    ],
                }

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agent.workflow_chat.AnthropicMessagesClient", lambda: FakeClient())

        result = run_workflow_agent("你好", max_steps=1)

        assert "下载、分析或上传" in result["answer"]
        messages = captured["messages"]
        payload = _extract_json_object(messages[0]["content"])
        tool_names = {tool["name"] for tool in payload["available_tools"]}
        assert tool_names == {
            "get_activity_overview", "get_activity_summary",
            "get_time_intervals", "get_distance_intervals", "get_history",
            "list_activities", "resolve_activity", "get_activities_in_range",
            "sync_garmin_activities", "analyze_fit_file", "upload_to_strava",
        }
        assert result["log_path"].startswith("log/")

    def test_workflow_agent_infers_fit_file_from_message(self, tmp_path, monkeypatch, sample_parsed_fit):
        """用户只写文件 stem 时,agent 也应把本地 FIT 识别为 current_fit_file."""
        from agent.workflow_chat import run_workflow_agent

        fit_file = tmp_path / "594588818_ACTIVITY.fit"
        fit_file.write_bytes(b"mock fit")
        captured: dict[str, object] = {}

        class FakeClient:
            def create_messages(self, **kwargs):
                captured.update(kwargs)
                return {
                    "model": "fake-model",
                    "content": [
                        {
                            "type": "text",
                            "text": '{"action":"final","answer":"已识别当前 FIT,会优先用数据工具分析。"}',
                        }
                    ],
                }

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agent.workflow_chat.parse_fit", lambda path: sample_parsed_fit)
        monkeypatch.setattr("agent.workflow_chat.query_activity_history", lambda **kwargs: None)
        monkeypatch.setattr("agent.workflow_chat.AnthropicMessagesClient", lambda: FakeClient())

        result = run_workflow_agent("分析594588818_ACTIVITY这个fit文件，生成报告", max_steps=1)

        assert result["current_fit_file"] == str(fit_file.resolve())
        messages = captured["messages"]
        payload = _extract_json_object(messages[0]["content"])
        assert payload["current_fit_file"] == str(fit_file.resolve())
        assert payload["current_fit_source"] == "argument_or_message_match"

    def test_workflow_agent_updates_current_fit_after_resolve_activity(self, tmp_path, monkeypatch, sample_parsed_fit):
        """resolve_activity 返回 fit_path 后,后续轮次应从 AgentContext 读取 current_fit_file."""
        from agent.workflow_chat import run_workflow_agent

        fit_file = tmp_path / "resolved.fit"
        fit_file.write_bytes(b"mock fit")
        captured_messages: list[list[dict[str, object]]] = []

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def create_messages(self, **kwargs):
                self.calls += 1
                captured_messages.append(list(kwargs["messages"]))
                if self.calls == 1:
                    text = '{"action":"tool","tool":"resolve_activity","arguments":{"date_local":"2026-05-14"}}'
                else:
                    text = '{"action":"final","answer":"已切换到解析出的活动。"}'
                return {
                    "model": "fake-model",
                    "content": [{"type": "text", "text": text}],
                }

        def fake_call_tool(name, arguments, *, parsed=None, history_before=None):
            assert name == "resolve_activity"
            return {
                "tool": name,
                "arguments": arguments,
                "result": {
                    "activity": {
                        "activity_key": "abc123",
                        "fit_path": str(fit_file),
                        "summary_path": str(tmp_path / "resolved.summary.json"),
                    }
                },
            }

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agent.workflow_chat.call_fit_analysis_tool", fake_call_tool)
        monkeypatch.setattr("agent.workflow_chat.parse_fit", lambda path: sample_parsed_fit)
        monkeypatch.setattr("agent.workflow_chat.query_activity_history", lambda **kwargs: None)
        monkeypatch.setattr("agent.workflow_chat.AnthropicMessagesClient", lambda: FakeClient())

        result = run_workflow_agent("分析 2026-05-14 的活动", max_steps=2)

        assert result["current_fit_file"] == str(fit_file.resolve())
        second_payload = _extract_json_object(captured_messages[1][-1]["content"])
        assert second_payload["current_fit_file"] == str(fit_file.resolve())
        assert "已切换" in result["answer"]


class TestActivityIndex:
    def test_upsert_and_resolve_activity_from_fit(self, tmp_path, monkeypatch, sample_parsed_fit):
        from core.activity_index import (
            get_activities_in_range,
            list_activities,
            resolve_activity,
            upsert_activity_from_fit,
        )

        fit_file = tmp_path / "ride.fit"
        fit_file.write_bytes(b"mock fit")
        index_path = tmp_path / "data" / "activity_index.json"
        monkeypatch.setattr("core.activity_index.parse_fit", lambda path: sample_parsed_fit)

        entry = upsert_activity_from_fit(fit_file, path=index_path)

        assert entry["file_name"] == "ride.fit"
        assert entry["date_local"] == "2026-05-14"
        listed = list_activities(path=index_path)
        assert listed["count"] == 1
        resolved = resolve_activity(date_local="2026-05-14", path=index_path)
        assert resolved["matched_count"] == 1
        assert resolved["activity"]["fit_path"] == str(fit_file.resolve())
        ranged = get_activities_in_range(start_date="2026-05-01", end_date="2026-05-31", path=index_path)
        assert ranged["count"] == 1
        assert ranged["totals"]["distance_km"] == 5.0


class TestCallFitAnalysisTool:
    def test_unknown_tool_returns_error(self, sample_parsed_fit):
        result = call_fit_analysis_tool("nonexistent_tool", {}, parsed=sample_parsed_fit, history_before=None)
        assert result["error"] == "unknown_tool"

    def test_get_activity_overview(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_activity_overview", {}, parsed=sample_parsed_fit, history_before=None)
        assert result["tool"] == "get_activity_overview"
        overview = result["result"]
        assert overview["activity_identity"]["sport_type"] == "cycling"
        assert overview["scale"]["duration_min"] is not None

    def test_get_activity_summary(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_activity_summary", {"sections": ["power"]}, parsed=sample_parsed_fit, history_before=None)
        assert "result" in result
        assert "power" in result["result"]

    def test_get_time_intervals(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_time_intervals", {"bucket_seconds": 60}, parsed=sample_parsed_fit, history_before=None)
        assert result["result"]["available"] is True

    def test_get_distance_intervals(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_distance_intervals", {"bucket_distance_m": 1000}, parsed=sample_parsed_fit, history_before=None)
        assert result["result"]["available"] is True

    def test_get_history_disabled(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_history", {}, parsed=sample_parsed_fit, history_before=None)
        assert result["result"]["count"] == 0

    def test_get_history_with_data(self, sample_parsed_fit):
        history = {"schema_version": "v1", "count": 2, "activities": [{"start_time": "2026-05-10T00:00:00+00:00"}]}
        result = call_fit_analysis_tool("get_history", {}, parsed=sample_parsed_fit, history_before=history)
        assert result["result"]["count"] == 2


class TestGetActivityOverviewTool:
    def test_returns_expected_structure(self, sample_parsed_fit):
        result = get_activity_overview_tool(sample_parsed_fit)
        assert result["activity_identity"]["sport_type"] == "cycling"
        assert result["activity_identity"]["start_time_local"] == "2026-05-14T16:00:00"
        assert "start_time_utc" not in result["activity_identity"]
        assert "duration_min" in result["scale"]
        assert "distance_km" in result["scale"]
        assert "total_ascent_m" in result["scale"]
        assert "avg_power_w" in result["basic_metrics"]
        assert "has_power" in result["data_availability"]

    def test_no_records_no_crash(self):
        parsed = {"summary": {}, "sessions": [], "sports": [], "records": [], "laps": [], "training_metadata": {}}
        result = get_activity_overview_tool(parsed)
        assert result["activity_identity"]["sport_type"] is None
        assert result["scale"]["duration_min"] is None


class TestGetActivitySummaryTool:
    def test_all_sections(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections="all")
        assert "activity_identity" in result
        assert "power" in result
        assert "heart_rate" in result
        assert "cadence" in result
        assert "speed" in result
        assert "elevation" in result

    def test_single_section(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections=["power"])
        assert "power" in result
        assert "heart_rate" not in result

    def test_power_section_merged(self, sample_parsed_fit):
        """Power section merges availability + stats + summary."""
        result = get_activity_summary_tool(sample_parsed_fit, sections=["power"])
        power = result["power"]
        assert power["available"] is True
        assert "stats" in power
        assert "summary" in power
        assert power["summary"]["avg_power_w"] is not None

    def test_heart_rate_section_merged(self, sample_parsed_fit):
        """Heart rate section merges availability + stats + summary."""
        result = get_activity_summary_tool(sample_parsed_fit, sections=["heart_rate"])
        hr = result["heart_rate"]
        assert hr["available"] is True
        assert "stats" in hr
        assert "summary" in hr

    def test_cadence_section_merged(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections=["cadence"])
        cad = result["cadence"]
        assert cad["available"] is True
        assert "stats" in cad
        assert "summary" in cad

    def test_speed_section_merged(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections=["speed"])
        spd = result["speed"]
        assert spd["available"] is True
        assert "stats" in spd
        assert "summary" in spd

    def test_elevation_section_merged(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections=["elevation"])
        elev = result["elevation"]
        assert elev["available"] is True
        assert "summary" in elev
        assert elev["summary"]["total_ascent_m"] is not None

    def test_power_unavailable(self):
        parsed = {"summary": {"has_power": False}, "records": [], "sessions": [], "training_metadata": {}}
        result = get_activity_summary_tool(parsed, sections=["power"])
        assert result["power"]["available"] is False

    def test_hr_unavailable(self):
        parsed = {"summary": {"has_heart_rate": False}, "records": [], "sessions": [], "training_metadata": {}}
        result = get_activity_summary_tool(parsed, sections=["heart_rate"])
        assert result["heart_rate"]["available"] is False


class TestNormalizeHistoryEntry:
    def test_fills_default_fields(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        entry = {}
        result = normalize_history_entry(entry, path=fit_path, parsed=sample_parsed_fit)
        assert result["activity_key"] is not None
        assert result["schema_version"] == "llm_activity_history_entry.v1"
        assert result["sport_type"] == "cycling"
        assert result["start_time"] == "2026-05-14T16:00:00"
        assert result["start_time_local"] == "2026-05-14T16:00:00"

    def test_preserves_existing_fields(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        entry = {"brief": "自定义笔记", "custom_field": "keep_me"}
        result = normalize_history_entry(entry, path=fit_path, parsed=sample_parsed_fit)
        assert result["brief"] == "自定义笔记"
        assert result["custom_field"] == "keep_me"

    def test_strips_timezone_from_llm_history_time(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        entry = {"start_time": "2026-05-14T16:00:00+08:00"}
        result = normalize_history_entry(entry, path=fit_path, parsed=sample_parsed_fit)
        assert result["start_time"] == "2026-05-14T16:00:00"
        assert result["start_time_local"] == "2026-05-14T16:00:00"


# -- 安全测试:strict bool / 上传错误状态 / sync count 上限 -----------------

class TestBuildInitialLoopPayload:
    def test_llm_payload_only_exposes_local_start_time(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        payload = build_initial_loop_payload(
            fit_path,
            sample_parsed_fit,
            history_before=None,
            strava_summary_tone={"name": "minimal_brief", "description": "test"},
        )
        fit_summary = payload["fit_summary"]
        assert fit_summary["start_time_local"] == "2026-05-14T16:00:00"
        assert "start_time" not in fit_summary
        assert "start_time_utc" not in fit_summary
        assert "timezone_note" not in fit_summary


class TestAnalyzeFitFileResultTimes:
    def test_result_fit_summary_uses_only_local_time(
        self, sample_parsed_fit, tmp_path, monkeypatch
    ):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("core.file_workflow.parse_fit", lambda path: sample_parsed_fit)
        monkeypatch.setattr(
            "core.file_workflow.query_activity_history",
            lambda **kwargs: {
                "schema_version": "file_training_history.v1",
                "count": 1,
                "activities": [
                    {
                        "start_time": "2026-05-13T00:00:00+00:00",
                        "start_time_local": "2026-05-13T08:00:00+08:00",
                    }
                ],
            },
        )
        monkeypatch.setattr(
            "core.file_workflow.analyze_with_llm",
            lambda path, parsed, history_before: {
                "model": "test-model",
                "markdown_report": "# Report",
                "strava_summary": "summary",
                "history_entry": {},
            },
        )

        result = analyze_fit_file(fit_path, use_history=True, update_history=False, force=True)

        assert result["fit_summary"]["start_time_local"] == "2026-05-14T16:00:00"
        assert "start_time" not in result["fit_summary"]
        assert "start_time_utc" not in result["fit_summary"]
        assert "timezone_note" not in result["fit_summary"]
        history_activity = result["history_before"]["activities"][0]
        assert history_activity["start_time_local"] == "2026-05-13T08:00:00"
        assert "start_time" not in history_activity


class TestStrictBool:
    def test_true_is_true(self):
        from core.workflow_tools import _parse_strict_bool
        assert _parse_strict_bool(True) is True

    def test_false_is_false(self):
        from core.workflow_tools import _parse_strict_bool
        assert _parse_strict_bool(False) is False

    def test_string_false_is_false(self):
        """字符串 'false' 不会被 bool() 误判为 True."""
        from core.workflow_tools import _parse_strict_bool
        assert _parse_strict_bool("false") is False

    def test_string_true_is_false(self):
        from core.workflow_tools import _parse_strict_bool
        assert _parse_strict_bool("true") is False

    def test_none_is_default(self):
        from core.workflow_tools import _parse_strict_bool
        assert _parse_strict_bool(None) is False

    def test_number_one_is_false(self):
        """数字 1 也不是 True."""
        from core.workflow_tools import _parse_strict_bool
        assert _parse_strict_bool(1) is False


class TestSyncCountLimit:
    def test_count_capped(self):
        from core.workflow_tools import sync_garmin_activities_tool
        # 只测 count 上限逻辑,不实际调用 Garmin(会因无凭证报错)
        from core.workflow_tools import MAX_SYNC_COUNT
        assert MAX_SYNC_COUNT == 20


class TestUploadErrorStates:
    def test_no_summary(self):
        from core.workflow_tools import upload_to_strava_tool
        result = upload_to_strava_tool("/tmp/nonexistent_activity.fit")
        assert result["error"] == "no_summary"

    def test_string_confirmed_does_not_upload(self, tmp_path, monkeypatch):
        """防御层:即使直接传 confirmed="true",内部用 _parse_strict_bool 转为 False.

        用临时 summary 文件 + mock StravaSink 验证不会调 upload_fit.
        """
        import json
        from unittest.mock import MagicMock
        from core.workflow_tools import upload_to_strava_tool

        # 创建临时 summary
        fit_file = tmp_path / "test.fit"
        fit_file.write_bytes(b"mock")
        summary_dir = tmp_path / "data" / "summaries"
        summary_dir.mkdir(parents=True)
        summary = {
            "strava_summary": "测试总结",
            "fit_summary": {"sport_type": "cycling", "start_time_local": "2026-05-15T08:00:00+08:00"},
            "activity_key": "abc123",
        }
        (summary_dir / "test.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False), encoding="utf-8"
        )

        # 让 upload_to_strava_tool 在 tmp_path/data/summaries 找 summary
        monkeypatch.chdir(tmp_path)

        # mock StravaSink(lazy import 在 sinks.strava)
        mock_sink = MagicMock()
        mock_sink_cls = MagicMock(return_value=mock_sink)
        monkeypatch.setattr("sinks.strava.StravaSink", mock_sink_cls)

        result = upload_to_strava_tool(str(fit_file), confirmed="true")
        # 字符串 "true" 被 _parse_strict_bool 转成 False,应走确认流程
        assert result["action_required"] == "confirm_upload"
        # StravaSink 从未被实例化
        mock_sink_cls.assert_not_called()

    def test_true_confirmed_proceeds(self, tmp_path, monkeypatch):
        """Python True 正常触发上传."""
        import json
        from unittest.mock import MagicMock
        from core.workflow_tools import upload_to_strava_tool

        fit_file = tmp_path / "test.fit"
        fit_file.write_bytes(b"mock")
        summary_dir = tmp_path / "data" / "summaries"
        summary_dir.mkdir(parents=True)
        summary = {
            "strava_summary": "测试总结",
            "fit_summary": {"sport_type": "cycling", "start_time_local": "2026-05-15T08:00:00+08:00"},
            "activity_key": "abc123",
        }
        (summary_dir / "test.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False), encoding="utf-8"
        )

        monkeypatch.chdir(tmp_path)

        mock_sink = MagicMock()
        mock_sink.upload_fit.return_value = {"id": 99999}
        mock_sink.wait_for_upload.return_value = {"activity_id": 88888}
        mock_sink_cls = MagicMock(return_value=mock_sink)
        monkeypatch.setattr("sinks.strava.StravaSink", mock_sink_cls)

        result = upload_to_strava_tool(str(fit_file), confirmed=True)
        assert result["status"] == "uploaded"
        assert result["strava_activity_id"] == 88888
