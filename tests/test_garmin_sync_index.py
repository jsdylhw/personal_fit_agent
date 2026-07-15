from __future__ import annotations

from pathlib import Path

from agent.operations import sync_garmin_activities_tool
from core.activity_index import list_activities


def test_sync_garmin_indexes_downloaded_fit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    activity = {
        "activityId": 123,
        "activityName": "基础训练",
        "startTimeLocal": "2026-05-26 21:38:30",
    }

    class FakeDownloader:
        def login(self):
            return None

        def list_activities(self, count):
            return [activity]

        def download_original(self, activity_id):
            return b"fake-fit"

    monkeypatch.setattr("core.config.load_config", lambda: {"output_dir": "fits"})
    monkeypatch.setattr("core.config.cfg_get", lambda config, key, default=None: config.get(key, default))
    monkeypatch.setattr("core.garmin_cn.build_downloader", lambda config: FakeDownloader())
    monkeypatch.setattr("core.garmin_cn.existing_fit_paths", lambda output_dir, item: [])
    monkeypatch.setattr(
        "core.activity_index.parse_fit",
        lambda path: {
            "summary": {
                "sport_type": "running",
                "sub_sport": "generic",
                "start_time_local": "2026-05-26T21:38:30",
                "duration_s": 1800,
                "distance_m": 5000,
            }
        },
    )

    result = sync_garmin_activities_tool(count=1)

    assert result["downloaded"] == 1
    assert result["indexed"] == 1
    assert result["index_errors"] == []

    activities = list_activities(limit=1)
    assert activities["count"] == 1
    assert activities["activities"][0]["sport_type"] == "running"
    assert activities["activities"][0]["source"] == "garmin_cn"
    assert Path(activities["activities"][0]["fit_path"]).exists()


def test_sync_garmin_indexes_existing_fit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fit_dir = tmp_path / "fits"
    fit_dir.mkdir()
    fit_path = fit_dir / "existing.fit"
    fit_path.write_bytes(b"fake-fit")

    activity = {
        "activityId": 456,
        "activityName": "基础训练",
        "startTimeLocal": "2026-05-26 21:38:30",
    }

    class FakeDownloader:
        def login(self):
            return None

        def list_activities(self, count):
            return [activity]

        def download_original(self, activity_id):
            raise AssertionError("existing FIT should not be downloaded")

    monkeypatch.setattr("core.config.load_config", lambda: {"output_dir": str(fit_dir)})
    monkeypatch.setattr("core.config.cfg_get", lambda config, key, default=None: config.get(key, default))
    monkeypatch.setattr("core.garmin_cn.build_downloader", lambda config: FakeDownloader())
    monkeypatch.setattr("core.garmin_cn.existing_fit_paths", lambda output_dir, item: [fit_path])
    monkeypatch.setattr(
        "core.activity_index.parse_fit",
        lambda path: {
            "summary": {
                "sport_type": "running",
                "start_time_local": "2026-05-26T21:38:30",
                "duration_s": 1200,
                "distance_m": 3000,
            }
        },
    )

    result = sync_garmin_activities_tool(count=1)

    assert result["downloaded"] == 0
    assert result["skipped"] == 1
    assert result["indexed"] == 1
    assert list_activities(limit=1)["activities"][0]["sport_type"] == "running"
