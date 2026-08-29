"""코멘트 블록의 편집 잠금.

한 번에 한 명만 같은 (블록, 월)을 편집하도록 막는다. 로그인이 없으므로 소유자는
브라우저 세션이 발급한 토큰이며, 이름은 다루지 않는다.

저장 위치: `google_sheets_writer`가 설정돼 있으면 전용 구글시트 `locks_state` 탭에
**잠금 하나당 한 행**. 아니면(로컬 개발 PC 등) `notes/locks.json`.

시트로 옮긴 이유 두 가지:
1. 배포판(Streamlit Community Cloud)은 재배포·리부트마다 로컬 디스크가 초기화된다.
   그러면 모든 잠금이 한꺼번에 풀려(fail-open) 두 사람이 같은 블록을 각자 "편집 중 · 나"로
   잡은 채 서로의 글을 덮어쓸 수 있었다.
2. 로컬 파일 방식은 잠금 dict **전체**를 다시 썼다. A가 X를, B가 Y를 동시에 잠그면 B의
   쓰기가 A의 잠금 항목을 지운다. 이제 행 하나만 갱신하고, 획득은 rev 비교
   (compare-and-set)로 처리해서 "둘이 동시에 free를 보고 둘 다 잡는" 경합도 막는다.

읽기 캐시: status()는 블록마다 리런마다 불린다. 시트를 매번 읽으면 화면 한 번 그릴 때
API 호출이 블록 수만큼 나가므로 아주 짧게(_CACHE_TTL초) 캐시하고 쓰기 직후 비운다.
touch도 리런마다 보내지 않고 _TOUCH_INTERVAL초에 한 번만 보낸다 — 잠금 유지에는 충분하고,
가장 빈번했던 쓰기 경합이 사라진다.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import google_sheets_writer

LOCKS_PATH = Path(__file__).resolve().parent / "notes" / "locks.json"

# 편집을 열어둔 채 자리를 뜬 잠금은 스스로 풀려야 한다
LOCK_TTL_MINUTES = 15
# 막 시작한 사람을 실수로 밀어내지 않도록, 이 시간이 지나야 강제 해제를 노출한다
# 5분이었는데 1분으로 줄였다(2026-08-29).
#
# 로그인이 없어 "누가 편집 중인가"를 브라우저 세션 토큰으로 판별한다. 그런데 그 토큰은
# session_state에 있어서 **새로고침하거나 서버가 재배포되면 새로 발급**된다 — 방금까지
# 내가 잡고 있던 잠금이 갑자기 "다른 사람"이 된다(실제로 겪음). 혼자 쓰는 시간이 대부분인
# 도구라, 남의 잠금을 오래 존중하는 것보다 빨리 되찾을 수 있는 편이 실용적이다.
STEAL_AFTER_MINUTES = 1

_CACHE_TTL = 4.0
# 잠금 갱신(touch)을 이 간격보다 자주 쓰지 않는다. 15분 TTL에 비해 아주 짧아 잠금 유지에는
# 넉넉하고, 리런마다 쓰던 것이 사라진다.
_TOUCH_INTERVAL_SECONDS = 30.0
_cache: tuple[float, dict] | None = None


@dataclass
class LockStatus:
    state: str  # "free" | "mine" | "other"
    held_minutes: float = 0.0


def _key(kind: str, month: int) -> str:
    return f"{kind}@{int(month)}"


def _read_local() -> dict:
    if not LOCKS_PATH.exists():
        return {}
    try:
        data = json.loads(LOCKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_local(data: dict) -> None:
    LOCKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # blocks.save_blocks와 같은 이유로 원자적 교체를 쓴다 — 쓰는 도중 끊기면 잠금 파일이
    # 통째로 깨져 모두의 잠금이 한꺼번에 사라진다.
    tmp = LOCKS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, LOCKS_PATH)


def clear_cache() -> None:
    global _cache
    _cache = None


def reset_state() -> None:
    """캐시를 통째로 비운다(테스트·프로세스 재시작 대용)."""
    clear_cache()


def _read(use_cache: bool = True) -> dict:
    """{키: {owner, acquired_at, touched_at, rev}} 를 돌려준다."""
    global _cache
    if use_cache and _cache and (time.monotonic() - _cache[0]) < _CACHE_TTL:
        return _cache[1]

    if google_sheets_writer.configured():
        status, data, _reason = google_sheets_writer.read_locks()
        if status == "error":
            # 잠금 저장소를 못 읽었다. 여기서 "잠금 없음"으로 답하면 두 사람이 같은 블록을
            # 동시에 잡는다. 캐시에 담지 않고, 마지막으로 알던 상태를 그대로 쓴다.
            return _cache[1] if _cache else {}
    else:
        data = {k: dict(v, rev=0) for k, v in _read_local().items() if isinstance(v, dict)}

    _cache = (time.monotonic(), data)
    return data


def _held_minutes(entry: dict, now: datetime) -> float:
    try:
        touched = datetime.fromisoformat(entry["touched_at"])
    except (KeyError, TypeError, ValueError):
        return float("inf")
    return (now - touched).total_seconds() / 60


def status(kind: str, month: int, owner: str, now: datetime | None = None) -> LockStatus:
    now = now or datetime.now()
    entry = _read().get(_key(kind, month))
    if not entry:
        return LockStatus("free")
    elapsed = _held_minutes(entry, now)
    if elapsed >= LOCK_TTL_MINUTES:
        return LockStatus("free")
    if entry.get("owner") == owner:
        return LockStatus("mine", elapsed)
    return LockStatus("other", elapsed)


def _save_entry(
    key: str, owner: str, acquired_at: str, touched_at: str, expected_rev: int | None
) -> bool:
    clear_cache()
    if google_sheets_writer.configured():
        ok, _reason = google_sheets_writer.write_lock(
            key, owner, acquired_at, touched_at, expected_rev=expected_rev
        )
        return ok
    data = _read_local()
    data[key] = {"owner": owner, "acquired_at": acquired_at, "touched_at": touched_at}
    _write_local(data)
    return True


def _delete_entry(key: str) -> None:
    clear_cache()
    if google_sheets_writer.configured():
        google_sheets_writer.delete_lock(key)
        return
    data = _read_local()
    if data.pop(key, None) is not None:
        _write_local(data)


def acquire(kind: str, month: int, owner: str, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    key = _key(kind, month)
    # 획득은 반드시 최신 상태로 판단한다 — 캐시된 "free"를 믿으면 이미 남이 잡은 블록을
    # 잡았다고 착각한다.
    data = _read(use_cache=False)
    entry = data.get(key) or {}
    stamp = now.isoformat(timespec="seconds")

    if entry:
        elapsed = _held_minutes(entry, now)
        mine = entry.get("owner") == owner
        if not mine and elapsed < LOCK_TTL_MINUTES:
            return False
        acquired = entry.get("acquired_at", stamp) if mine else stamp
    else:
        acquired = stamp

    # rev 비교: 내가 읽은 그 순간의 rev와 시트의 rev가 같을 때만 쓴다. 두 사람이 동시에
    # 같은 free 블록을 잡으면 늦은 쪽은 여기서 실패하고 "다른 사람이 방금 시작했습니다"를
    # 보게 된다 — 예전에는 둘 다 성공했다고 믿었다.
    return _save_entry(key, owner, acquired, stamp, expected_rev=int(entry.get("rev", 0)))


def touch(kind: str, month: int, owner: str, now: datetime | None = None) -> bool:
    """내가 잡고 있는 잠금의 만료 시각을 미룬다.

    쓰로틀 기준은 **저장된 갱신 시각**이다(별도 상태를 들지 않는다). 마지막 갱신이
    _TOUCH_INTERVAL_SECONDS보다 최근이면 쓰기를 보내지 않는다 — 리런마다 쓰기를 보내는 것이
    이 앱에서 가장 빈번한 쓰기이자 가장 잦은 충돌원이었다.

    소유권 확인은 쓰로틀과 무관하게 항상 한다. 확인까지 건너뛰면 그 사이 누군가 강제
    해제한 잠금을 계속 "내 것"이라고 답해서, 뺏긴 사람이 그대로 저장하게 된다.
    """
    now = now or datetime.now()
    key = _key(kind, month)

    entry = _read().get(key)
    if not entry or entry.get("owner") != owner:
        return False
    elapsed_seconds = _held_minutes(entry, now) * 60
    if elapsed_seconds >= LOCK_TTL_MINUTES * 60:
        return False
    if elapsed_seconds < _TOUCH_INTERVAL_SECONDS:
        return True  # 방금 갱신됐다 — 쓰지 않는다

    fresh = _read(use_cache=False).get(key)
    if not fresh or fresh.get("owner") != owner:
        return False
    if _held_minutes(fresh, now) >= LOCK_TTL_MINUTES:
        return False
    return _save_entry(
        key, owner, fresh.get("acquired_at", now.isoformat(timespec="seconds")),
        now.isoformat(timespec="seconds"), expected_rev=int(fresh.get("rev", 0)),
    )


def release(kind: str, month: int, owner: str) -> None:
    key = _key(kind, month)
    entry = _read(use_cache=False).get(key)
    if entry and entry.get("owner") == owner:
        _delete_entry(key)


def force_release(kind: str, month: int) -> None:
    _delete_entry(_key(kind, month))
