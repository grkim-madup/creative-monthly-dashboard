"""6명이 동시에 써도 안전하도록 넣은 세 가지 조치의 회귀 테스트.

배경(2026-08-29 실측): 실제 시트에 6개 세션을 붙이자 ① 분당 60회 읽기 한도를 15초 만에
넘겨 저장이 전부 실패했고, ② 같은 표를 동시에 강조하면 6명 중 1명 것만 남았다.
②는 행의 rev를 대조하는 것만으로는 부족했다(6명 중 3명 생존) — 시트 API는 읽기와 쓰기가
원자적이지 않아 같은 행을 겨냥하면 여럿이 같은 rev를 보고 통과한다. 그래서 **셀마다 행을
나눴다**(키 하나 = 행 하나).

여기서 고정하는 것:
- 서로 다른 셀은 서로 다른 행에 저장된다 → 동시에 켜도 유실이 없다.
- 화면 한 번에 시트를 **한 번만** 읽는다(batchGet + 짧은 캐시).
- 읽기 실패는 절대 "데이터 없음"으로 저장되지 않는다.
- 쿼터 초과(429)는 사람이 읽을 수 있는 문장으로 바뀐다.
"""

from __future__ import annotations

import pytest

import blocks
import google_sheets_writer as writer
import highlights
import locks
import prefetch
from tests import fake_sheets

MONTH = 91  # 실제 노트·시트와 겹치지 않는 달(레거시 이관이 끼어들지 않게)
TABLE = "sec4"


@pytest.fixture
def book(monkeypatch):
    return fake_sheets.install(monkeypatch, writer)


def _add_block(title: str) -> None:
    blocks.mutate(
        MONTH,
        lambda d: (
            blocks.add_block(d, blocks.SLOT_ANALYSIS, "creative_query", title), d
        )[1],
    )


# ---------------------------------------------------------------------------
# A. 강조 — 같은 표를 동시에 만져도 유실되지 않는다


def test_two_people_highlighting_the_same_table_keep_both(book):
    """두 사람이 같은 표의 다른 셀을 강조하면 둘 다 남아야 한다."""
    ok, _ = highlights.apply(MONTH, TABLE, add=[(1, "CPI")])
    assert ok

    # 두 번째 사람은 첫 번째 사람의 저장을 못 본 상태다(캐시가 비어 있는 새 세션).
    highlights.clear_cache()
    ok, _ = highlights.apply(MONTH, TABLE, add=[(2, "CPI")])
    assert ok

    highlights.clear_cache()
    assert set(highlights.load(MONTH, TABLE)) == {(1, "CPI"), (2, "CPI")}


def test_each_cell_is_its_own_row(book):
    """유실이 원리적으로 없는 이유 — 셀마다 행이 다르다."""
    highlights.apply(MONTH, TABLE, add=[(1, "CPI"), (2, "CPI")])
    read = writer.store_read(writer.hl_cells_tab(MONTH))
    keys = [row[0] for row in writer.store_rows(read, writer.HL_CELL_HEADER)]
    assert sorted(keys) == [f"{TABLE}|1|CPI", f"{TABLE}|2|CPI"]


def test_a_stale_view_cannot_erase_someone_elses_cell(book):
    """화면이 낡은 목록을 들고 있어도, 저장은 내가 켠 셀의 행만 건드린다."""
    highlights.apply(MONTH, TABLE, add=[(1, "CPI")])
    highlights.clear_cache()
    stale = dict(highlights.load_all(MONTH))    # 이 시점의 화면이 아는 전부

    highlights.clear_cache()
    highlights.apply(MONTH, TABLE, add=[(7, "CPI")])   # 다른 사람이 먼저 저장

    highlights.seed_cache(MONTH, stale)                # 낡은 화면으로 되돌린다
    ok, _ = highlights.apply(MONTH, TABLE, add=[(3, "CPI")])
    assert ok

    highlights.clear_cache()
    assert set(highlights.load(MONTH, TABLE)) == {(1, "CPI"), (7, "CPI"), (3, "CPI")}


def test_removing_a_cell_does_not_drop_someone_elses(book):
    highlights.apply(MONTH, TABLE, add=[(1, "CPI"), (2, "CPI")])
    highlights.clear_cache()
    highlights.apply(MONTH, TABLE, remove=[(1, "CPI")])
    highlights.clear_cache()
    assert set(highlights.load(MONTH, TABLE)) == {(2, "CPI")}


def test_removing_a_cell_does_not_touch_other_tables(book):
    highlights.apply(MONTH, TABLE, add=[(1, "CPI")])
    highlights.apply(MONTH, "sec6", add=[(1, "CPI")])
    highlights.apply(MONTH, TABLE, remove=[(1, "CPI")])
    highlights.clear_cache()
    assert set(highlights.load(MONTH, "sec6")) == {(1, "CPI")}
    assert highlights.load(MONTH, TABLE) == []


def test_load_does_not_write_when_the_read_failed(book, monkeypatch):
    """읽기 실패를 '강조 없음'으로 오인해 쓰면 그 달의 강조가 전부 사라진다."""
    highlights.apply(MONTH, TABLE, add=[(1, "CPI")])
    highlights.clear_cache()

    broken = {"on": True}
    original = writer.read_hl_cells

    def maybe_broken(month, known_read=None):
        if broken["on"]:
            return "error", {}, "boom"
        return original(month, known_read)

    monkeypatch.setattr(writer, "read_hl_cells", maybe_broken)
    assert highlights.load(MONTH, TABLE) == []
    assert MONTH not in highlights._CACHE      # 실패는 캐시에 굳히지 않는다

    broken["on"] = False  # monkeypatch.undo()는 가짜 시트까지 되돌린다 — 토글로 푼다
    highlights.clear_cache()
    assert set(highlights.load(MONTH, TABLE)) == {(1, "CPI")}


def test_apply_reports_failure_instead_of_pretending_to_save(book, monkeypatch):
    monkeypatch.setattr(
        writer, "add_hl_cells", lambda *a, **k: (False, "HttpError 429 Quota exceeded")
    )
    ok, reason = highlights.apply(MONTH, TABLE, add=[(1, "CPI")])
    assert ok is False
    assert writer.is_quota_error(reason)


def test_old_table_rows_are_migrated_once(book):
    """예전 형식(표 하나 = 한 행)에 남아 있던 강조를 한 번만 옮긴다."""
    writer.write_highlight(MONTH, TABLE, [[1, "CPI"], [2, "CPI"]])
    highlights.clear_cache()

    assert set(highlights.load(MONTH, TABLE)) == {(1, "CPI"), (2, "CPI")}

    # 옮긴 뒤 사용자가 전부 지웠다면, 다음에 열 때 예전 탭에서 되살아나면 안 된다.
    highlights.apply(MONTH, TABLE, remove=[(1, "CPI"), (2, "CPI")])
    highlights.clear_cache()
    assert highlights.load(MONTH, TABLE) == []


# ---------------------------------------------------------------------------
# B. 읽기 횟수 — 화면 한 번에 시트를 한 번만 읽는다


def test_store_read_many_reads_every_tab_in_one_call(book):
    writer.store_upsert("a", ["k", writer.REV_COLUMN], {"k": "x", "rev": ""})
    writer.store_upsert("b", ["k", writer.REV_COLUMN], {"k": "y", "rev": ""})
    book.calls.clear()

    reads = writer.store_read_many(["a", "b", "없는탭"])

    assert [c for c in book.calls if c[0] == "get"] == []
    assert len([c for c in book.calls if c[0] == "batchGet"]) == 1
    assert reads["a"].ok and reads["b"].ok
    assert reads["없는탭"].status == "empty"  # 없는 탭은 batchGet을 통째로 실패시키므로 거른다


def test_one_render_reads_the_sheet_once(book):
    """미리 읽어두면 블록·강조·잠금 조회가 추가 호출 없이 끝난다."""
    _add_block("표")
    highlights.apply(MONTH, TABLE, add=[(1, "CPI")])
    locks.acquire("block:x", MONTH, "someone")
    blocks.clear_state_cache()
    highlights.clear_cache()
    locks.reset_state()
    book.calls.clear()

    prefetch.warm(MONTH)
    state = blocks.load_state(MONTH, use_cache=True)
    marks = highlights.load(MONTH, TABLE)
    locks.status("block:x", MONTH, "me")

    reads = [c for c in book.calls if c[0] in ("get", "batchGet")]
    assert len(reads) == 1 and reads[0][0] == "batchGet"
    assert len(state.data[blocks.SLOT_ANALYSIS]) == 1
    assert set(marks) == {(1, "CPI")}


def test_both_block_sections_share_one_read(book):
    """5번과 7번이 각각 읽던 것을 한 번으로 줄인다."""
    _add_block("표")
    blocks.clear_state_cache()
    book.calls.clear()

    blocks.load_state(MONTH, use_cache=True)   # 5번
    blocks.load_state(MONTH, use_cache=True)   # 7번

    assert len([c for c in book.calls if c[0] == "get"]) == 1


def test_saving_always_reads_fresh_state(book):
    """저장은 캐시를 믿지 않는다 — 낡은 rev로 남의 글을 덮어쓰지 않기 위해서다."""
    _add_block("표")
    blocks.load_state(MONTH, use_cache=True)   # 캐시를 채운다
    book.calls.clear()

    blocks.mutate(MONTH, lambda d: d)

    assert [c for c in book.calls if c[0] == "get"], "저장 경로가 캐시를 썼다"


def test_own_save_invalidates_the_cache(book):
    """내가 저장한 직후에는 캐시가 아니라 새 값이 보여야 한다."""
    _add_block("첫 블록")
    blocks.load_state(MONTH, use_cache=True)
    _add_block("둘째 블록")

    titles = [
        b["title"]
        for b in blocks.load_state(MONTH, use_cache=True).data[blocks.SLOT_ANALYSIS]
    ]
    assert titles == ["첫 블록", "둘째 블록"]


def test_prefetch_does_not_seed_an_unreadable_tab(book, monkeypatch):
    """읽기 실패를 캐시에 담으면 그 위에 빈 값을 저장하는 사고로 이어진다."""
    monkeypatch.setattr(
        writer, "store_read_many",
        lambda tabs: {tab: writer.StoreRead("error", reason="boom") for tab in tabs},
    )
    assert prefetch.warm(MONTH) is False
    assert blocks._STATE_CACHE == {}


# ---------------------------------------------------------------------------
# C. 쿼터 초과를 사람이 읽을 수 있게


@pytest.mark.parametrize("reason", [
    'HttpError 429 ... "Quota exceeded for quota metric \'Read requests\'"',
    "HttpError: rateLimitExceeded",
])
def test_quota_errors_are_recognised(reason):
    assert writer.is_quota_error(reason)
    assert "한도" in writer.friendly_error(reason)


def test_other_errors_keep_their_original_text():
    assert writer.friendly_error("ValueError: 이상함") == "ValueError: 이상함"
    assert not writer.is_quota_error("ValueError: 이상함")


def test_two_people_creating_the_same_tab_at_once(book, monkeypatch):
    """새 달을 여러 명이 동시에 처음 열면 탭 생성이 겹친다 — 화면이 죽으면 안 된다."""
    service = writer._service()

    real_batch = service.spreadsheets().batchUpdate

    def racing_batch(spreadsheetId=None, body=None, **kw):  # noqa: N803
        # 내가 만들기 직전에 다른 사람이 같은 탭을 이미 만들어 둔 상황.
        for request in (body or {}).get("requests", []):
            title = request.get("addSheet", {}).get("properties", {}).get("title")
            if title:
                book.tabs.setdefault(title, [])
                raise RuntimeError(
                    'Invalid requests[0].addSheet: A sheet with the name '
                    f'"{title}" already exists.'
                )
        return real_batch(spreadsheetId=spreadsheetId, body=body, **kw)

    monkeypatch.setattr(
        type(service.spreadsheets()), "batchUpdate", staticmethod(racing_batch)
    )
    writer._clear_tabs_cache()
    writer._ensure_tab(service, writer.block_rows_tab(MONTH))  # 예외가 나면 실패다


def test_collapsing_a_duplicate_row_does_not_shift_another_key(book):
    """중복 줄을 지우면 그 아래 행 번호가 밀린다 — 같은 배치의 다른 키가 밀려선 안 된다.

    동시 저장이 겹치면 같은 키가 두 줄이 될 수 있고(실측), 그 정리 과정에서 남의 행을
    덮어쓰면 코멘트가 통째로 바뀐다.
    """
    header = ["k", writer.REV_COLUMN, "v"]
    book.tabs["t"] = [
        header,
        ["a", "1", "a-원본"],
        ["a", "1", "a-중복"],     # 3행: 중복 줄
        ["b", "1", "b-원본"],     # 4행: 지우면 3행으로 밀린다
    ]
    writer._clear_tabs_cache()

    ok, _ = writer.store_upsert_many(
        "t", header, [{"k": "a", "rev": "", "v": "a-새값"},
                      {"k": "b", "rev": "", "v": "b-새값"}]
    )
    assert ok

    rows = {r[0]: r[2] for r in writer.store_rows(writer.store_read("t"), header)}
    assert rows == {"a": "a-새값", "b": "b-새값"}


def test_first_save_on_an_empty_tab_does_not_overwrite_others(book):
    """빈 탭에 여러 명이 동시에 첫 저장 — 예전에는 마지막 한 명만 남았다.

    실측(수동 분류, 6명 동시): 6개 중 5개가 사라졌다. 원인은 "탭이 비어 있으면
    [헤더, 내 행]을 A1에 통째로 쓴다"였다. 지금은 헤더만 놓고 행은 append 한다.
    """
    header = ["k", writer.REV_COLUMN, "v"]
    seen_empty = writer.store_read("새탭")          # 전원이 들고 있는 "비어 있다"

    for key in ("a", "b", "c"):
        ok, _ = writer.store_upsert(
            "새탭", header, {"k": key, "rev": "", "v": f"{key}값"},
            known_read=seen_empty,                  # 남이 이미 썼는지 모르는 상태
        )
        assert ok

    rows = {r[0]: r[2] for r in writer.store_rows(writer.store_read("새탭"), header)}
    assert rows == {"a": "a값", "b": "b값", "c": "c값"}


def test_first_batch_save_on_an_empty_tab_keeps_earlier_rows(book):
    header = ["k", writer.REV_COLUMN, "v"]
    seen_empty = writer.store_read("새탭2")
    writer.store_upsert_many(
        "새탭2", header, [{"k": "a", "rev": "", "v": "a값"}], known_read=seen_empty
    )
    writer.store_upsert_many(
        "새탭2", header, [{"k": "b", "rev": "", "v": "b값"}], known_read=seen_empty
    )
    rows = {r[0]: r[2] for r in writer.store_rows(writer.store_read("새탭2"), header)}
    assert rows == {"a": "a값", "b": "b값"}


def test_releasing_a_lock_does_not_remove_its_row(book):
    """잠금 해제는 행을 지우지 않고 소유자만 비운다.

    잠금은 6명이 쉬지 않고 넣고 푸는 가장 churn이 심한 탭이다. 행을 진짜로 지우면 그
    아래 행 번호가 밀려, 그 순간 다른 사람이 보낸 저장이 엉뚱한 행에 떨어진다
    (실측: 자기 키인데 획득 실패, 해제했는데 남는 행).
    """
    locks.acquire("block:a", MONTH, "나")
    locks.acquire("block:b", MONTH, "너")
    rows_before = len(writer.store_rows(writer.store_read(writer.LOCKS_TAB),
                                        writer.LOCK_HEADER))

    locks.release("block:a", MONTH, "나")

    rows_after = len(writer.store_rows(writer.store_read(writer.LOCKS_TAB),
                                       writer.LOCK_HEADER))
    assert rows_after == rows_before, "해제하면서 행이 사라졌다(아래 행 번호가 밀린다)"

    locks.reset_state()
    assert locks.status("block:a", MONTH, "누구든").state == "free"
    assert locks.status("block:b", MONTH, "누구든").state == "other"


def test_a_freed_lock_can_be_taken_again(book):
    locks.acquire("block:a", MONTH, "나")
    locks.release("block:a", MONTH, "나")
    locks.reset_state()
    assert locks.acquire("block:a", MONTH, "다른사람") is True


def test_unreadable_lock_store_never_reports_free(book, monkeypatch):
    """잠금을 못 읽었을 때 '아무도 안 잡았다'로 답하면 두 사람이 같이 편집한다."""
    locks.reset_state()
    monkeypatch.setattr(
        writer, "read_locks", lambda known_read=None: ("error", {}, "boom")
    )
    assert locks.acquire("block:x", MONTH, "나") is False
    assert locks.status("block:x", MONTH, "나").state == "other"
    assert locks.touch("block:x", MONTH, "나") is False


def test_override_save_reports_failure(book, monkeypatch):
    """수동 분류 저장 실패를 삼키면 화면에는 분류된 것처럼 보이고 시트에는 없다.

    실사용 흉내에서 17건 중 1건이 그렇게 조용히 사라졌다(2026-08-30).
    """
    import overrides as manual

    monkeypatch.setattr(
        writer, "write_override",
        lambda *a, **k: (False, "HttpError 429 Quota exceeded"),
    )
    ok, reason = manual.save(MONTH, "소재-A", {"creative_type": "Highlight"})
    assert ok is False
    assert writer.is_quota_error(reason)


def test_override_save_returns_success(book):
    import overrides as manual

    assert manual.save(MONTH, "소재-A", {"creative_type": "Highlight"}) == (True, None)
    assert manual.load(MONTH)["소재-A"]["creative_type"] == "Highlight"
