"""표에서 사용자가 그때그때 고른 셀 강조(굵게+배경색)를 월별로 저장한다.

`st.dataframe`은 캔버스로 그려져 pandas Styler의 border는 무시하지만(실측 확인),
background-color·font-weight는 반영된다 — 그래서 "굵은 선" 대신 이 조합으로 강조한다.
셀은 (그 표 안에서의 행 위치, 컬럼명)으로 식별한다. 같은 달·같은 표를 다시 열면 저장된
위치 그대로 선택 상태를 복원하지만, 표의 행 순서 자체가 바뀌면(정렬 기준 변경 등) 다른
셀을 가리킬 수 있다 — 같은 달 안에서 조건을 그대로 유지하는 일반적인 사용 방식에서는
문제없다.

저장 위치: `google_sheets_writer`가 설정돼 있으면 전용 구글시트 `hlcells_<월>` 탭에
**셀 하나당 한 행**. 아니면 `notes/highlights_<월>.json`.

왜 셀마다 한 행인가 (2026-08-29, 실측 두 번 끝에):
- 처음에는 표 하나의 강조 목록을 한 셀에 JSON으로 넣고 통째로 덮어썼다. 두 사람이 같은
  표를 거의 동시에 강조하면 늦게 저장한 쪽이 앞사람 강조를 지웠다(6명 동시 → 1개만 생존).
- 다음으로 행의 `rev`를 대조해 쓰도록 고쳤다(compare-and-set). 그래도 6명 중 3명 것이
  사라졌다 — 시트 API는 읽기와 쓰기가 원자적이지 않아, 같은 행을 겨냥한 여섯이 모두
  같은 rev를 읽고 통과해 버린다. **같은 행에 동시에 쓰는 구조 자체가 문제**였다.
- 그래서 이 프로젝트의 원칙("키 하나 = 행 하나")대로 셀마다 행을 나눴다. 서로 다른 셀은
  다른 행이라 충돌이 원리적으로 없고, 같은 셀을 둘이 켜면 같은 값이 두 번 쓰일 뿐이다.
  블록이 같은 방식으로 6명 동시에도 무사했던 것과 같은 이유다.

읽기 캐시: 강조는 표를 그릴 때마다 조회되므로(한 화면에 표가 여러 개다) 시트를 매번 읽으면
리런 한 번에 API 호출이 열 번 넘게 나간다. 월 단위로 짧게(_CACHE_TTL초) 캐시하고 저장 직후
갱신한다. 다른 사람의 강조는 최대 그 시간만큼 늦게 보인다 — 쓰기가 있는 값에 긴 TTL을 걸면
"고쳤는데 화면이 그대로"인 조용한 오류가 나므로 짧게 유지한다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import google_sheets_writer

HIGHLIGHTS_DIR = Path(__file__).resolve().parent / "notes"

_CACHE_TTL = 20.0
_CACHE: dict[int, tuple[float, dict]] = {}


def _path(month: int) -> Path:
    return HIGHLIGHTS_DIR / f"highlights_{int(month)}.json"


def _normalize_cells(raw) -> list[tuple[int, str]]:
    if not isinstance(raw, list):
        return []
    cells = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                cells.append((int(item[0]), str(item[1])))
            except (TypeError, ValueError):
                continue
    return cells


def _read_local_all(month: int) -> dict:
    path = _path(month)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_local_all(month: int, data: dict) -> None:
    HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(month)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _update_cache(month: int, table_key: str, cells: list) -> None:
    """방금 저장한 값을 캐시에 반영한다(시트를 다시 읽지 않기 위해).

    캐시가 아직 없으면 아무것도 하지 않는다 — 다음 load()가 시트에서 통째로 읽는다.
    남이 같은 달의 다른 표를 고친 것은 기존 TTL(_CACHE_TTL)이 지나면 반영된다.
    """
    cached = _CACHE.get(int(month))
    if not cached:
        return
    data = dict(cached[1])
    if cells:
        data[table_key] = [[int(r), str(c)] for r, c in cells]
    else:
        data.pop(table_key, None)
    _CACHE[int(month)] = (cached[0], data)


def seed_cache(month: int, data: dict) -> None:
    """다른 곳에서 이미 읽어 온 이 달의 강조 전체를 캐시에 넣는다.

    화면 한 번을 그릴 때 블록·강조·잠금을 batchGet으로 **한 번에** 읽고 그 결과를
    각 모듈에 나눠 담는다(prefetch.py). 여기 없으면 load_all이 시트를 또 읽는다.
    """
    _CACHE[int(month)] = (time.monotonic(), data)


def clear_cache(month: int | None = None) -> None:  # noqa: D401
    if month is None:
        _CACHE.clear()
    else:
        _CACHE.pop(int(month), None)


def _migrate_from_table_rows(month: int) -> dict:
    """예전 형식(표 하나 = 한 행)과 로컬 파일에서 한 번만 옮긴다. 원본은 지우지 않는다."""
    status, data, _reason = google_sheets_writer.read_highlights(month)
    if status == "error":
        return {}
    if not data:
        data = _read_local_all(month)
    for table_key, cells in data.items():
        google_sheets_writer.add_hl_cells(month, table_key, _normalize_cells(cells))
    # 이관 표식 — 없으면 사용자가 전부 지운 강조가 예전 탭에서 되살아난다.
    google_sheets_writer.mark_migrated(
        google_sheets_writer.hl_cells_tab(month), google_sheets_writer.HL_CELL_HEADER
    )
    return data


def load_all(month: int) -> dict:
    """이 달의 {표 키: 셀 목록} 전체를 돌려준다."""
    month = int(month)
    cached = _CACHE.get(month)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    if not google_sheets_writer.configured():
        data = _read_local_all(month)
    else:
        status, data, _reason = google_sheets_writer.read_hl_cells(month)
        if status == "error":
            # 읽기 실패를 "강조 없음"으로 오인해 저장하면 전부 사라진다 — 쓰지 않는다.
            return {}
        if status == "empty":
            data = _migrate_from_table_rows(month)

    _CACHE[month] = (time.monotonic(), data)
    return data


def load(month: int, table_key: str) -> list[tuple[int, str]]:
    """저장된 강조 셀 목록을 돌려준다. 없으면 빈 목록."""
    return _normalize_cells(load_all(month).get(table_key))


def apply(month: int, table_key: str, add=(), remove=()) -> tuple[bool, str | None]:
    """이 표의 강조에 `add`를 켜고 `remove`를 끈다. 남의 강조는 건드리지 않는다.

    화면이 들고 있는 목록을 통째로 덮어쓰지 않고 **바뀐 셀의 행만** 만진다. 그래서 두
    사람이 같은 표의 다른 셀을 동시에 강조해도 서로 다른 행이라 둘 다 남는다.
    """
    month = int(month)
    to_add = [(int(r), str(c)) for r, c in add]
    to_remove = [(int(r), str(c)) for r, c in remove]
    if not to_add and not to_remove:
        return True, None

    if not google_sheets_writer.configured():
        clear_cache(month)
        data = _read_local_all(month)
        merged = (
            set(_normalize_cells(data.get(table_key))) | set(to_add)
        ) - set(to_remove)
        if merged:
            data[table_key] = [[r, c] for r, c in sorted(merged)]
        else:
            data.pop(table_key, None)
        _write_local_all(month, data)
        return True, None

    ok, reason = google_sheets_writer.add_hl_cells(month, table_key, to_add)
    if not ok:
        clear_cache(month)
        return False, reason
    ok, reason = google_sheets_writer.remove_hl_cells(month, table_key, to_remove)
    if not ok:
        clear_cache(month)
        return False, reason

    # 캐시에는 내가 아는 범위만 반영한다. 남이 같은 순간에 켠 셀은 TTL이 지나면 보인다.
    cached = _CACHE.get(month)
    if cached:
        current = set(_normalize_cells(cached[1].get(table_key)))
        _update_cache(
            month, table_key, sorted((current | set(to_add)) - set(to_remove))
        )
    return True, None


def save(month: int, table_key: str, cells: list) -> tuple[bool, str | None]:
    """이 표의 강조를 주어진 목록으로 맞춘다(빈 목록이면 전부 지운다).

    **덮어쓰기 의미다.** 사용자가 셀을 켜고 끄는 경로에서는 `apply`를 써야 한다 —
    이 함수는 초기화·이관처럼 "이 값이 전부"임이 확실할 때만 쓴다. 내부적으로도 통째로
    쓰지 않고, 현재 상태와의 차이만 행 단위로 반영한다.
    """
    month = int(month)
    wanted = {(int(r), str(c)) for r, c in cells}
    current = set(load(month, table_key))
    if wanted == current:
        return True, None
    return apply(
        month, table_key, add=sorted(wanted - current), remove=sorted(current - wanted)
    )
