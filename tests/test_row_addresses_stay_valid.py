"""행 번호(=주소)가 절대 밀리지 않는다.

이 저장소의 모든 쓰기는 "읽어서 행 번호를 찾고 → `A{n}`에 update"다. 즉 **행 번호가 주소**다.
행을 진짜로 지우면 그 아래 주소가 전부 한 칸씩 밀리고, 그 순간 다른 사람이 (지우기 전에
읽어둔) 주소로 보낸 쓰기가 **남의 행을 키 컬럼까지 덮어쓴다.** `rev` 대조는 그 행의 *값*을
검증할 뿐 *주소*를 검증하지 않으므로 이걸 못 막는다.

그래서 지우기를 묘비(`__dead__…`)로 바꿨다. 여기서 그 성질을 고정한다.
"""

from __future__ import annotations

import pytest

import google_sheets_writer as writer
import highlights
from tests import fake_sheets

MONTH = 88
TABLE = "sec4"
HEADER = ["k", writer.REV_COLUMN, "v"]


@pytest.fixture
def book(monkeypatch):
    return fake_sheets.install(monkeypatch, writer)


def _seed(book, tab="t"):
    book.tabs[tab] = [HEADER, ["a", "1", "A값"], ["b", "1", "B값"], ["c", "1", "C값"]]
    book.ensure(tab)
    writer._clear_tabs_cache()


def _row_of(book, tab, key):
    return next((i + 1 for i, r in enumerate(book.tabs[tab]) if r and r[0] == key), None)


# ---------------------------------------------------------------------------


def test_removing_a_row_does_not_move_the_rows_below(book):
    _seed(book)
    before = _row_of(book, "t", "c")

    writer.store_delete("t", HEADER, "a")

    assert _row_of(book, "t", "c") == before, "행을 지웠더니 아래 주소가 밀렸다"
    rows = {r[0]: r[2] for r in writer.store_rows(writer.store_read("t"), HEADER)}
    assert rows == {"b": "B값", "c": "C값"}


def test_a_stale_address_cannot_overwrite_someone_elses_row(book):
    """남이 먼저 지운 뒤에 내 쓰기가 도착해도 남의 행을 건드리면 안 된다."""
    _seed(book)
    seen = writer.store_read("t")            # 내가 들고 있는(곧 낡을) 읽기

    writer.store_delete("t", HEADER, "a")    # 그 사이 남이 a를 지운다
    writer.store_upsert("t", HEADER, {"k": "c", "rev": "", "v": "C새값"},
                        known_read=seen)

    rows = {r[0]: r[2] for r in writer.store_rows(writer.store_read("t"), HEADER)}
    assert rows == {"b": "B값", "c": "C새값"}, "낡은 주소가 남의 행을 덮어썼다"


def test_a_retired_row_is_invisible_to_readers(book):
    _seed(book)
    writer.store_delete("t", HEADER, "b")

    read = writer.store_read("t")
    assert writer.store_get(read, HEADER, "b") is None
    assert writer.store_row_numbers(read, HEADER, "b") == []
    assert [r[0] for r in writer.store_rows(read, HEADER)] == ["a", "c"]
    # 행 자체는 남아 있어야 한다 — 그게 주소를 고정하는 방법이다
    assert len(book.tabs["t"]) == 4


def test_appending_after_a_retired_row_goes_to_the_end(book):
    """묘비 행이 중간에 있어도 새 행은 맨 끝에 붙어야 한다.

    예전에 시도했던 '내용만 비우기'는 여기서 깨졌다 — 첫 셀이 비면 append가 표의 끝을
    그 빈 행으로 보고 거기에 끼어들어 아래를 전부 밀었다(실제 시트로 확인).
    """
    _seed(book)
    writer.store_delete("t", HEADER, "b")
    c_row = _row_of(book, "t", "c")

    writer.store_upsert("t", HEADER, {"k": "d", "rev": "", "v": "D값"})

    assert _row_of(book, "t", "c") == c_row, "append가 중간에 끼어들어 아래를 밀었다"
    assert _row_of(book, "t", "d") == len(book.tabs["t"])


# ---------------------------------------------------------------------------
# 실제로 사고가 나던 자리 — 강조에는 잠금이 없다


def test_turning_a_highlight_off_does_not_disturb_another_cell(book):
    """A가 셀 하나를 끄는 동안 B가 다른 셀을 켜도 둘 다 정확해야 한다.

    강조는 잠금이 없어서 이 경합을 막아 주는 것이 아무것도 없었다.
    """
    highlights.apply(MONTH, TABLE, add=[(1, "CPI"), (2, "CPI"), (3, "CPI")])
    highlights.clear_cache()

    stale = writer.store_read(writer.hl_cells_tab(MONTH))   # B가 들고 있는 읽기
    highlights.apply(MONTH, TABLE, remove=[(1, "CPI")])     # A가 먼저 끈다

    # B가 낡은 읽기 상태에서 새 셀을 켠다
    writer.store_upsert(
        writer.hl_cells_tab(MONTH), writer.HL_CELL_HEADER,
        {"cell_key": writer.hl_cell_key(TABLE, 9, "CPI"), writer.REV_COLUMN: "",
         "table_key": TABLE, "row": "9", "col": "CPI"},
        known_read=stale,
    )

    highlights.clear_cache()
    assert set(highlights.load(MONTH, TABLE)) == {(2, "CPI"), (3, "CPI"), (9, "CPI")}


def test_two_tables_do_not_interfere_when_cells_are_turned_off(book):
    highlights.apply(MONTH, TABLE, add=[(1, "CPI"), (2, "CPI")])
    highlights.apply(MONTH, "sec6", add=[(1, "소진액"), (2, "소진액")])
    highlights.clear_cache()

    highlights.apply(MONTH, TABLE, remove=[(1, "CPI")])

    highlights.clear_cache()
    assert set(highlights.load(MONTH, "sec6")) == {(1, "소진액"), (2, "소진액")}
    assert set(highlights.load(MONTH, TABLE)) == {(2, "CPI")}
