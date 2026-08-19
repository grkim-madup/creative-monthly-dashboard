import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import locks  # noqa: E402

T0 = datetime(2026, 8, 16, 14, 0, 0)
ME, OTHER = "owner-me", "owner-other"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "LOCKS_PATH", tmp_path / "notes" / "locks.json")


def test_acquire_on_free_section():
    assert locks.acquire("block:b1", 7, ME, now=T0) is True
    assert locks.status("block:b1", 7, ME, now=T0).state == "mine"


def test_other_owner_cannot_acquire_held_lock():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert locks.acquire("block:b1", 7, OTHER, now=T0) is False
    assert locks.status("block:b1", 7, OTHER, now=T0).state == "other"


def test_same_owner_can_reacquire():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert locks.acquire("block:b1", 7, ME, now=T0 + timedelta(minutes=1)) is True


def test_blocks_do_not_interfere():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert locks.acquire("block:b2", 7, OTHER, now=T0) is True


def test_months_do_not_interfere():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert locks.acquire("block:b1", 8, OTHER, now=T0) is True


def test_lock_expires_after_ttl():
    locks.acquire("block:b1", 7, ME, now=T0)
    later = T0 + timedelta(minutes=locks.LOCK_TTL_MINUTES + 1)
    assert locks.status("block:b1", 7, OTHER, now=later).state == "free"
    assert locks.acquire("block:b1", 7, OTHER, now=later) is True


def test_touch_extends_expiry():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert locks.touch("block:b1", 7, ME, now=T0 + timedelta(minutes=10)) is True
    assert locks.status("block:b1", 7, OTHER, now=T0 + timedelta(minutes=20)).state == "other"


def test_touch_fails_for_other_owner():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert locks.touch("block:b1", 7, OTHER, now=T0 + timedelta(minutes=1)) is False


def test_release_only_frees_own_lock():
    locks.acquire("block:b1", 7, ME, now=T0)
    locks.release("block:b1", 7, OTHER)
    assert locks.status("block:b1", 7, ME, now=T0).state == "mine"
    locks.release("block:b1", 7, ME)
    assert locks.status("block:b1", 7, ME, now=T0).state == "free"


def test_force_release_ignores_owner():
    locks.acquire("block:b1", 7, ME, now=T0)
    locks.force_release("block:b1", 7)
    assert locks.status("block:b1", 7, OTHER, now=T0).state == "free"


def test_force_release_on_missing_lock_is_safe():
    locks.force_release("block:none", 7)


def test_status_reports_held_minutes():
    locks.acquire("block:b1", 7, ME, now=T0)
    seen = locks.status("block:b1", 7, OTHER, now=T0 + timedelta(minutes=6))
    assert seen.state == "other"
    assert 5.9 < seen.held_minutes < 6.1


def test_touch_survives_force_release_between_reads(monkeypatch):
    """status() 이후 항목이 사라져도 KeyError로 페이지가 죽으면 안 된다."""
    locks.acquire("block:b1", 7, ME, now=T0)

    original_status = locks.status

    def steal_then_report(kind, month, owner, now=None):
        result = original_status(kind, month, owner, now)
        locks.force_release(kind, month)  # 두 번의 읽기 사이에 남이 강제 해제
        return result

    monkeypatch.setattr(locks, "status", steal_then_report)
    assert locks.touch("block:b1", 7, ME, now=T0 + timedelta(minutes=1)) is False


def test_lock_write_leaves_no_temp_file():
    locks.acquire("block:b1", 7, ME, now=T0)
    assert list(locks.LOCKS_PATH.parent.glob("*.tmp")) == []


def test_corrupted_lock_file_is_treated_as_empty():
    locks.LOCKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    locks.LOCKS_PATH.write_text("{깨진 json", encoding="utf-8")
    assert locks.status("block:b1", 7, ME, now=T0).state == "free"
    assert locks.acquire("block:b1", 7, ME, now=T0) is True
