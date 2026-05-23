from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.activity_index import _entry_from_fit_summary
from core.file_workflow import normalize_history_entry


class TestRelativeFitPathInActivityIndex:
    def test_fit_path_converted_to_relative(self, tmp_path, monkeypatch):
        """_entry_from_fit_summary 把绝对路径 FIT 转为相对路径存储."""
        monkeypatch.chdir(tmp_path)
        fit_dir = tmp_path / "garmin_cn_fit_files"
        fit_dir.mkdir()
        fit_file = (fit_dir / "test_activity.fit")
        fit_file.write_bytes(b"dummy fit content")

        summary = {
            "sport_type": "cycling",
            "start_time_local": "2026-05-14T08:00:00",
            "duration_s": 600.0,
            "distance_m": 5000.0,
        }
        entry = _entry_from_fit_summary(
            fit_file.resolve(),
            summary,
            source="manual",
            source_activity_id=None,
        )
        assert entry["fit_path"] == "garmin_cn_fit_files/test_activity.fit"
        assert not Path(entry["fit_path"]).is_absolute()

    def test_summary_path_not_exists_set_to_none(self, tmp_path, monkeypatch):
        """summary 尚未生成时 summary_path 为 None."""
        monkeypatch.chdir(tmp_path)
        fit_file = tmp_path / "no_summary.fit"
        fit_file.write_bytes(b"dummy")

        summary = {"sport_type": "running", "start_time_local": "2026-05-14T08:00:00"}
        entry = _entry_from_fit_summary(
            fit_file.resolve(),
            summary,
            source="manual",
            source_activity_id=None,
        )
        assert entry.get("summary_path") is None


class TestRelativeFilePathInHistoryEntry:
    def test_file_path_converted_to_relative(self, tmp_path, monkeypatch):
        """normalize_history_entry 把绝对路径转为相对路径."""
        monkeypatch.chdir(tmp_path)
        fit_dir = tmp_path / "garmin_cn_fit_files"
        fit_dir.mkdir()
        fit_file = (fit_dir / "ride.fit")
        fit_file.write_bytes(b"dummy")

        parsed = {
            "summary": {"sport_type": "cycling", "start_time_local": "2026-05-14T08:00:00"},
        }
        entry = normalize_history_entry(
            {"summary_label": "test ride"},
            path=fit_file.resolve(),
            parsed=parsed,
        )
        assert entry["file_path"] == "garmin_cn_fit_files/ride.fit"
        assert not Path(entry["file_path"]).is_absolute()
