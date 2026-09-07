# -*- coding: utf-8 -*-
"""`Media_RAW` 월 고정 — 광고주에게 이미 보낸 달의 숫자가 안 움직여야 한다.

규리님(2026-09-08): *"매달 보여야 하는 데이터의 기준이 달라."*
"""
import pandas as pd
import pytest

import media_snapshot


def frame(month: int, cost: float, ad: str = "a") -> pd.DataFrame:
    return pd.DataFrame([{
        "ad": ad, "month": month, "date": f"2026-0{month}-01",
        "media": "Meta", "os": "AOS", "ua_type": "UA", "format": "VID",
        "impression": 1000, "click": 10, "cost": cost, "total install": 5,
        "D0 read": 3, "D0 coin": 1, "D7 coin": 2,
    }])


@pytest.fixture(autouse=True)
def local_dir(tmp_path, monkeypatch):
    """실제 저장소·Firestore에 절대 닿지 않는다."""
    monkeypatch.setattr(media_snapshot, "SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(media_snapshot.store, "is_firestore", lambda: False)
    return tmp_path


def test_고정_전에는_없다():
    assert media_snapshot.exists(8) is False
    assert media_snapshot.frozen_at(8) is None
    assert media_snapshot.load(8) is None


def test_고정하면_그_달_행이_남는다():
    media_snapshot.save(8, frame(8, 1000.0))
    assert media_snapshot.exists(8)
    assert media_snapshot.frozen_at(8)
    loaded = media_snapshot.load(8)
    assert len(loaded) == 1
    assert float(loaded["cost"].iloc[0]) == 1000.0


def test_시트가_바뀌어도_고정한_달은_안_움직인다():
    """이 테스트가 이 기능의 존재 이유다."""
    media_snapshot.save(8, frame(8, 1000.0))
    live = frame(8, 9999.0)                      # 시트가 갱신됐다고 치자
    merged, swapped = media_snapshot.apply(live)
    assert swapped == [8]
    assert float(merged["cost"].iloc[0]) == 1000.0


def test_고정_안_한_달은_라이브를_그대로_쓴다():
    media_snapshot.save(8, frame(8, 1000.0))
    live = pd.concat([frame(8, 9999.0), frame(7, 500.0)], ignore_index=True)
    merged, swapped = media_snapshot.apply(live)
    assert swapped == [8]
    by_month = merged.set_index("month")["cost"].astype(float).to_dict()
    assert by_month == {8: 1000.0, 7: 500.0}


def test_아무것도_고정_안_했으면_원본_그대로():
    live = frame(8, 1000.0)
    merged, swapped = media_snapshot.apply(live)
    assert swapped == []
    assert merged is live


def test_월_필터를_안_걸고_줘도_그_달만_저장한다():
    both = pd.concat([frame(8, 1000.0), frame(7, 500.0)], ignore_index=True)
    media_snapshot.save(8, both)
    loaded = media_snapshot.load(8)
    assert set(loaded["month"]) == {8}


def test_그_달_행이_없으면_거부한다():
    with pytest.raises(ValueError):
        media_snapshot.save(9, frame(8, 1000.0))


def test_다시_고정하면_갈아끼워진다():
    media_snapshot.save(8, frame(8, 1000.0))
    media_snapshot.save(8, frame(8, 2000.0))
    assert float(media_snapshot.load(8)["cost"].iloc[0]) == 2000.0


def test_컬럼이_늘어난_뒤에_읽어도_어긋나지_않는다():
    """스냅샷을 만든 뒤 코드에 차원이 추가되는 일이 실제로 있었다(`title_code`)."""
    media_snapshot.save(8, frame(8, 1000.0))
    live = frame(8, 9999.0).assign(새컬럼="x")
    merged, swapped = media_snapshot.apply(live)
    assert swapped == [8]
    assert list(merged.columns) == list(live.columns)
    assert pd.isna(merged["새컬럼"].iloc[0])


def test_읽기가_실패하면_라이브를_남긴다(monkeypatch):
    """한 달을 못 읽었다고 리포트를 통째로 막지 않는다 — 대신 swapped에서 빠진다."""
    media_snapshot.save(8, frame(8, 1000.0))
    monkeypatch.setattr(media_snapshot, "load", lambda month: None)
    merged, swapped = media_snapshot.apply(frame(8, 9999.0))
    assert swapped == []
    assert float(merged["cost"].iloc[0]) == 9999.0


def test_고정된_달_목록():
    media_snapshot.save(7, frame(7, 1.0))
    media_snapshot.save(8, frame(8, 2.0))
    assert media_snapshot.frozen_months() == [7, 8]


def test_원자적_교체_임시파일이_안_남는다(local_dir):
    media_snapshot.save(8, frame(8, 1000.0))
    assert not list(local_dir.glob("*.tmp"))


def test_시트_백엔드는_쓰지_않는다():
    """월 34만 셀이라 스프레드시트 상한을 몇 달 만에 먹는다 — 폴백은 로컬 파일이다."""
    import inspect

    source = inspect.getsource(media_snapshot)
    assert "google_sheets_writer" not in source


# ------------------------------------------------------------- Firestore 백엔드

def test_구글과_미디어_스냅샷이_서로_침범하지_않는다(monkeypatch):
    """컬렉션 이름이 종류별로 갈라져 있는지. 겹치면 한쪽 고정이 다른 쪽을 지운다."""
    import fs_store
    from tests import fake_firestore

    fake_firestore.install(monkeypatch, fs_store)
    monkeypatch.setattr(media_snapshot.store, "is_firestore", lambda: True)

    google_rows = pd.DataFrame([{"asset": "url", "month": 8, "cost_raw": 7.0}])
    fs_store.write_snapshot(8, google_rows, cost_markup=1.08)
    media_snapshot.save(8, frame(8, 1000.0),
                        settings={"sheet_id": "SHEET-A"})

    assert fs_store.snapshot_exists(8) is True
    assert fs_store.snapshot_exists(8, kind="media") is True
    # 구글 쪽은 그대로 남아 있어야 한다
    google_back = fs_store.read_snapshot(8)
    assert list(google_back["asset"]) == ["url"]
    # 미디어 쪽도 자기 것만
    media_back = media_snapshot.load(8)
    assert float(media_back["cost"].iloc[0]) == 1000.0
    assert "asset" not in media_back.columns


def test_고정_시점_설정이_함께_남는다(monkeypatch):
    """규리님: 시트 링크·드롭박스 폴더·마크업이 당시 값으로 고정되어야 한다."""
    import fs_store
    from tests import fake_firestore

    fake_firestore.install(monkeypatch, fs_store)
    monkeypatch.setattr(media_snapshot.store, "is_firestore", lambda: True)

    media_snapshot.save(8, frame(8, 1000.0), settings={
        "sheet_id": "SHEET-A",
        "google_folder": r"C:\드롭박스\구글 먼슬리 크리",
        "cost_markup": 1.08,
    })
    settings = media_snapshot.frozen_settings(8)
    assert settings["sheet_id"] == "SHEET-A"
    assert settings["cost_markup"] == 1.08
    assert "구글 먼슬리 크리" in settings["google_folder"]


def test_설정이_없던_예전_스냅샷도_안전하다(monkeypatch):
    import fs_store
    from tests import fake_firestore

    fake_firestore.install(monkeypatch, fs_store)
    monkeypatch.setattr(media_snapshot.store, "is_firestore", lambda: True)
    media_snapshot.save(8, frame(8, 1000.0))
    assert media_snapshot.frozen_settings(8) == {}


def test_알_수_없는_종류는_거부한다():
    import fs_store

    with pytest.raises(ValueError):
        fs_store._kind("없는종류")


def test_로컬_폴백도_설정을_남긴다():
    """Firestore만 남기면 로컬에서는 "무엇으로 고정했는지 모르는" 상태가 된다."""
    media_snapshot.save(8, frame(8, 1000.0), settings={"sheet_id": "A",
                                                       "cost_markup": 1.08})
    assert media_snapshot.frozen_settings(8) == {"sheet_id": "A",
                                                 "cost_markup": 1.08}


def test_행_수를_돌려준다():
    media_snapshot.save(8, pd.concat([frame(8, 1.0, "a"), frame(8, 2.0, "b")],
                                     ignore_index=True))
    assert media_snapshot.row_count(8) == 2
    assert media_snapshot.row_count(7) is None
