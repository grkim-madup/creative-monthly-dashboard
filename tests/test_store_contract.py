"""저장소 계약 — **같은 시나리오를 두 백엔드에서 돌려 같은 결과가 나오는지** 본다 (4단계).

기존 테스트는 대부분 시트 백엔드에 붙어 있었다. Firestore로 옮기면서 "화면이 보는
계약"이 안 바뀌었다는 걸 증명해야 하는데, 백엔드마다 따로 테스트를 쓰면 두 배로 늘고
계약이 어긋나도 안 잡힌다. 그래서 **한 시나리오 = 한 테스트, 백엔드는 파라미터**다.

여기서 고정하는 계약:
- 저장한 것이 그대로 읽힌다
- 남이 먼저 고쳤으면(`rev` 불일치) **거부한다** — 조용히 덮어쓰지 않는다
- 지운 것은 되살아나지 않는다
- 읽기 실패는 "데이터 없음"이 아니라 **error**로 올라와 편집을 막는다
- 강조는 **합친다**(전체 덮어쓰기가 아니다)
- 잠금은 **한 명만** 잡는다
- 스냅샷은 왕복이 정확하고, 이관 시 고정 시각이 보존된다

⚠ 시트 wire-level 어서션(`values().update`가 어느 range로 갔는지 등)은 여기 넣지 않는다.
   그건 `test_row_addresses_stay_valid.py` 등에 그대로 남긴다 — 시트 백엔드는 컷오버 후에도
   **백업·복구 경로로 남으므로** 버리지 않는다.
"""
from __future__ import annotations

import pytest

import blocks
import fs_store
import google_sheets_writer
import highlights
import locks
import overrides
import store
from tests import fake_firestore, fake_sheets

MONTH = 7
BACKENDS = ["sheets", "firestore"]


@pytest.fixture(params=BACKENDS)
def backend(request, monkeypatch):
    """두 백엔드를 같은 방식으로 붙인다. 어느 쪽도 실제 저장소에 닿지 않는다."""
    name = request.param
    if name == "sheets":
        fake_sheets.install(monkeypatch, google_sheets_writer)
        monkeypatch.setattr(store, "backend", lambda: store.SHEETS)
    else:
        fake_firestore.install(monkeypatch, fs_store)
        monkeypatch.setattr(store, "backend", lambda: store.FIRESTORE)
    locks.reset_state()
    highlights.clear_cache()
    blocks.clear_state_cache()
    return name


# --------------------------------------------------------------------------- #
# 블록(코멘트) — 이 프로젝트에서 유실 비용이 가장 큰 데이터
# --------------------------------------------------------------------------- #


def _add(month, title, comment=""):
    created = {}

    def change(data):
        block_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "note", title=title)
        blocks.update_block(data, blocks.SLOT_ANALYSIS, block_id, comment=comment)
        created["id"] = block_id

    ok, reason = blocks.mutate(month, change)
    assert ok, reason
    return created["id"]


def test_저장한_코멘트가_그대로_읽힌다(backend):
    block_id = _add(MONTH, "8월 소재 분석", "TEXT 유형이 잘 나왔다")

    blocks.clear_state_cache()
    state = blocks.load_state(MONTH)
    assert state.status == "ok"
    found = blocks.find_block(state.data, blocks.SLOT_ANALYSIS, block_id)
    assert found["title"] == "8월 소재 분석"
    assert found["comment"] == "TEXT 유형이 잘 나왔다"


def test_남이_먼저_고쳤으면_거부한다(backend):
    """조용히 덮어써서 남의 글을 지우는 것보다 거부가 낫다."""
    block_id = _add(MONTH, "제목", "처음")

    # A가 먼저 저장한다
    def first(data):
        blocks.update_block(data, blocks.SLOT_ANALYSIS, block_id, comment="A가 쓴 글")

    ok, _ = blocks.mutate(MONTH, first)
    assert ok

    # B는 그 전 rev를 들고 저장한다 → 거부돼야 한다
    def second(data):
        blocks.update_block(data, blocks.SLOT_ANALYSIS, block_id, comment="B가 쓴 글")

    ok, reason = blocks.mutate(MONTH, second, expect={block_id: 1})
    assert ok is False, f"[{backend}] 낡은 rev로 저장이 통과했다 — 남의 글이 사라진다"
    assert reason

    blocks.clear_state_cache()
    survivor = blocks.find_block(
        blocks.load_state(MONTH).data, blocks.SLOT_ANALYSIS, block_id)
    assert survivor["comment"] == "A가 쓴 글"


def test_지운_블록은_되살아나지_않는다(backend):
    block_id = _add(MONTH, "지울 블록", "내용")

    def drop(data):
        blocks.remove_block(data, blocks.SLOT_ANALYSIS, block_id)

    ok, reason = blocks.mutate(MONTH, drop)
    assert ok, reason

    blocks.clear_state_cache()
    state = blocks.load_state(MONTH)
    assert blocks.find_block(state.data, blocks.SLOT_ANALYSIS, block_id) is None


def test_읽기_실패는_error로_올라온다(backend, monkeypatch):
    """실패를 '데이터 없음'으로 뭉개면 그 위에 빈 값을 저장해 한 달치가 날아간다."""
    _add(MONTH, "지켜야 할 코멘트", "본문")
    blocks.clear_state_cache()

    def broken(*_args, **_kwargs):
        return "error", [], "조회 한도 초과"

    if backend == "sheets":
        monkeypatch.setattr(google_sheets_writer, "read_block_rows", broken)
    else:
        monkeypatch.setattr(fs_store, "read_block_rows", broken)

    state = blocks.load_state(MONTH)
    assert state.status == "error", "읽기 실패가 빈 리포트로 보이면 안 된다"


# --------------------------------------------------------------------------- #
# 셀 강조 — 잠금이 없는 전원 공유 상태
# --------------------------------------------------------------------------- #


def test_강조는_덮어쓰지_않고_합친다(backend):
    ok, reason = highlights.apply(MONTH, "sec2_media", add=[(1, "CPI")])
    assert ok, reason
    ok, reason = highlights.apply(MONTH, "sec2_media", add=[(3, "CTR")])
    assert ok, reason

    highlights.clear_cache()
    cells = set(highlights.load(MONTH, "sec2_media"))
    assert cells == {(1, "CPI"), (3, "CTR")}, \
        f"[{backend}] 나중 저장이 앞 사람 강조를 지웠다"


def test_강조_해제는_그_셀만_지운다(backend):
    highlights.apply(MONTH, "sec2_media", add=[(1, "CPI"), (2, "CPI"), (3, "CTR")])
    ok, reason = highlights.apply(MONTH, "sec2_media", remove=[(2, "CPI")])
    assert ok, reason

    highlights.clear_cache()
    assert set(highlights.load(MONTH, "sec2_media")) == {(1, "CPI"), (3, "CTR")}


def test_다른_표의_강조는_서로_영향_없다(backend):
    highlights.apply(MONTH, "sec2_media", add=[(1, "CPI")])
    highlights.apply(MONTH, "sec4_format", add=[(1, "CPI")])
    highlights.apply(MONTH, "sec2_media", remove=[(1, "CPI")])

    highlights.clear_cache()
    assert highlights.load(MONTH, "sec2_media") == []
    assert set(highlights.load(MONTH, "sec4_format")) == {(1, "CPI")}


# --------------------------------------------------------------------------- #
# 수동 분류
# --------------------------------------------------------------------------- #


def test_분류_저장과_삭제가_결과를_돌려준다(backend):
    ok, reason = overrides.save(MONTH, "1234_작품_VID", {"creative_type": "Highlight"})
    assert (ok, reason) == (True, None)
    assert overrides.load(MONTH)["1234_작품_VID"]["creative_type"] == "Highlight"

    ok, reason = overrides.remove(MONTH, "1234_작품_VID")
    assert ok, reason
    assert "1234_작품_VID" not in overrides.load(MONTH)


def test_분류를_전부_비우면_삭제되고_화면이_죽지_않는다(backend):
    """빈 dict를 넘기면 삭제 경로를 탄다. 예전에 None을 돌려줘 TypeError로 죽었다."""
    overrides.save(MONTH, "소재A", {"creative_type": "Trailer"})
    result = overrides.save(MONTH, "소재A", {"creative_type": ""})
    assert isinstance(result, tuple) and len(result) == 2
    ok, _reason = result
    assert ok
    assert "소재A" not in overrides.load(MONTH)


# --------------------------------------------------------------------------- #
# 편집 잠금 — 상호배제가 실제로 되는지
# --------------------------------------------------------------------------- #


def test_잠금은_한_명만_잡는다(backend):
    assert locks.acquire("block:abc", MONTH, "사람1") is True
    locks.clear_cache()
    assert locks.acquire("block:abc", MONTH, "사람2") is False, \
        f"[{backend}] 두 명이 같은 블록을 동시에 잡았다"


def test_잠금_해제_후에는_남이_잡을_수_있다(backend):
    locks.acquire("block:abc", MONTH, "사람1")
    locks.release("block:abc", MONTH, "사람1")
    locks.clear_cache()
    assert locks.acquire("block:abc", MONTH, "사람2") is True


def test_잠금을_못_읽으면_잡지_않는다(backend, monkeypatch):
    """모르면 안 잡는 쪽이 안전하다 — 예전에는 읽기 실패를 '잠금 없음'으로 봤다."""
    if backend == "sheets":
        monkeypatch.setattr(google_sheets_writer, "read_locks",
                            lambda *a, **k: ("error", {}, "조회 한도 초과"))
    else:
        # Firestore 경로는 트랜잭션 한 번으로 끝나므로, 저장소가 아예 안 되는 상황을
        # 만든다(잠금 획득이 실패하면 잡지 않아야 한다).
        def dead():
            raise RuntimeError("Firestore 연결 실패")

        monkeypatch.setattr(fs_store, "client", dead)
    locks.clear_cache()
    assert locks.acquire("block:abc", MONTH, "사람1") is False


# --------------------------------------------------------------------------- #
# 스냅샷 — 광고주에게 가는 이력
# --------------------------------------------------------------------------- #


def _sample_snapshot():
    import pandas as pd

    return pd.DataFrame({
        "asset": ["가", "나", "다"],
        "impression": [10, 20, 30],
        "cost_raw": [1000.5, 2000.25, 3000.0],
        "month": [MONTH] * 3,
    })


def test_스냅샷_왕복이_정확하다(backend):
    import pandas as pd

    df = _sample_snapshot()
    if backend == "sheets":
        google_sheets_writer.write_month(MONTH, df)
        back = google_sheets_writer.read_month(MONTH)
    else:
        fs_store.write_snapshot(MONTH, df)
        back = fs_store.read_snapshot(MONTH)

    assert list(back.columns) == list(df.columns)
    assert len(back) == len(df)
    assert back["asset"].tolist() == df["asset"].tolist()
    assert pd.to_numeric(back["cost_raw"]).sum() == pytest.approx(df["cost_raw"].sum())


def test_이관은_고정시각을_보존한다(backend):
    """이 값은 화면에 'N월 데이터 고정됨 · 날짜'로 광고주에게 보인다."""
    if backend == "sheets":
        pytest.skip("시트 백엔드에는 이관용 frozen_at 인자가 없다(원본 쪽이라 필요 없다)")
    fs_store.write_snapshot(MONTH, _sample_snapshot(), frozen_at="2026-08-20 12:59")
    assert fs_store.snapshot_frozen_at(MONTH) == "2026-08-20 12:59"


def test_스냅샷_고정은_지금_시각을_찍는다(backend):
    if backend == "sheets":
        pytest.skip("frozen_at 인자는 Firestore 백엔드에만 있다")
    fs_store.write_snapshot(MONTH, _sample_snapshot())
    stamp = fs_store.snapshot_frozen_at(MONTH)
    assert stamp and len(stamp) == 16 and stamp[4] == "-"


# --------------------------------------------------------------------------- #
# 미리 읽기(prefetch) — 컷오버 후 화면이 시트를 보고 있으면 안 된다
#
# 실제 사고(2026-09-01): 편집 모드에서 블록을 지우면 Firestore에서는 정상 삭제되는데,
# 다음 리런에서 `prefetch.warm`이 **시트**를 읽어 화면 캐시에 다시 심어서 보기 모드에
# 삭제한 블록이 되살아나 보였다. 저장은 Firestore, 화면은 시트를 보는 상태였다.
# --------------------------------------------------------------------------- #


def test_firestore_백엔드에서는_시트를_미리읽지_않는다(monkeypatch):
    """이걸 어기면 "지웠는데 되살아난다"가 재현된다."""
    import prefetch

    fake_sheets.install(monkeypatch, google_sheets_writer)
    monkeypatch.setattr(google_sheets_writer, "configured", lambda: True)
    fake_firestore.install(monkeypatch, fs_store)
    monkeypatch.setattr(store, "backend", lambda: store.FIRESTORE)

    blocks.clear_state_cache()
    highlights.clear_cache()
    locks.reset_state()

    # 시트에 예전 블록이 남아 있는 상태를 만든다(컷오버 전 데이터가 그대로 있다).
    google_sheets_writer.upsert_block_rows(MONTH, [{
        "block_id": "old123", "slot": blocks.SLOT_ANALYSIS, "seq": 0,
        "payload": {"id": "old123", "type": "note", "title": "시트에 남은 옛 블록"},
    }])

    seeded = prefetch.warm(MONTH)
    assert seeded is False, "Firestore 백엔드인데 시트에서 캐시를 심었다"
    assert blocks.cache_is_fresh(MONTH) is False, \
        "시트 데이터가 화면 캐시에 들어갔다 — 삭제한 블록이 되살아난다"

    state = blocks.load_state(MONTH, use_cache=True)
    ids = [b.get("id") for slot in blocks.SLOTS for b in state.data.get(slot, [])]
    assert "old123" not in ids, "화면이 시트 데이터를 보여주고 있다"
