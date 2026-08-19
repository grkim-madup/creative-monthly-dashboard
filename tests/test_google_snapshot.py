import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import google_sheets_writer  # noqa: E402
import google_snapshot  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(google_snapshot, "SNAPSHOT_DIR", tmp_path / "snapshots")
    # 로컬 개발 PC의 실제 .streamlit/secrets.toml에 서비스 계정이 설정돼 있어도, 이
    # 폴더-백엔드 테스트들은 항상 폴더 모드로 격리한다(그렇지 않으면 실제 시트 API를
    # 부르려다 실패하거나, 실제 시트에 테스트 데이터를 써버린다).
    monkeypatch.setattr(google_sheets_writer, "configured", lambda: False)


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


def test_source_label_is_local_path_in_folder_mode():
    assert google_snapshot.source_label(7) == str(google_snapshot.path(7))


# ----------------------------------------------------------------------------
# 구글시트 백엔드 — google_sheets_writer가 configured()=True일 때 그쪽으로 위임하는지만
# 확인한다. 실제 Google API 호출은 google_sheets_writer 자체 테스트(있다면)에서 다룬다.


@pytest.fixture
def sheet_mode(monkeypatch):
    monkeypatch.setattr(google_sheets_writer, "configured", lambda: True)


def test_exists_delegates_to_sheet_writer(sheet_mode, monkeypatch):
    monkeypatch.setattr(google_sheets_writer, "month_exists", lambda m: m == 7)
    assert google_snapshot.exists(7) is True
    assert google_snapshot.exists(8) is False


def test_frozen_at_delegates_to_sheet_writer(sheet_mode, monkeypatch):
    monkeypatch.setattr(google_sheets_writer, "frozen_at", lambda m: "2026-08-20 12:00")
    assert google_snapshot.frozen_at(7) == "2026-08-20 12:00"


def test_source_label_mentions_sheet_tab_in_sheet_mode(sheet_mode):
    assert "snapshot_7" in google_snapshot.source_label(7)


def test_save_writes_raw_cost_dataframe_to_sheet(sheet_mode, monkeypatch, tmp_path):
    captured = {}

    def fake_write_month(month, df):
        captured["month"] = month
        captured["df"] = df

    monkeypatch.setattr(google_sheets_writer, "write_month", fake_write_month)
    monkeypatch.setattr(
        google_snapshot, "load_google_ads_folder",
        lambda folder, cost_markup: pd.DataFrame(
            {"month": [7, 7, 8], "cost": [100.0, 200.0, 999.0]}
        ),
    )

    google_snapshot.save(7, tmp_path)

    assert captured["month"] == 7
    assert list(captured["df"]["month"]) == [7, 7]  # 8월 행은 걸러졌어야 한다
    assert list(captured["df"]["cost"]) == [100.0, 200.0]  # markup=1.0이라 원가 그대로


def test_save_raises_when_live_folder_has_no_data_for_month(sheet_mode, monkeypatch, tmp_path):
    monkeypatch.setattr(
        google_snapshot, "load_google_ads_folder",
        lambda folder, cost_markup: pd.DataFrame({"month": [8], "cost": [1.0]}),
    )
    with pytest.raises(RuntimeError):
        google_snapshot.save(7, tmp_path)


def test_load_applies_current_markup_to_raw_cost(sheet_mode, monkeypatch):
    monkeypatch.setattr(
        google_sheets_writer, "read_month",
        lambda m: pd.DataFrame({"month": [7], "cost_raw": [1000.0]}),
    )
    out = google_snapshot.load(7, cost_markup=1.083)
    assert out["cost"].iloc[0] == pytest.approx(1083.0)


def test_load_raises_when_sheet_tab_missing(sheet_mode, monkeypatch):
    monkeypatch.setattr(google_sheets_writer, "read_month", lambda m: None)
    with pytest.raises(RuntimeError):
        google_snapshot.load(7, cost_markup=1.0)
