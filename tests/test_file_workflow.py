from __future__ import annotations

import pytest

from core.file_workflow import (
    _extract_json_object,
    _normalize_bucket_distance_m,
    _normalize_bucket_seconds,
    _normalize_summary_sections,
    _round_float,
    SUMMARY_SECTIONS,
    _seconds_to_minutes,
    call_fit_analysis_tool,
    choose_strava_summary_tone,
    fit_analysis_tool_catalog,
    get_activity_overview_tool,
    get_activity_summary_tool,
    get_distance_intervals_tool,
    get_sampled_records_tool,
    get_time_intervals_tool,
    normalize_history_entry,
    prune_empty_values,
)
from core.history import query_activity_history


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
    def test_all_returns_all_sections(self):
        result = _normalize_summary_sections("all")
        assert len(result) == len(SUMMARY_SECTIONS)

    def test_empty_returns_defaults(self):
        result = _normalize_summary_sections(None)
        assert "activity_identity" in result
        assert "training_zones" not in result  # not in defaults

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
    def test_returns_all_tools(self):
        tools = fit_analysis_tool_catalog()
        tool_names = {t["name"] for t in tools}
        assert "get_activity_overview" in tool_names
        assert "get_activity_summary" in tool_names
        assert "get_time_intervals" in tool_names
        assert "get_distance_intervals" in tool_names
        assert "get_history" in tool_names

    def test_each_tool_has_description(self):
        for tool in fit_analysis_tool_catalog():
            assert "description" in tool
            assert len(tool["description"]) > 0


class TestCallFitAnalysisTool:
    def test_unknown_tool_returns_error(self, sample_parsed_fit):
        result = call_fit_analysis_tool("nonexistent_tool", {}, parsed=sample_parsed_fit, history_before=None)
        assert result["error"] == "unknown_tool"

    def test_get_activity_overview(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_activity_overview", {}, parsed=sample_parsed_fit, history_before=None)
        assert result["tool"] == "get_activity_overview"
        assert "result" in result
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
        assert result["result"]["mode"] == "time"

    def test_get_time_intervals_with_window(self, sample_parsed_fit):
        result = call_fit_analysis_tool(
            "get_time_intervals", {"bucket_seconds": 30, "start_s": 100, "end_s": 200}, parsed=sample_parsed_fit, history_before=None
        )
        assert result["result"]["available"] is True

    def test_get_distance_intervals(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_distance_intervals", {"bucket_distance_m": 1000}, parsed=sample_parsed_fit, history_before=None)
        assert result["result"]["available"] is True
        assert result["result"]["mode"] == "distance"

    def test_get_history_disabled(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_history", {}, parsed=sample_parsed_fit, history_before=None)
        assert result["result"]["count"] == 0

    def test_get_history_with_data(self, sample_parsed_fit):
        history = {"schema_version": "v1", "count": 2, "activities": [{"start_time": "2026-05-10T00:00:00+00:00"}]}
        result = call_fit_analysis_tool("get_history", {}, parsed=sample_parsed_fit, history_before=history)
        assert result["result"]["count"] == 2

    def test_get_sampled_records(self, sample_parsed_fit):
        result = call_fit_analysis_tool("get_sampled_records", {"max_records": 20}, parsed=sample_parsed_fit, history_before=None)
        assert result["result"]["record_count"] > 0
        assert len(result["result"]["sampled_records"]) <= 20


class TestGetActivityOverviewTool:
    def test_returns_expected_structure(self, sample_parsed_fit):
        result = get_activity_overview_tool(sample_parsed_fit)
        assert result["activity_identity"]["sport_type"] == "cycling"
        assert "duration_min" in result["scale"]
        assert "distance_km" in result["scale"]
        assert "avg_power_w" in result["basic_metrics"]
        assert "avg_hr_bpm" in result["basic_metrics"]
        assert "has_power" in result["data_availability"]

    def test_no_records_no_crash(self):
        parsed = {"summary": {}, "sessions": [], "sports": [], "records": [], "laps": [], "training_metadata": {}}
        result = get_activity_overview_tool(parsed)
        assert result["activity_identity"]["sport_type"] is None
        assert result["scale"]["duration_min"] is None
        assert result["data_availability"]["record_count"] is None


class TestGetActivitySummaryTool:
    def test_all_sections_returns_structured_data(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections="all")
        assert "activity_identity" in result
        assert "power" in result
        assert "heart_rate" in result

    def test_single_section(self, sample_parsed_fit):
        result = get_activity_summary_tool(sample_parsed_fit, sections=["power"])
        assert "power" in result
        assert "heart_rate" not in result


class TestGetSampledRecordsTool:
    def test_max_records_limit(self, sample_parsed_fit):
        result = get_sampled_records_tool(sample_parsed_fit, max_records=10)
        assert len(result["sampled_records"]) <= 10

    def test_sample_step_calculated(self, sample_parsed_fit):
        result = get_sampled_records_tool(sample_parsed_fit, max_records=20)
        assert result["sample_step"] > 0

    def test_empty_records(self):
        parsed = {"records": []}
        result = get_sampled_records_tool(parsed, max_records=20)
        assert result["record_count"] == 0
        assert result["sampled_records"] == []


class TestNormalizeHistoryEntry:
    def test_fills_default_fields(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        entry = {}
        result = normalize_history_entry(entry, path=fit_path, parsed=sample_parsed_fit)
        assert result["activity_key"] is not None
        assert result["schema_version"] == "llm_activity_history_entry.v1"
        assert result["sport_type"] == "cycling"

    def test_preserves_existing_fields(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        entry = {"brief": "自定义笔记", "custom_field": "keep_me"}
        result = normalize_history_entry(entry, path=fit_path, parsed=sample_parsed_fit)
        assert result["brief"] == "自定义笔记"
        assert result["custom_field"] == "keep_me"
