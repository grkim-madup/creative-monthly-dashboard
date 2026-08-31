"""저장소 스위치의 기본값과 안전 규칙.

`STORAGE_BACKEND`가 없거나 이상한 값이면 **시트**로 떨어져야 한다. 이 기본값이
컷오버 전까지 운영 동작을 그대로 유지해 주고, 문제가 생기면 시크릿 하나로 되돌리는
길이 된다.
"""

from __future__ import annotations

import google_sheets_writer as writer
import store


def test_default_backend_is_sheets(monkeypatch):
    monkeypatch.setattr(writer, "_secret", lambda name: None)
    assert store.backend() == store.SHEETS
    assert store.is_firestore() is False


def test_unknown_value_falls_back_to_sheets(monkeypatch):
    monkeypatch.setattr(writer, "_secret", lambda name: "postgres")
    assert store.backend() == store.SHEETS


def test_firestore_is_opt_in(monkeypatch):
    monkeypatch.setattr(writer, "_secret", lambda name: "firestore")
    assert store.is_firestore() is True


def test_value_is_case_and_space_tolerant(monkeypatch):
    monkeypatch.setattr(writer, "_secret", lambda name: "  FireStore \n")
    assert store.is_firestore() is True


def test_broken_touched_at_is_treated_as_expired():
    """깨진 시각을 '방금'으로 보면 그 블록이 영구히 잠긴다 — 회수 가능해야 한다."""
    import fs_store
    from datetime import datetime

    now = datetime(2026, 8, 30, 12, 0, 0)
    assert fs_store._elapsed_minutes("", now) == float("inf")
    assert fs_store._elapsed_minutes("쓰레기값", now) == float("inf")
    assert fs_store._elapsed_minutes("2026-08-30T11:50:00", now) == 10.0


# ---------------------------------------------------------------------------
# 2-B: 백엔드를 갈아끼워도 소비 모듈의 계약이 같아야 한다


def test_firestore_read_shapes_match_the_sheet_contract():
    """반환 모양이 어긋나면 화면이 조용히 빈 리포트를 그린다 — 서명으로 고정해 둔다."""
    import inspect

    import fs_store

    # (상태, 데이터, 사유) 3-튜플을 돌려주는 읽기 함수들
    for name in ("read_locks", "read_block_rows", "read_hl_cells", "read_overrides"):
        assert callable(getattr(fs_store, name)), name

    # (ok, reason) 2-튜플을 돌려주는 쓰기 함수들
    for name in ("upsert_block_rows", "delete_block_rows", "add_hl_cells",
                 "remove_hl_cells", "write_override", "delete_override",
                 "acquire_lock", "touch_lock", "release_lock"):
        assert callable(getattr(fs_store, name)), name

    # 잠금 관련 함수는 now/ttl 을 받아야 한다(시간 판단을 저장소에 맡기지 않는다)
    for name in ("acquire_lock", "touch_lock"):
        params = inspect.signature(getattr(fs_store, name)).parameters
        assert "now" in params and "ttl_minutes" in params, name


def test_firestore_collection_names_avoid_reserved_pattern():
    """Firestore는 `__이름__` 형태를 예약어로 쓴다 — 컬렉션 이름에 못 넣는다."""
    import fs_store

    for name in (fs_store.LOCKS, fs_store.BLOCKS, fs_store.HLCELLS, fs_store.OVERRIDES):
        assert not (name.startswith("__") and name.endswith("__")), name


# --------------------------------------------------------------------------- #
# 스냅샷 청크 분할 (2-C)
#
# Firestore 문서 상한은 1 MiB인데 실제 7월 스냅샷은 JSON 692KB다(2,091행 × 20열).
# 행이 1.5배만 늘면 문서 하나에 안 들어간다 — 그래서 청크로 나눈다. 여기서는 실제 DB
# 없이 분할 규칙만 고정한다(DB 접근은 conftest가 막는다).
# --------------------------------------------------------------------------- #

import json

import fs_store


def test_청크는_목표_크기를_넘으면_나뉜다():
    rows = [[f"긴문자열-{i}" * 150, i] for i in range(400)]  # 합쳐 ~400KB
    chunks = fs_store._chunk_rows(rows, ["a", "b"])

    assert len(chunks) > 1, "692KB급 데이터가 한 청크에 뭉쳐 있으면 1MiB 한도를 넘는다"
    for payload in chunks:
        assert len(payload.encode("utf-8")) < 1_000_000, "청크 하나가 문서 상한에 근접"

    restored = [row for payload in chunks for row in json.loads(payload)]
    assert restored == rows, "청크를 이어 붙이면 원본과 정확히 같아야 한다"


def test_빈_표도_청크_하나를_만든다():
    """행이 없다고 청크가 0개면 읽는 쪽이 '깨진 스냅샷'으로 오해한다."""
    chunks = fs_store._chunk_rows([], ["a"])
    assert len(chunks) == 1
    assert json.loads(chunks[0]) == []


def test_한_행이_목표를_넘어도_잘리지_않는다():
    huge = [["x" * (fs_store.CHUNK_TARGET_BYTES + 5000)]]
    chunks = fs_store._chunk_rows(huge, ["a"])
    assert [row for c in chunks for row in json.loads(c)] == huge


def test_이관은_원래_고정시각을_보존한다():
    """스냅샷 고정 시각은 화면에 광고주에게 보인다 — 이관이 오늘로 덮으면 이력이 틀려진다.

    실제로 3단계 백필 첫 실행에서 7월 고정시각이 '2026-08-20 12:59'에서 실행 당일로
    바뀌었다. 여기서는 인자가 실제로 쓰이는지(서명 계약)만 고정한다.
    """
    import inspect

    sig = inspect.signature(fs_store.write_snapshot)
    assert "frozen_at" in sig.parameters, "이관용 frozen_at 인자가 사라지면 이력이 덮인다"
    assert sig.parameters["frozen_at"].default is None, "평소 고정은 지금 시각을 찍어야 한다"
