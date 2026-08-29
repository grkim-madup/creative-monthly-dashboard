"""스냅샷 고정이 동시 사용에서 안전한지 — 원자적 교체의 회귀 테스트.

`write_month`는 프로젝트에서 유일하게 탭을 통째로 갈아끼우는 경로다. 예전에는
원본 탭을 clear한 뒤 다시 썼는데, 그 사이에
- 다른 사람이 그 달을 읽으면 빈 탭을 보고 "고정 안 됨"으로 판단했고(실측 26%),
- 쓰기가 실패하면 스냅샷이 **영구히 사라졌다**(clear는 이미 끝났으므로).

지금은 임시 탭에 다 쓴 뒤 한 번의 batchUpdate로 이름을 맞바꾼다.
"""

from __future__ import annotations

import pandas as pd
import pytest

import google_sheets_writer as writer
from tests import fake_sheets

MONTH = 95


@pytest.fixture
def book(monkeypatch):
    return fake_sheets.install(monkeypatch, writer)


def _df(tag: str, rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "asset": [f"{tag}-{i}" for i in range(rows)],
        "cost_raw": [100 + i for i in range(rows)],
        "month": [MONTH] * rows,
    })


def test_freezing_replaces_the_snapshot_and_leaves_no_temp_tab(book):
    writer.write_month(MONTH, _df("첫번째"))
    writer.write_month(MONTH, _df("두번째"))

    back = writer.read_month(MONTH)
    assert list(back["asset"]) == ["두번째-0", "두번째-1", "두번째-2"]
    assert [t for t in book.tabs if "staging" in t] == []


def test_a_failed_freeze_keeps_the_previous_snapshot(book, monkeypatch):
    """쓰기가 중간에 실패해도 이미 고정해 둔 값이 사라지면 안 된다."""
    writer.write_month(MONTH, _df("원본"))

    real_update = fake_sheets._Values.update
    broken = {"on": True}

    def failing_update(self, spreadsheetId=None, range=None, body=None, **kw):  # noqa: A002, N803
        if broken["on"] and "staging" in str(range):
            raise RuntimeError("네트워크가 끊겼다")
        return real_update(self, spreadsheetId=spreadsheetId, range=range, body=body, **kw)

    monkeypatch.setattr(fake_sheets._Values, "update", failing_update)
    with pytest.raises(RuntimeError):
        writer.write_month(MONTH, _df("새값"))

    broken["on"] = False   # monkeypatch.undo()는 가짜 시트까지 되돌린다 — 토글로 푼다
    back = writer.read_month(MONTH)
    assert list(back["asset"]) == ["원본-0", "원본-1", "원본-2"], "옛 스냅샷이 사라졌다"
    assert [t for t in book.tabs if "staging" in t] == [], "임시 탭이 남았다"


def test_the_tab_is_never_empty_during_a_freeze(book):
    """교체 순간에 읽어도 옛 값 아니면 새 값 — 빈 표는 없어야 한다."""
    writer.write_month(MONTH, _df("원본"))
    seen = []

    real_batch = fake_sheets._Spreadsheets.batchUpdate

    def watching_batch(self, spreadsheetId=None, body=None, **kw):
        # 교체 요청을 보내기 **직전**에 읽으면 아직 옛 값이 보여야 한다.
        if any("updateSheetProperties" in r for r in (body or {}).get("requests", [])):
            before = writer.read_month(MONTH)
            seen.append(None if before is None else list(before["asset"]))
        return real_batch(self, spreadsheetId=spreadsheetId, body=body, **kw)

    fake_sheets._Spreadsheets.batchUpdate = watching_batch
    try:
        writer.write_month(MONTH, _df("새값"))
    finally:
        fake_sheets._Spreadsheets.batchUpdate = real_batch

    assert seen == [["원본-0", "원본-1", "원본-2"]], f"교체 직전에 본 값: {seen}"
    after = writer.read_month(MONTH)
    assert list(after["asset"]) == ["새값-0", "새값-1", "새값-2"]


def test_freeze_stamp_stays_a_single_row(book):
    writer.write_month(MONTH, _df("a"))
    writer.write_month(MONTH, _df("b"))
    rows = writer.store_rows(writer.store_read(writer.META_TAB), writer.META_HEADER)
    assert len([r for r in rows if r[0] == str(MONTH)]) == 1
