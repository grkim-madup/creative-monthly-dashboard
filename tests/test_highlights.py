import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import highlights  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(highlights, "HIGHLIGHTS_DIR", tmp_path / "notes")


def test_load_returns_empty_when_missing():
    assert highlights.load(7, "table_a") == []


def test_save_then_load_roundtrip():
    highlights.save(7, "table_a", [[0, "CPI"], [2, "소재명"]])
    assert highlights.load(7, "table_a") == [(0, "CPI"), (2, "소재명")]


def test_tables_are_kept_separate():
    highlights.save(7, "table_a", [[0, "CPI"]])
    highlights.save(7, "table_b", [[1, "노출"]])
    assert highlights.load(7, "table_a") == [(0, "CPI")]
    assert highlights.load(7, "table_b") == [(1, "노출")]


def test_months_are_kept_separate():
    highlights.save(7, "table_a", [[0, "CPI"]])
    highlights.save(8, "table_a", [[1, "노출"]])
    assert highlights.load(7, "table_a") == [(0, "CPI")]
    assert highlights.load(8, "table_a") == [(1, "노출")]


def test_saving_empty_list_clears_highlight():
    highlights.save(7, "table_a", [[0, "CPI"]])
    highlights.save(7, "table_a", [])
    assert highlights.load(7, "table_a") == []


def test_corrupted_file_falls_back_to_empty():
    highlights.HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    (highlights.HIGHLIGHTS_DIR / "highlights_7.json").write_text(
        "{깨진 json", encoding="utf-8"
    )
    assert highlights.load(7, "table_a") == []


def test_save_survives_existing_corrupted_file():
    highlights.HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    (highlights.HIGHLIGHTS_DIR / "highlights_7.json").write_text(
        "{깨진 json", encoding="utf-8"
    )
    highlights.save(7, "table_a", [[0, "CPI"]])
    assert highlights.load(7, "table_a") == [(0, "CPI")]
