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

import fs_store
import google_sheets_writer
import store

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
# 잠금을 주장한 뒤 "정말 내가 주인인가"를 다시 확인하기까지 기다리는 시간. 동시에 들어온
# 쓰기들이 정리될 만큼은 길어야 하고, 편집 버튼을 누른 사람이 답답하지 않을 만큼은 짧아야
# 한다. 0.5초에서 6명 동시 경합 시 새는 경우가 사라졌다(실측).
_CLAIM_SETTLE_SECONDS = 0.5
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


def cache_is_fresh() -> bool:
    """잠금 캐시가 아직 살아 있는가(prefetch가 건너뛸지 판단하는 데 쓴다)."""
    return bool(_cache) and (time.monotonic() - _cache[0]) < _CACHE_TTL


def seed_cache(data: dict) -> None:
    """다른 곳에서 읽어 온 잠금 상태를 캐시에 넣는다(prefetch.py).

    화면 한 번을 그릴 때 블록·강조·잠금을 batchGet으로 한 번에 읽고 나눠 담는다 —
    여기 없으면 _read가 시트를 또 읽는다.
    """
    global _cache
    _cache = (time.monotonic(), data)


def reset_state() -> None:
    """캐시를 통째로 비운다(테스트·프로세스 재시작 대용)."""
    clear_cache()


class LocksUnavailable(RuntimeError):
    """잠금 저장소를 읽지 못했다 — '잠금 없음'으로 오해하면 안 되는 상태."""


def _read(use_cache: bool = True) -> dict:
    """{키: {owner, acquired_at, touched_at, rev}} 를 돌려준다.

    읽기에 실패하고 참고할 캐시도 없으면 **LocksUnavailable**을 던진다. 예전에는 빈
    dict를 돌려줬는데, 그러면 호출자가 "아무도 안 잡았다"로 착각한다. 실제로 접속이
    몰려 429가 났을 때 그 경로를 탔고, 다행히 rev 대조가 쓰기를 막아 사고로 이어지지는
    않았지만(획득 실패로 보였다) 판단 자체가 틀린 상태였다(2026-08-29 실측).
    """
    global _cache
    if use_cache and _cache and (time.monotonic() - _cache[0]) < _CACHE_TTL:
        return _cache[1]

    if store.is_firestore():
        status, data, _reason = fs_store.read_locks()
        if status == "error":
            # 못 읽었다는 사실을 "잠금 없음"으로 뭉개면 두 사람이 같은 블록을 잡는다.
            if _cache:
                return _cache[1]
            raise LocksUnavailable(_reason or "잠금 상태를 읽지 못했습니다")
    elif google_sheets_writer.configured():
        status, data, _reason = google_sheets_writer.read_locks()
        if status == "error":
            # 잠금 저장소를 못 읽었다. 여기서 "잠금 없음"으로 답하면 두 사람이 같은 블록을
            # 동시에 잡는다. 마지막으로 알던 상태가 있으면 그것을 쓰고, 없으면 모른다고 한다.
            if _cache:
                return _cache[1]
            raise LocksUnavailable(_reason or "잠금 상태를 읽지 못했습니다")
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


def _holder(entry: dict | None) -> str:
    """이 행을 실제로 쥐고 있는 사람. 풀린 행(소유자 빈칸)은 아무도 아니다.

    해제할 때 행을 지우지 않고 소유자만 비운다 — 행을 지우면 그 아래 행 번호가 밀려서
    그 순간 다른 사람이 보낸 저장이 엉뚱한 행에 떨어진다(2026-08-29 실측).
    그래서 "행이 있다"와 "잠겨 있다"가 더 이상 같은 뜻이 아니다.
    """
    return str((entry or {}).get("owner") or "")


def status(
    kind: str, month: int, owner: str, now: datetime | None = None,
    fresh: bool = False,
) -> LockStatus:
    """잠금 상태. `fresh=True`면 캐시를 건너뛰고 저장소를 다시 읽는다.

    **저장 직전에는 반드시 fresh=True로 확인해야 한다.** 캐시(_CACHE_TTL초) 때문에,
    그 사이 남이 강제 해제하고 가져간 잠금을 여전히 "내 것"으로 보고 저장하는 경로가
    있었다(2026-08-30).
    """
    now = now or datetime.now()
    try:
        entry = _read(use_cache=not fresh).get(_key(kind, month))
    except LocksUnavailable:
        # 모르면 "남이 쥐고 있다"로 답한다 — 편집을 막을지언정 두 사람이 같이 들어가게
        # 두지는 않는다.
        return LockStatus("other")
    if not _holder(entry):
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


def _delete_entry(key: str, expected_rev: int | None = None) -> tuple[bool, str | None]:
    """잠금을 푼다. **결과를 돌려준다** — 호출자가 재시도할 수 있어야 한다.

    예전에는 결과를 버렸다. 그래서 해제 '쓰기'가 429로 실패해도 조용히 끝났고,
    남이 그 블록을 최대 TTL(15분) 동안 못 만졌다(2026-08-30).
    """
    clear_cache()
    if google_sheets_writer.configured():
        return google_sheets_writer.delete_lock(key, expected_rev=expected_rev)
    data = _read_local()
    if data.pop(key, None) is not None:
        _write_local(data)
    return True, None


def acquire(kind: str, month: int, owner: str, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    key = _key(kind, month)

    if store.is_firestore():
        # 트랜잭션 하나로 "읽고 판단하고 쓰기"가 끝난다 → claim-then-verify도, 0.5초
        # 정착 대기도 필요 없다. 겹침이 원리적으로 불가능하다.
        clear_cache()
        ok, reason = fs_store.acquire_lock(key, owner, now, LOCK_TTL_MINUTES)
        if reason:
            return False          # 저장소를 못 만졌다 — 모르면 안 잡는다
        return ok

    # 획득은 반드시 최신 상태로 판단한다 — 캐시된 "free"를 믿으면 이미 남이 잡은 블록을
    # 잡았다고 착각한다. 아예 못 읽었으면 잡지 않는다(모르면 안 잡는 쪽이 안전하다).
    try:
        data = _read(use_cache=False)
    except LocksUnavailable:
        return False
    entry = data.get(key) or {}
    stamp = now.isoformat(timespec="seconds")

    if _holder(entry):
        elapsed = _held_minutes(entry, now)
        mine = entry.get("owner") == owner
        if not mine and elapsed < LOCK_TTL_MINUTES:
            return False
        acquired = entry.get("acquired_at", stamp) if mine else stamp
    else:
        # 아무도 안 쥔 행(처음이거나 방금 풀린 행)이다. rev는 그 행의 것을 그대로 써야
        # 한다 — 0으로 넘기면 이미 있는 행과 어긋나 "conflict"로 거부된다.
        acquired = stamp

    # rev 비교(compare-and-set)로 먼저 거른다. 다만 **시트에는 원자적 CAS가 없다** —
    # rev를 읽는 것과 쓰는 것이 서로 다른 API 호출이라, 여섯이 동시에 달려들면 여럿이
    # 같은 rev를 읽고 모두 통과한다(2026-08-29 실측: 6명 중 5명이 동시에 임계구역에
    # 들어갔다). 그래서 쓰기만으로는 잠금이 되지 않는다.
    if not _save_entry(key, owner, acquired, stamp,
                       expected_rev=int(entry.get("rev", 0))):
        return False

    # **claim-then-verify**: 내가 쓴 뒤 잠깐 기다렸다 다시 읽어, 그 사이 남의 쓰기가
    # 나를 덮어쓰지 않았는지 확인한다. 동시에 쓴 사람이 여럿이어도 마지막에 남는 주인은
    # 하나뿐이므로, 자기 이름이 남아 있는 사람만 잠금을 가진 것으로 본다.
    time.sleep(_CLAIM_SETTLE_SECONDS)
    try:
        fresh = _read(use_cache=False).get(key)
    except LocksUnavailable:
        return False
    return _holder(fresh) == owner


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

    if store.is_firestore():
        clear_cache()
        ok, _reason = fs_store.touch_lock(key, owner, now, LOCK_TTL_MINUTES)
        return ok

    try:
        entry = _read().get(key)
    except LocksUnavailable:
        return False
    if _holder(entry) != owner:
        return False
    elapsed_seconds = _held_minutes(entry, now) * 60
    if elapsed_seconds >= LOCK_TTL_MINUTES * 60:
        return False
    if elapsed_seconds < _TOUCH_INTERVAL_SECONDS:
        return True  # 방금 갱신됐다 — 쓰지 않는다

    try:
        fresh = _read(use_cache=False).get(key)
    except LocksUnavailable:
        return False
    if _holder(fresh) != owner:
        return False
    if _held_minutes(fresh, now) >= LOCK_TTL_MINUTES:
        return False
    return _save_entry(
        key, owner, fresh.get("acquired_at", now.isoformat(timespec="seconds")),
        now.isoformat(timespec="seconds"), expected_rev=int(fresh.get("rev", 0)),
    )


def release(kind: str, month: int, owner: str) -> None:
    key = _key(kind, month)

    if store.is_firestore():
        # 확인과 쓰기가 같은 트랜잭션 안에 있으므로, 사전 확인이 낡아 남의 잠금을 지우는
        # 일이 생기지 않는다. 실패하면 몇 번 더 시도한다(놓치면 남이 TTL 동안 막힌다).
        for attempt in range(3):
            clear_cache()
            ok, _reason = fs_store.release_lock(key, owner)
            if ok:
                return
            time.sleep(0.4 * (attempt + 1))
        return
    # 해제에 실패하면 남이 그 블록을 못 만진다(최대 TTL). 한 번 실패했다고 포기하지 않고
    # 몇 번 더 해본다 — 접속이 몰린 순간은 대개 몇 초면 지나간다.
    # 첫 시도는 캐시로 본다. 진짜 방어선은 아래 rev 대조다 — 캐시가 낡아 남이 이미
    # 가져갔다면 그 대조에서 거부되고, 다음 바퀴에서 최신을 다시 읽는다. 예전에는 대조가
    # 없어서 사전 확인이 낡으면 **남의 잠금을 지웠다.**
    for attempt in range(3):
        try:
            entry = _read(use_cache=(attempt == 0)).get(key)
        except LocksUnavailable:
            time.sleep(0.4 * (attempt + 1))
            continue
        if _holder(entry) != owner:
            return                      # 내 것이 아니다 — 건드리지 않는다
        ok, reason = _delete_entry(key, expected_rev=int((entry or {}).get("rev", 0)))
        if ok:
            return
        if reason == "deleted":
            return                      # 행이 사라졌다 — 이미 풀린 것이다
        # 해제 **쓰기**가 실패했다. 예전에는 여기서 그냥 끝나 잠금이 남았다.
        time.sleep(0.4 * (attempt + 1))


def force_release(kind: str, month: int) -> None:
    if store.is_firestore():
        clear_cache()
        fs_store.force_release_lock(_key(kind, month))
        return
    _delete_entry(_key(kind, month))
