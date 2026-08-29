"""표에서 사용자가 그때그때 고른 셀 강조(굵게+배경색)를 월별로 저장한다.

`st.dataframe`은 캔버스로 그려져 pandas Styler의 border는 무시하지만(실측 확인),
background-color·font-weight는 반영된다 — 그래서 "굵은 선" 대신 이 조합으로 강조한다.
셀은 (그 표 안에서의 행 위치, 컬럼명)으로 식별한다. 같은 달·같은 표를 다시 열면 저장된
위치 그대로 선택 상태를 복원하지만, 표의 행 순서 자체가 바뀌면(정렬 기준 변경 등) 다른
셀을 가리킬 수 있다 — 같은 달 안에서 조건을 그대로 유지하는 일반적인 사용 방식에서는
문제없다.

저장 위치: `google_sheets_writer`가 설정돼 있으면 전용 구글시트 `highlights_<월>` 탭에
**표 하나당 한 행**. 아니면 `notes/highlights_<월>.json`.

시트로 옮긴 이유: 배포판은 재배포·리부트마다 로컬 디스크가 초기화돼 강조가 조용히 사라졌다.
그리고 파일 하나를 통째로 다시 쓰던 방식은 두 사람이 서로 다른 표를 강조해도 늦게 저장한
쪽이 먼저 저장된 강조를 지웠다.

읽기 캐시: 강조는 표를 그릴 때마다 조회되므로(한 화면에 표가 여러 개다) 시트를 매번 읽으면
리런 한 번에 API 호출이 열 번 넘게 나간다. 월 단위로 짧게(_CACHE_TTL초) 캐시하고 저장 직후
비운다. 다른 사람의 강조는 최대 그 시간만큼 늦게 보인다 — 쓰기가 있는 값에 긴 TTL을 걸면
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


def clear_cache(month: int | None = None) -> None:
    if month is None:
        _CACHE.clear()
    else:
        _CACHE.pop(int(month), None)


def load_all(month: int) -> dict:
    """이 달의 {표 키: 셀 목록} 전체를 돌려준다."""
    month = int(month)
    cached = _CACHE.get(month)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    if not google_sheets_writer.configured():
        data = _read_local_all(month)
    else:
        status, data, _reason = google_sheets_writer.read_highlights(month)
        if status == "error":
            # 읽기 실패를 "강조 없음"으로 오인해 저장하면 전부 사라진다 — 쓰지 않는다.
            return {}
        if status == "empty":
            # 시트 백엔드를 켜기 전 로컬에 남아 있던 강조를 한 번 옮긴다.
            data = _read_local_all(month)
            for table_key, cells in data.items():
                google_sheets_writer.write_highlight(month, table_key, cells)
            # 이관 표식 — 없으면 사용자가 전부 지운 강조가 로컬 파일에서 되살아난다.
            google_sheets_writer.mark_migrated(
                f"highlights_{int(month)}", google_sheets_writer.HIGHLIGHT_HEADER
            )

    _CACHE[month] = (time.monotonic(), data)
    return data


def load(month: int, table_key: str) -> list[tuple[int, str]]:
    """저장된 강조 셀 목록을 돌려준다. 없으면 빈 목록."""
    return _normalize_cells(load_all(month).get(table_key))


def save(month: int, table_key: str, cells: list) -> None:
    """이 표의 강조 셀을 통째로 덮어쓴다(빈 목록을 주면 강조를 전부 지운다)."""
    normalized = [[int(r), str(c)] for r, c in cells]
    clear_cache(month)

    if google_sheets_writer.configured():
        if normalized:
            google_sheets_writer.write_highlight(month, table_key, normalized)
        else:
            google_sheets_writer.delete_highlight(month, table_key)
        return

    data = _read_local_all(month)
    if normalized:
        data[table_key] = normalized
    else:
        data.pop(table_key, None)
    _write_local_all(month, data)
