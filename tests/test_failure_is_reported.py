"""저장이 실패했는데 성공한 것처럼 넘어가는 경로가 없어야 한다.

이 프로젝트에서 가장 자주 사고를 낸 방식이 "조용한 실패"다. 화면은 저장됐다고 하는데
시트에는 없다 — 사용자는 며칠 뒤에야 알아차린다. 그래서 **쓰기 실패를 일부러 주입해서**
호출자가 그 사실을 알게 되는지 확인한다.

여기서 고정하는 세 가지(2026-08-30에 전부 실제로 있던 버그):
- `delete_override`가 아무것도 안 돌려줘 화면이 TypeError로 죽었다
- `locks.release`가 해제 **쓰기** 실패를 재시도하지 않아 남이 15분간 편집을 못 했다
- `blocks.mutate`가 삭제 실패를 삼켜, 지운 블록이 다음 새로고침에 되살아났다
"""

from __future__ import annotations

import pytest

import blocks
import google_sheets_writer as writer
import locks
import overrides as manual
from tests import fake_sheets

MONTH = 89
QUOTA = "HttpError 429 Quota exceeded"


@pytest.fixture
def book(monkeypatch):
    return fake_sheets.install(monkeypatch, writer)


# ---------------------------------------------------------------------------
# 1. 분류를 전부 비우고 저장 → 화면이 죽으면 안 된다


def test_clearing_every_field_returns_a_result_instead_of_none(book):
    """화면은 `ok, reason = save(...)`로 받는다. None을 돌려주면 TypeError로 죽는다."""
    manual.save(MONTH, "소재-A", {"creative_type": "Highlight"})

    result = manual.save(MONTH, "소재-A", {"creative_type": "", "format": ""})

    assert isinstance(result, tuple) and len(result) == 2
    ok, _reason = result
    assert ok is True
    assert "소재-A" not in manual.load(MONTH)


def test_clearing_every_field_reports_a_failure(book, monkeypatch):
    manual.save(MONTH, "소재-A", {"creative_type": "Highlight"})
    monkeypatch.setattr(writer, "store_delete", lambda *a, **k: (False, QUOTA))

    ok, reason = manual.save(MONTH, "소재-A", {"creative_type": ""})

    assert ok is False
    assert writer.is_quota_error(reason)


# ---------------------------------------------------------------------------
# 2. 잠금 해제 — 쓰기가 실패하면 다시 시도해야 한다


def test_release_retries_when_the_write_fails(book, monkeypatch):
    """해제를 놓치면 남이 그 블록을 최대 TTL(15분) 동안 못 만진다."""
    assert locks.acquire("block:a", MONTH, "나") is True

    calls = {"n": 0}
    real = writer.delete_lock

    def flaky(key, expected_rev=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return False, QUOTA          # 처음 두 번은 429
        return real(key, expected_rev=expected_rev)

    monkeypatch.setattr(writer, "delete_lock", flaky)
    locks.release("block:a", MONTH, "나")

    assert calls["n"] == 3, "해제 쓰기 실패를 재시도하지 않았다"
    locks.reset_state()
    assert locks.status("block:a", MONTH, "누구든").state == "free"


def test_release_does_not_touch_someone_elses_lock(book):
    locks.acquire("block:a", MONTH, "먼저잡은사람")
    locks.reset_state()

    locks.release("block:a", MONTH, "남")

    locks.reset_state()
    assert locks.status("block:a", MONTH, "먼저잡은사람").state == "mine"


# ---------------------------------------------------------------------------
# 3. 블록 삭제 — 실패를 삼키면 지운 블록이 되살아난다


def test_mutate_reports_a_failed_delete(book, monkeypatch):
    blocks.mutate(MONTH, lambda d: (
        blocks.add_block(d, blocks.SLOT_ANALYSIS, "creative_query", "지울 블록"), d)[1])
    state = blocks.load_state(MONTH)
    block_id = state.data[blocks.SLOT_ANALYSIS][0]["id"]

    monkeypatch.setattr(writer, "delete_block_rows", lambda *a, **k: (False, QUOTA))
    ok, reason = blocks.mutate(
        MONTH, lambda d: (blocks.remove_block(d, blocks.SLOT_ANALYSIS, block_id), d)[1]
    )

    assert ok is False, "삭제가 실패했는데 성공을 보고했다"
    assert writer.is_quota_error(reason)


def test_delete_block_rows_reports_a_read_failure(book, monkeypatch):
    monkeypatch.setattr(
        writer, "store_read", lambda tab: writer.StoreRead("error", reason="boom")
    )
    ok, reason = writer.delete_block_rows(MONTH, ["abc"])
    assert (ok, reason) == (False, "boom")


def test_deleting_nothing_is_success(book):
    assert writer.delete_block_rows(MONTH, []) == (True, None)


def test_release_cannot_wipe_a_lock_someone_else_just_took(book):
    """해제의 사전 확인이 낡았어도 남의 잠금을 지우면 안 된다(rev 대조가 막는다)."""
    locks.acquire("block:a", MONTH, "나")
    stale = locks._read(use_cache=False).get(f"block:a@{MONTH}")

    locks.force_release("block:a", MONTH)          # 내 잠금이 풀리고
    locks.acquire("block:a", MONTH, "남")           # 남이 가져갔다

    # 내가 들고 있던 낡은 rev로 해제를 시도한다
    ok, reason = writer.delete_lock(
        f"block:a@{MONTH}", expected_rev=int(stale["rev"])
    )

    assert (ok, reason) == (False, "conflict")
    locks.reset_state()
    assert locks.status("block:a", MONTH, "남").state == "mine", "남의 잠금이 지워졌다"
