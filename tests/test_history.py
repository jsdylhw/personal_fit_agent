from __future__ import annotations

import json

import pytest

from core.history import (
    load_activity_history,
    query_activity_history,
    save_activity_history,
    upsert_activity_history,
)


class TestLoadActivityHistory:
    def test_empty_file_returns_empty_list(self, temp_history_file):
        result = load_activity_history(temp_history_file)
        assert result == []

    def test_nonexistent_file_returns_empty_list(self):
        result = load_activity_history("/tmp/nonexistent_history.jsonl")
        assert result == []

    def test_loads_entries(self, temp_history_file, sample_activity_history_entry):
        temp_history_file.write_text(
            json.dumps(sample_activity_history_entry, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result = load_activity_history(temp_history_file)
        assert len(result) == 1
        assert result[0]["activity_key"] == sample_activity_history_entry["activity_key"]

    def test_skips_invalid_json_lines(self, temp_history_file, sample_activity_history_entry):
        temp_history_file.write_text(
            "not valid json\n"
            + json.dumps(sample_activity_history_entry, ensure_ascii=False) + "\n"
            + "{broken json\n",
            encoding="utf-8",
        )
        result = load_activity_history(temp_history_file)
        assert len(result) == 1

    def test_sorts_by_start_time(self, temp_history_file):
        entries = [
            {"start_time": "2026-05-14T08:00:00+00:00", "activity_key": "c"},
            {"start_time": "2026-05-10T08:00:00+00:00", "activity_key": "a"},
            {"start_time": "2026-05-12T08:00:00+00:00", "activity_key": "b"},
        ]
        text = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
        temp_history_file.write_text(text, encoding="utf-8")
        result = load_activity_history(temp_history_file)
        assert result[0]["activity_key"] == "a"
        assert result[2]["activity_key"] == "c"


class TestSaveActivityHistory:
    def test_saves_and_loads(self, temp_history_file, sample_activity_history_entry):
        save_activity_history([sample_activity_history_entry], temp_history_file)
        loaded = load_activity_history(temp_history_file)
        assert len(loaded) == 1
        assert loaded[0]["activity_key"] == sample_activity_history_entry["activity_key"]

    def test_overwrites_existing(self, temp_history_file, sample_activity_history_entry):
        save_activity_history([sample_activity_history_entry], temp_history_file)
        new_entry = dict(sample_activity_history_entry, activity_key="new_key")
        save_activity_history([new_entry], temp_history_file)
        loaded = load_activity_history(temp_history_file)
        assert len(loaded) == 1
        assert loaded[0]["activity_key"] == "new_key"

    def test_creates_parent_directory(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "history.jsonl"
            save_activity_history([], path)
            assert path.exists()


class TestUpsertActivityHistory:
    def test_inserts_new_entry(self, temp_history_file, sample_activity_history_entry):
        upsert_activity_history(sample_activity_history_entry, temp_history_file)
        loaded = load_activity_history(temp_history_file)
        assert len(loaded) == 1

    def test_replaces_by_activity_key(self, temp_history_file, sample_activity_history_entry):
        upsert_activity_history(sample_activity_history_entry, temp_history_file)
        updated = dict(sample_activity_history_entry, brief="updated brief")
        upsert_activity_history(updated, temp_history_file)
        loaded = load_activity_history(temp_history_file)
        assert len(loaded) == 1
        assert loaded[0]["brief"] == "updated brief"

    def test_replaces_by_file_path(self, temp_history_file, sample_activity_history_entry):
        entry = dict(sample_activity_history_entry)
        entry.pop("activity_key", None)
        upsert_activity_history(entry, temp_history_file)
        updated = dict(entry, brief="updated by file_path")
        upsert_activity_history(updated, temp_history_file)
        loaded = load_activity_history(temp_history_file)
        assert len(loaded) == 1
        assert loaded[0]["brief"] == "updated by file_path"

    def test_deduplicates_only_first_match(self, temp_history_file, sample_activity_history_entry):
        entry1 = dict(sample_activity_history_entry, activity_key="key_a", file_path="/tmp/a.fit")
        entry2 = dict(sample_activity_history_entry, activity_key="key_b", file_path="/tmp/b.fit")
        upsert_activity_history(entry1, temp_history_file)
        upsert_activity_history(entry2, temp_history_file)
        loaded = load_activity_history(temp_history_file)
        assert len(loaded) == 2


class TestQueryActivityHistory:
    def test_returns_all_when_no_filters(self, temp_history_file, sample_activity_history_entry):
        save_activity_history([sample_activity_history_entry], temp_history_file)
        result = query_activity_history(path=temp_history_file)
        assert result["count"] == 1

    def test_filters_by_before_date(self, temp_history_file):
        entries = [
            {"start_time": "2026-05-10T08:00:00+00:00", "activity_key": "a"},
            {"start_time": "2026-05-14T08:00:00+00:00", "activity_key": "b"},
        ]
        save_activity_history(entries, temp_history_file)
        result = query_activity_history(before="2026-05-14T08:00:00+00:00", path=temp_history_file)
        assert result["count"] == 1
        assert result["activities"][0]["activity_key"] == "a"

    def test_filters_by_days(self, temp_history_file):
        entries = [
            {"start_time": "2026-05-01T08:00:00+00:00", "activity_key": "old"},
            {"start_time": "2026-05-13T08:00:00+00:00", "activity_key": "recent"},
        ]
        save_activity_history(entries, temp_history_file)
        result = query_activity_history(before="2026-05-14T08:00:00+00:00", days=7, path=temp_history_file)
        assert result["count"] == 1
        assert result["activities"][0]["activity_key"] == "recent"

    def test_limit(self, temp_history_file):
        entries = [
            {"start_time": f"2026-05-{d:02d}T08:00:00+00:00", "activity_key": str(d)}
            for d in range(1, 15)
        ]
        save_activity_history(entries, temp_history_file)
        result = query_activity_history(limit=5, path=temp_history_file)
        assert result["count"] == 5

    def test_empty_history(self, temp_history_file):
        result = query_activity_history(path=temp_history_file)
        assert result["count"] == 0
        assert result["activities"] == []
