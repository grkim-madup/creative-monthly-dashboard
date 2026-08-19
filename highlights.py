"""표에서 사용자가 그때그때 고른 셀 강조(굵게+배경색)를 월별로 저장한다.

`st.dataframe`은 캔버스로 그려져 pandas Styler의 border는 무시하지만(실측 확인),
background-color·font-weight는 반영된다 — 그래서 "굵은 선" 대신 이 조합으로 강조한다.
셀은 (그 표 안에서의 행 위치, 컬럼명)으로 식별한다. 같은 달·같은 표를 다시 열면 저장된
위치 그대로 선택 상태를 복원하지만, 표의 행 순서 자체가 바뀌면(정렬 기준 변경 등) 다른
셀을 가리킬 수 있다 — 같은 달 안에서 조건을 그대로 유지하는 일반적인 사용 방식에서는
문제없다.

저장 위치: `notes/highlights_<월>.json`
"""

from __future__ import annotations

import json
from pathlib import Path

HIGHLIGHTS_DIR = Path(__file__).resolve().parent / "notes"


def _path(month: int) -> Path:
    return HIGHLIGHTS_DIR / f"highlights_{int(month)}.json"


def load(month: int, table_key: str) -> list[tuple[int, str]]:
    """저장된 강조 셀 목록을 돌려준다. 없거나 파일이 깨졌으면 빈 목록."""
    path = _path(month)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get(table_key)
    if not isinstance(raw, list):
        return []
    cells = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            cells.append((int(item[0]), str(item[1])))
    return cells


def save(month: int, table_key: str, cells: list) -> None:
    """이 표의 강조 셀을 통째로 덮어쓴다(빈 목록을 주면 강조를 전부 지운다)."""
    path = _path(month)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, OSError):
        data = {}

    normalized = [[int(r), str(c)] for r, c in cells]
    if normalized:
        data[table_key] = normalized
    else:
        data.pop(table_key, None)

    HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
