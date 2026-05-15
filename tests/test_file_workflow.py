from __future__ import annotations

import pytest

from agent.tools import call_fit_analysis_tool, fit_analysis_tool_catalog
from core.data_tools import (
    DEFAULT_SECTIONS,
    SUMMARY_SECTIONS,
    _normalize_summary_sections,
    get_activity_overview_tool,
    get_activity_summary_tool,
)
from core.file_workflow import _extract_json_object, choose_strava_summary_tone, normalize_history_entry
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
    def test_returns_all_8_tools(self):
        tools = fit_analysis_tool_catalog()
        tool_names = {t["name"] for t in tools}
        assert tool_names == {
            "get_activity_overview", "get_activity_summary",
            "get_time_intervals", "get_distance_intervals", "get_history",
            "sync_garmin_activities", "analyze_fit_file", "upload_to_strava",
        }

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

    def test_preserves_existing_fields(self, sample_parsed_fit, tmp_path):
        fit_path = tmp_path / "test_activity.fit"
        fit_path.write_bytes(b"mock fit content")
        entry = {"brief": "自定义笔记", "custom_field": "keep_me"}
        result = normalize_history_entry(entry, path=fit_path, parsed=sample_parsed_fit)
        assert result["brief"] == "自定义笔记"
        assert result["custom_field"] == "keep_me"
