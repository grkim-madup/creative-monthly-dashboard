"""여러 사람이 동시에 작업할 때만 터지는 사고를 고정한다.

ASA 위클리 대시보드에서 실제로 있었던 사고가 근거다(2026-08-28): 팀원들이 캠페인을 나눠
코멘트를 쓰자 한 캠페인의 코멘트 5개가 통째로 사라졌다. 원인은 "탭 전체를 읽고 → clear() →
전체 재작성"이었고, **서로 다른 것**을 저장해도 늦게 쓴 쪽이 먼저 쓴 것을 지웠다.

여기서는 google_sheets_writer의 함수를 갈아끼우지 않고, 실제 코드가 보내는 API 요청을
가짜 시트가 받아서 흉내낸다. 그래야 "탭을 clear하지 않았다"까지 검증할 수 있다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import blocks  # noqa: E402
import google_sheets_writer as writer  # noqa: E402
import highlights  # noqa: E402
import locks  # noqa: E402
import overrides  # noqa: E402
from tests import fake_sheets  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """로컬 폴백 경로가 실제 notes/ 폴더를 건드리지 않게 하고, 캐시를 비운다."""
    monkeypatch.setattr(blocks, "BLOCKS_DIR", tmp_path / "notes")
    monkeypatch.setattr(locks, "LOCKS_PATH", tmp_path / "notes" / "locks.json")
    monkeypatch.setattr(overrides, "OVERRIDES_DIR", tmp_path / "notes")
    monkeypatch.setattr(highlights, "HIGHLIGHTS_DIR", tmp_path / "notes")
    highlights.clear_cache()
    locks.clear_cache()
    writer.clear_image_cache()
    yield
    highlights.clear_cache()
    locks.clear_cache()


@pytest.fixture
def book(monkeypatch):
    return fake_sheets.install(monkeypatch, writer)


def _seed_two_blocks(month: int = 7) -> tuple[str, str]:
    data = blocks.empty_blocks()
    first = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "규리 블록")
    second = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "팀원 블록")
    blocks.save_blocks(month, data)
    return first, second


# ---------------------------------------------------------------------------
# 블록 — 서로 다른 블록을 동시에 저장해도 서로를 지우지 않는다


def test_saving_different_blocks_keeps_both_edits(book):
    """ASA에서 코멘트 5개를 날린 그 사고의 회귀 테스트."""
    first, second = _seed_two_blocks()

    # 규리님이 화면을 열어 첫 블록을 편집하기 시작한다(이 시점의 상태를 들고 있다).
    seen = blocks.load_state(7)
    seen_rev = seen.revs[first]

    # 그 사이 팀원이 두 번째 블록을 저장한다.
    ok, reason = blocks.mutate(
        7, lambda d: blocks.update_block(
            d, blocks.SLOT_ANALYSIS, second, comment="팀원이 쓴 코멘트"),
        expect={second: seen.revs[second]},
    )
    assert (ok, reason) == (True, None)

    # 이제 규리님이 첫 블록을 저장한다. 예전 구조라면 여기서 팀원의 코멘트가 사라졌다.
    ok, reason = blocks.mutate(
        7, lambda d: blocks.update_block(
            d, blocks.SLOT_ANALYSIS, first, comment="규리님이 쓴 코멘트"),
        expect={first: seen_rev},
    )
    assert (ok, reason) == (True, None)

    final = blocks.load_state(7).data[blocks.SLOT_ANALYSIS]
    comments = {b["id"]: b["comment"] for b in final}
    assert comments[first] == "규리님이 쓴 코멘트"
    assert comments[second] == "팀원이 쓴 코멘트"
    # 탭을 통째로 지우는 호출이 단 한 번도 없어야 한다 — 그게 사고의 원인이었다.
    assert book.cleared == []


def test_saving_same_block_twice_is_rejected_not_overwritten(book):
    """같은 블록을 동시에 저장하면 늦은 쪽은 거부된다(조용한 덮어쓰기 금지)."""
    first, _second = _seed_two_blocks()
    stale_rev = blocks.load_state(7).revs[first]

    ok, _ = blocks.mutate(
        7, lambda d: blocks.update_block(
            d, blocks.SLOT_ANALYSIS, first, comment="먼저 저장한 내용"),
        expect={first: stale_rev},
    )
    assert ok

    ok, reason = blocks.mutate(
        7, lambda d: blocks.update_block(
            d, blocks.SLOT_ANALYSIS, first, comment="늦게 저장한 내용"),
        expect={first: stale_rev},  # 화면이 들고 있던 옛 rev
    )
    assert (ok, reason) == (False, "conflict")

    survived = blocks.load_state(7).data[blocks.SLOT_ANALYSIS][0]
    assert survived["comment"] == "먼저 저장한 내용"


def test_unchanged_blocks_are_not_rewritten(book):
    """바뀐 블록만 쓴다 — 안 바뀐 블록에 쓰기가 나가면 불필요한 충돌·쿼터가 생긴다."""
    first, _second = _seed_two_blocks()
    book.updates.clear()
    book.appends.clear()

    blocks.mutate(7, lambda d: blocks.update_block(
        d, blocks.SLOT_ANALYSIS, first, comment="한 블록만 수정"))

    tab = writer.block_rows_tab(7)
    assert [u for u in book.updates if u[0] == tab] != []
    # 두 블록이 아니라 한 블록만 갱신됐다
    assert len([u for u in book.updates if u[0] == tab]) == 1


def test_deleting_a_block_leaves_the_other_row_untouched(book):
    first, second = _seed_two_blocks()

    ok, _ = blocks.mutate(
        7, lambda d: blocks.remove_block(d, blocks.SLOT_ANALYSIS, first))
    assert ok

    remaining = blocks.load_state(7).data[blocks.SLOT_ANALYSIS]
    assert [b["id"] for b in remaining] == [second]
    assert book.cleared == []


# ---------------------------------------------------------------------------
# 블록 — 읽기 실패에 빈 값을 덮어쓰지 않는다


def test_read_failure_does_not_wipe_blocks(book, monkeypatch):
    """일시적 읽기 실패를 '데이터 없음'으로 오인해 저장하면 한 달치가 사라진다."""
    _seed_two_blocks()
    before = [list(r) for r in book.tabs[writer.block_rows_tab(7)]]

    def boom(*_args, **_kwargs):
        raise TimeoutError("일시적 실패")

    monkeypatch.setattr(writer, "_existing_tabs", boom)

    state = blocks.load_state(7)
    assert state.status == "error"
    assert state.reason

    ok, _ = blocks.mutate(7, lambda d: blocks.add_block(
        d, blocks.SLOT_ANALYSIS, "creative_query", "실패 중에 추가"))
    assert ok is False
    # 시트는 손대지 않았다
    assert book.tabs[writer.block_rows_tab(7)] == before


def test_broken_row_json_is_an_error_not_an_empty_report(book):
    tab = writer.block_rows_tab(7)
    book.tabs[tab] = [writer.BLOCK_HEADER, ["abc123", "analysis", "0", "1", "{깨진 JSON"]]

    status, _items, reason = writer.read_block_rows(7)
    assert status == "error"
    assert reason
    assert blocks.load_state(7).status == "error"


def test_legacy_single_cell_blocks_are_migrated_once(book):
    """예전 한 셀 JSON 형식이 새 행 형식으로 옮겨지고, 원본은 남는다."""
    legacy = blocks.empty_blocks()
    blocks.add_block(legacy, blocks.SLOT_NEXT_STEP, "note", "예전 코멘트")
    writer.write_blocks(7, legacy)

    data = blocks.load_state(7).data
    assert data[blocks.SLOT_NEXT_STEP][0]["title"] == "예전 코멘트"
    # 원본 탭(blocks_7)은 그대로 남아 있어야 한다 — 이관이 잘못돼도 되돌릴 수 있어야 한다.
    assert book.tabs["blocks_7"]


# ---------------------------------------------------------------------------
# 이미지 — 삭제가 다른 이미지를 건드리지 않는다


def test_deleting_one_image_keeps_the_others(book):
    writer.write_image(7, "7_a_first.png", b"first-image-bytes")
    writer.write_image(7, "7_b_second.png", b"second-image-bytes")

    writer.delete_image(7, "7_a_first.png")

    assert writer.read_image(7, "7_a_first.png") is None
    assert writer.read_image(7, "7_b_second.png") == b"second-image-bytes"
    # 탭 전체 clear가 없어야 한다 — clear~재작성 사이에 다른 사람이 읽으면 그 달 첨부가
    # 전부 빈칸으로 보였다.
    assert book.cleared == []


def test_two_uploads_then_one_delete_is_not_a_lost_update(book):
    """삭제 도중에 올라온 업로드가 사라지지 않는다."""
    writer.write_image(7, "7_a.png", b"aaa")
    writer.write_image(7, "7_b.png", b"bbb")
    writer.delete_image(7, "7_a.png")
    writer.write_image(7, "7_c.png", b"ccc")

    assert writer.read_image(7, "7_b.png") == b"bbb"
    assert writer.read_image(7, "7_c.png") == b"ccc"


# ---------------------------------------------------------------------------
# 스냅샷 메타 — 다른 달을 동시에 고정해도 서로를 지우지 않는다


def test_freezing_two_months_keeps_both_stamps(book):
    writer.store_upsert(writer.META_TAB, writer.META_HEADER,
                        {"month": "7", "frozen_at": "2026-08-01 10:00", "rev": ""})
    writer.store_upsert(writer.META_TAB, writer.META_HEADER,
                        {"month": "8", "frozen_at": "2026-09-01 10:00", "rev": ""})

    assert writer.frozen_at(7) == "2026-08-01 10:00"
    assert writer.frozen_at(8) == "2026-09-01 10:00"


# ---------------------------------------------------------------------------
# 편집 잠금


def test_two_sessions_cannot_hold_the_same_lock(book):
    assert locks.acquire("block:abc", 7, "규리-세션") is True
    locks.clear_cache()
    assert locks.acquire("block:abc", 7, "팀원-세션") is False


def test_stale_free_view_cannot_steal_a_lock(book, monkeypatch):
    """상대가 방금 잡은 걸 못 본 상태(캐시된 'free')로도 잠금을 빼앗지 못한다.

    예전 구조에서는 두 사람이 동시에 free를 보면 둘 다 성공했다고 믿었다 — rev 비교로 막는다.
    """
    assert locks.acquire("block:abc", 7, "규리-세션") is True

    # 팀원 세션이 잠금 저장소를 옛 상태(비어 있음)로 보고 있다고 가정한다.
    monkeypatch.setattr(locks, "_read", lambda use_cache=True: {})
    assert locks.acquire("block:abc", 7, "팀원-세션") is False


def test_locking_two_blocks_keeps_both_locks(book):
    """예전엔 잠금 dict 전체를 다시 써서, 다른 블록을 잠그면 남의 잠금이 사라졌다."""
    assert locks.acquire("block:aaa", 7, "규리-세션") is True
    locks.clear_cache()
    assert locks.acquire("block:bbb", 7, "팀원-세션") is True

    locks.clear_cache()
    assert locks.status("block:aaa", 7, "규리-세션").state == "mine"
    locks.clear_cache()
    assert locks.status("block:bbb", 7, "팀원-세션").state == "mine"
    assert book.cleared == []


def test_expired_lock_can_be_taken_over(book):
    from datetime import datetime, timedelta

    start = datetime(2026, 8, 28, 10, 0, 0)
    assert locks.acquire("block:abc", 7, "규리-세션", now=start) is True
    locks.clear_cache()
    later = start + timedelta(minutes=locks.LOCK_TTL_MINUTES + 1)
    assert locks.acquire("block:abc", 7, "팀원-세션", now=later) is True


def test_touch_is_throttled(book):
    """touch가 리런마다 쓰기를 보내면 그게 가장 빈번한 충돌원이 된다."""
    locks.acquire("block:abc", 7, "규리-세션")
    book.updates.clear()
    book.appends.clear()
    for _ in range(5):
        locks.touch("block:abc", 7, "규리-세션")
    assert book.updates == [] and book.appends == []


def test_lock_read_failure_does_not_report_free(book, monkeypatch):
    """잠금 저장소를 못 읽었을 때 'free'로 답하면 두 사람이 같은 블록을 잡는다."""
    locks.acquire("block:abc", 7, "규리-세션")
    locks.clear_cache()
    locks.status("block:abc", 7, "규리-세션")  # 캐시를 채운다

    monkeypatch.setattr(writer, "read_locks",
                        lambda: ("error", {}, "일시적 실패"))
    assert locks.status("block:abc", 7, "팀원-세션").state == "other"


# ---------------------------------------------------------------------------
# 오버라이드 / 하이라이트


def test_overrides_for_different_ads_do_not_overwrite_each_other(book):
    overrides.save(7, "소재-A", {"creative_type": "Highlight"})
    overrides.save(7, "소재-B", {"creative_type": "Trailer"})

    stored = overrides.load(7)
    assert stored["소재-A"]["creative_type"] == "Highlight"
    assert stored["소재-B"]["creative_type"] == "Trailer"
    assert book.cleared == []


def test_override_read_failure_returns_empty_without_writing(book, monkeypatch):
    overrides.save(7, "소재-A", {"creative_type": "Highlight"})
    before = [list(r) for r in book.tabs["overrides_7"]]
    monkeypatch.setattr(writer, "read_overrides",
                        lambda month: ("error", {}, "일시적 실패"))
    assert overrides.load(7) == {}
    assert book.tabs["overrides_7"] == before


def test_highlights_for_different_tables_do_not_overwrite_each_other(book):
    highlights.save(7, "sec4_media", [(0, "CPI")])
    highlights.save(7, "sec6_by_title", [(2, "소진액")])

    assert highlights.load(7, "sec4_media") == [(0, "CPI")]
    assert highlights.load(7, "sec6_by_title") == [(2, "소진액")]
    assert book.cleared == []


def test_highlight_cache_is_cleared_on_save(book):
    highlights.save(7, "sec4_media", [(0, "CPI")])
    assert highlights.load(7, "sec4_media") == [(0, "CPI")]
    highlights.save(7, "sec4_media", [])
    assert highlights.load(7, "sec4_media") == []


def test_local_fallback_still_works_without_service_account(tmp_path, monkeypatch):
    """서비스 계정이 없는 로컬 개발 PC에서는 파일 경로가 그대로 동작해야 한다."""
    monkeypatch.setattr(writer, "configured", lambda: False)
    overrides.save(7, "소재-A", {"creative_type": "Highlight"})
    assert overrides.load(7)["소재-A"]["creative_type"] == "Highlight"

    highlights.save(7, "tbl", [(1, "CPI")])
    assert highlights.load(7, "tbl") == [(1, "CPI")]

    assert locks.acquire("block:abc", 7, "규리-세션") is True
    locks.clear_cache()
    assert locks.status("block:abc", 7, "규리-세션").state == "mine"


# ---------------------------------------------------------------------------
# 중복 행 — 이관이 두 번 겹쳐 실행돼도 결과가 달라지지 않아야 한다
#
# 실제로 겪은 일: 예전 형식 → 새 행 형식 이관 순간 Streamlit의 첫 렌더와 리런이 겹쳐
# 두 실행이 같이 이관해, 같은 block_id가 두 줄씩 생겼다.


def test_duplicate_block_rows_are_read_as_one(book):
    tab = writer.block_rows_tab(7)
    block = {"id": "dup001", "type": "creative_query", "title": "제목", "comment": "새 내용"}
    stale = dict(block, comment="옛 내용")
    book.tabs[tab] = [
        writer.BLOCK_HEADER,
        ["dup001", "analysis", "0", "1", json.dumps(stale)],
        ["dup001", "analysis", "0", "2", json.dumps(block)],
    ]

    status, items, _ = writer.read_block_rows(7)
    assert status == "ok"
    assert len(items) == 1  # 두 줄이 한 블록으로 읽힌다
    assert items[0]["block"]["comment"] == "새 내용"  # rev가 큰 쪽을 고른다


def test_next_save_collapses_duplicate_rows(book):
    tab = writer.block_rows_tab(7)
    payload = json.dumps(
        {"id": "dup001", "type": "creative_query", "title": "제목", "comment": ""})
    book.tabs[tab] = [
        writer.BLOCK_HEADER,
        ["dup001", "analysis", "0", "1", payload],
        ["dup001", "analysis", "0", "2", payload],
    ]

    ok, _ = blocks.mutate(7, lambda d: blocks.update_block(
        d, blocks.SLOT_ANALYSIS, "dup001", comment="정리 후 저장"))
    assert ok
    # 지우기는 행을 없애지 않고 **내용만 비운다**(행 번호가 밀리면 남의 행을 덮어쓰기
    # 때문이다 — 2026-08-29). 그래서 빈 행을 걸러내고 센다.
    rows = [r for r in book.tabs[tab][1:] if r and r[0] == "dup001"]
    assert len(rows) == 1  # 저장하면서 중복이 스스로 정리된다
    assert "정리 후 저장" in rows[0][-1]


def test_delete_removes_every_duplicate_row(book):
    tab = f"overrides_{7}"
    book.tabs[tab] = [
        writer.OVERRIDE_HEADER,
        ["소재-A", "1", '{"creative_type": "Highlight"}'],
        ["소재-A", "2", '{"creative_type": "Trailer"}'],
    ]
    writer.delete_override(7, "소재-A")
    # 행 자체는 남고 내용만 비워진다 — 읽는 쪽(store_rows)이 빈 행을 건너뛴다.
    assert [r for r in book.tabs[tab][1:] if r and r[0] == "소재-A"] == []
    assert writer.store_rows(writer.store_read(tab), writer.OVERRIDE_HEADER) == []
