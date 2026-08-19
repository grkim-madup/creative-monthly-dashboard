import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import google_snapshot  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(google_snapshot, "SNAPSHOT_DIR", tmp_path / "snapshots")


@pytest.fixture
def source_folder(tmp_path):
    src = tmp_path / "live"
    (src / "AOS ACa").mkdir(parents=True)
    (src / "AOS ACa" / "a.csv").write_text("dummy", encoding="utf-8")
    (src / "iOS ACi").mkdir(parents=True)
    (src / "iOS ACi" / "b.csv").write_text("dummy", encoding="utf-8")
    return src


def test_exists_is_false_when_never_saved():
    assert google_snapshot.exists(7) is False


def test_save_then_exists(source_folder):
    google_snapshot.save(7, source_folder)
    assert google_snapshot.exists(7) is True


def test_save_preserves_folder_structure(source_folder):
    google_snapshot.save(7, source_folder)
    dest = google_snapshot.path(7)
    assert (dest / "AOS ACa" / "a.csv").exists()
    assert (dest / "iOS ACi" / "b.csv").exists()


def test_months_are_kept_separate(source_folder):
    google_snapshot.save(7, source_folder)
    assert google_snapshot.exists(7) is True
    assert google_snapshot.exists(8) is False


def test_frozen_at_is_none_before_saving():
    assert google_snapshot.frozen_at(7) is None


def test_frozen_at_returns_timestamp_after_saving(source_folder):
    google_snapshot.save(7, source_folder)
    stamp = google_snapshot.frozen_at(7)
    assert stamp is not None
    assert len(stamp) > 0


def test_resave_overwrites_previous_snapshot(source_folder, tmp_path):
    google_snapshot.save(7, source_folder)
    assert (google_snapshot.path(7) / "AOS ACa" / "a.csv").exists()

    new_source = tmp_path / "live2"
    (new_source / "AOS ACi").mkdir(parents=True)
    (new_source / "AOS ACi" / "c.csv").write_text("dummy2", encoding="utf-8")
    google_snapshot.save(7, new_source)

    dest = google_snapshot.path(7)
    assert (dest / "AOS ACi" / "c.csv").exists()
    assert not (dest / "AOS ACa").exists()  # 예전 스냅샷 내용은 완전히 지워졌어야 한다


def test_exists_ignores_folder_with_no_csv(tmp_path):
    empty_source = tmp_path / "empty_live"
    empty_source.mkdir()
    (empty_source / "note.txt").write_text("no csv here", encoding="utf-8")
    google_snapshot.save(9, empty_source)
    assert google_snapshot.exists(9) is False
