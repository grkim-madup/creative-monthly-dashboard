"""코멘트 블록의 편집 잠금.

한 번에 한 명만 같은 (블록, 월)을 편집하도록 막는다. 로그인이 없으므로 소유자는
브라우저 세션이 발급한 토큰이며, 이름은 다루지 않는다.

저장 위치: `notes/locks.json` — 서버가 한 대일 때를 전제로 한 선택이다.
인스턴스가 늘어나면 이 파일 하나만 다른 저장소로 갈아끼우면 된다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOCKS_PATH = Path(__file__).resolve().parent / "notes" / "locks.json"

# 편집을 열어둔 채 자리를 뜬 잠금은 스스로 풀려야 한다
LOCK_TTL_MINUTES = 15
# 막 시작한 사람을 실수로 밀어내지 않도록, 이 시간이 지나야 강제 해제를 노출한다
STEAL_AFTER_MINUTES = 5


@dataclass
class LockStatus:
    state: str  # "free" | "mine" | "other"
    held_minutes: float = 0.0


def _key(kind: str, month: int) -> str:
    return f"{kind}@{int(month)}"


def _read() -> dict:
    if not LOCKS_PATH.exists():
        return {}
    try:
        data = json.loads(LOCKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    LOCKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # blocks.save_blocks와 같은 이유로 원자적 교체를 쓴다 — 쓰는 도중 끊기면 잠금 파일이
    # 통째로 깨져 모두의 잠금이 한꺼번에 사라진다.
    tmp = LOCKS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, LOCKS_PATH)


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


def acquire(kind: str, month: int, owner: str, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    current = status(kind, month, owner, now)
    if current.state == "other":
        return False
    data = _read()
    stamp = now.isoformat(timespec="seconds")
    existing = data.get(_key(kind, month)) or {}
    acquired = existing.get("acquired_at", stamp) if current.state == "mine" else stamp
    data[_key(kind, month)] = {
        "owner": owner, "acquired_at": acquired, "touched_at": stamp,
    }
    _write(data)
    return True


def touch(kind: str, month: int, owner: str, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if status(kind, month, owner, now).state != "mine":
        return False
    data = _read()
    # status()가 자기 몫으로 한 번 읽고 여기서 또 읽는다. 그 사이 누군가 강제 해제했다면
    # 항목이 사라져 있으므로, 바로 인덱싱하면 KeyError로 페이지가 통째로 죽는다.
    entry = data.get(_key(kind, month))
    if not entry:
        return False
    entry["touched_at"] = now.isoformat(timespec="seconds")
    _write(data)
    return True


def release(kind: str, month: int, owner: str) -> None:
    data = _read()
    entry = data.get(_key(kind, month))
    if entry and entry.get("owner") == owner:
        del data[_key(kind, month)]
        _write(data)


def force_release(kind: str, month: int) -> None:
    data = _read()
    if data.pop(_key(kind, month), None) is not None:
        _write(data)
