from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.strava_upload import (
    _parse_duplicate_activity_id,
    upload_summary_to_strava,
)
from core.activity_index import load_activity_index


class TestParseDuplicateActivityId:
    def test_extracts_activity_id_from_error(self):
        error = (
            'b4c6f1d8e0f3938d.fit duplicate of '
            '<a href="/activities/18619000064" target="_blank">Rider Tracker Virtual Ride</a>'
        )
        result = _parse_duplicate_activity_id({"error": error})
        assert result == "18619000064"

    def test_no_error_field_returns_none(self):
        assert _parse_duplicate_activity_id({"status": "ready"}) is None

    def test_non_duplicate_error_returns_none(self):
        assert _parse_duplicate_activity_id({"error": "Some other error"}) is None

    def test_error_not_string_returns_none(self):
        assert _parse_duplicate_activity_id({"error": 123}) is None

    def test_empty_dict_returns_none(self):
        assert _parse_duplicate_activity_id({}) is None


class TestUploadSummaryDuplicateWithoutForce:
    def test_duplicate_without_force_returns_clean_error(
        self, tmp_path, monkeypatch,
    ):
        """不加 --force 时返回干净提示,含已有活动 ID."""
        monkeypatch.chdir(tmp_path)

        # 准备 summary.json
        summaries_dir = tmp_path / "data" / "summaries"
        summaries_dir.mkdir(parents=True)
        fit_dir = tmp_path / "garmin_cn_fit_files"
        fit_dir.mkdir()
        fit_file = fit_dir / "test_ride.fit"
        fit_file.write_bytes(b"dummy")

        summary = {
            "activity_key": "abc123",
            "fit_path": "garmin_cn_fit_files/test_ride.fit",
            "fit_summary": {
                "sport_type": "cycling",
                "start_time_local": "2026-05-14T08:00:00",
            },
            "strava_summary": "测试 Strava 总结",
        }
        summary_path = summaries_dir / "test_ride.summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False))

        upload_response = {"id": 12345}
        duplicate_status = {
            "error": "test_ride.fit duplicate of "
            '<a href="/activities/18619000064" target="_blank">Test Ride</a>',
        }

        with patch("core.strava_upload.StravaSink") as MockSink:
            mock_sink = MockSink.return_value
            mock_sink.upload_fit.return_value = upload_response
            mock_sink.wait_for_upload.return_value = duplicate_status

            result = upload_summary_to_strava(str(summary_path), wait=True, force=False)

        assert result["status"] == "duplicate"
        assert result["strava_activity_id"] == "18619000064"
        assert "18619000064" in result["message"]
        assert "raw" not in json.dumps(result)
        saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert saved_summary["strava_activity_id"] == "18619000064"
        index_rows = load_activity_index()["activities"]
        assert index_rows[0]["strava_activity_id"] == "18619000064"


class TestUploadSummaryDuplicateWithForce:
    def test_duplicate_with_force_updates_description(
        self, tmp_path, monkeypatch,
    ):
        """加 --force 时更新已有活动的描述."""
        monkeypatch.chdir(tmp_path)

        summaries_dir = tmp_path / "data" / "summaries"
        summaries_dir.mkdir(parents=True)
        fit_dir = tmp_path / "garmin_cn_fit_files"
        fit_dir.mkdir()
        fit_file = fit_dir / "test_ride.fit"
        fit_file.write_bytes(b"dummy")

        strava_summary = "测试 Strava 总结"
        summary = {
            "activity_key": "abc123",
            "fit_path": "garmin_cn_fit_files/test_ride.fit",
            "fit_summary": {
                "sport_type": "cycling",
                "start_time_local": "2026-05-14T08:00:00",
            },
            "strava_summary": strava_summary,
        }
        summary_path = summaries_dir / "test_ride.summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False))

        upload_response = {"id": 12345}
        duplicate_status = {
            "error": "test_ride.fit duplicate of "
            '<a href="/activities/18619000064" target="_blank">Test Ride</a>',
        }
        update_response = {"id": 18619000064, "description": strava_summary}

        with patch("core.strava_upload.StravaSink") as MockSink:
            mock_sink = MockSink.return_value
            mock_sink.upload_fit.return_value = upload_response
            mock_sink.wait_for_upload.return_value = duplicate_status
            mock_sink.update_description.return_value = update_response

            result = upload_summary_to_strava(str(summary_path), wait=True, force=True)

        assert result["status"] == "description_updated"
        assert result["strava_activity_id"] == "18619000064"
        mock_sink.update_description.assert_called_once_with("18619000064", strava_summary)
        saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert saved_summary["strava_activity_id"] == "18619000064"

    def test_force_with_cached_activity_id_updates_without_upload(
        self, tmp_path, monkeypatch,
    ):
        """summary 已缓存 Strava 活动 ID 时,--force 直接更新描述,不再走 uploads."""
        monkeypatch.chdir(tmp_path)

        summaries_dir = tmp_path / "data" / "summaries"
        summaries_dir.mkdir(parents=True)
        fit_dir = tmp_path / "garmin_cn_fit_files"
        fit_dir.mkdir()
        fit_file = fit_dir / "test_ride.fit"
        fit_file.write_bytes(b"dummy")

        strava_summary = "测试 Strava 总结"
        summary = {
            "activity_key": "abc123",
            "fit_path": "garmin_cn_fit_files/test_ride.fit",
            "fit_summary": {
                "sport_type": "cycling",
                "start_time_local": "2026-05-14T08:00:00",
            },
            "strava_summary": strava_summary,
            "strava_activity_id": "18619000064",
        }
        summary_path = summaries_dir / "test_ride.summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False))

        update_response = {"id": 18619000064, "description": strava_summary}

        with patch("core.strava_upload.StravaSink") as MockSink:
            mock_sink = MockSink.return_value
            mock_sink.update_description.return_value = update_response

            result = upload_summary_to_strava(str(summary_path), wait=True, force=True)

        assert result["status"] == "description_updated"
        assert result["strava_activity_id"] == "18619000064"
        mock_sink.upload_fit.assert_not_called()
        mock_sink.wait_for_upload.assert_not_called()
        mock_sink.update_description.assert_called_once_with("18619000064", strava_summary)


class TestUploadSummarySuccess:
    def test_normal_upload_returns_uploaded(
        self, tmp_path, monkeypatch,
    ):
        """正常上传无 duplicate 时正常返回."""
        monkeypatch.chdir(tmp_path)

        summaries_dir = tmp_path / "data" / "summaries"
        summaries_dir.mkdir(parents=True)
        fit_dir = tmp_path / "garmin_cn_fit_files"
        fit_dir.mkdir()
        fit_file = fit_dir / "test_ride.fit"
        fit_file.write_bytes(b"dummy")

        summary = {
            "activity_key": "abc123",
            "fit_path": "garmin_cn_fit_files/test_ride.fit",
            "fit_summary": {
                "sport_type": "cycling",
                "start_time_local": "2026-05-14T08:00:00",
            },
            "strava_summary": "测试 Strava 总结",
        }
        summary_path = summaries_dir / "test_ride.summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False))

        upload_response = {"id": 12345}
        success_status = {"activity_id": 98765, "status": "ready"}

        with patch("core.strava_upload.StravaSink") as MockSink:
            mock_sink = MockSink.return_value
            mock_sink.upload_fit.return_value = upload_response
            mock_sink.wait_for_upload.return_value = success_status

            result = upload_summary_to_strava(str(summary_path), wait=True)

        assert "upload_status" in result
        assert result["upload_status"]["activity_id"] == 98765
