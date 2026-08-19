"""리포트의 분석 블록 구성.

5번(소재 찾아보기)과 7번(NEXT STEP)은 고정 섹션이 아니라 블록의 목록이다. 매달 분석 축이
달라지므로 월별 파일로 나누고, 새 달은 빈 상태에서 시작한다.

저장 위치: `notes/blocks_<월>.json`
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import next_step

BLOCKS_DIR = Path(__file__).resolve().parent / "notes"

SLOT_ANALYSIS = "analysis"
SLOT_NEXT_STEP = "next_step"
SLOTS = (SLOT_ANALYSIS, SLOT_NEXT_STEP)

# 블록 타입별 기본 형태. update_block은 여기 있는 키만 반영한다.
BLOCK_DEFAULTS: dict[str, dict] = {
    "creative_query": {"title": "", "conditions": {}, "show_table": True, "comment": ""},
    "note": {"title": "", "comment": "", "images": [], "tables": [],
             "image_max_height": next_step.DEFAULT_IMAGE_MAX_HEIGHT},
}


def blocks_path(month: int) -> Path:
    return BLOCKS_DIR / f"blocks_{int(month)}.json"


def empty_blocks() -> dict:
    return {SLOT_ANALYSIS: [], SLOT_NEXT_STEP: []}


def save_blocks(month: int, data: dict) -> Path:
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {slot: list(data.get(slot, [])) for slot in SLOTS}
    path = blocks_path(month)
    # write_text는 먼저 파일을 잘라내기 때문에, 쓰는 도중 끊기면 한 달치 블록이 깨진 JSON으로
    # 남는다. 임시 파일에 다 쓴 뒤 os.replace로 갈아끼우면 교체가 원자적이라
    # 이전 내용이나 새 내용 둘 중 하나만 남는다(중간 상태가 없다).
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


# 손상 파일을 격리했다는 사실을 화면에 알리기 위한 자리. load_blocks는 Streamlit을 몰라야 하므로
# 여기에 남겨두고, 대시보드가 pop_corruption으로 한 번만 꺼내 st.error로 띄운다.
_CORRUPTIONS: dict[int, str] = {}


def pop_corruption(month: int) -> str | None:
    """직전 load_blocks에서 격리된 손상 파일 경로를 한 번만 돌려준다."""
    return _CORRUPTIONS.pop(int(month), None)


def quarantine_corrupt(month: int) -> str | None:
    """깨진 블록 파일을 지우지 않고 옆에 치워둔다.

    그냥 빈 값을 돌려주면 다음 저장이 손상 파일을 덮어써서 복구할 길이 영영 사라진다.
    """
    path = blocks_path(month)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"blocks_{int(month)}.corrupt-{stamp}.json")
    try:
        os.replace(path, target)
    except OSError:
        return None
    _CORRUPTIONS[int(month)] = str(target)
    return str(target)


def load_blocks(month: int) -> dict:
    """블록 구성을 읽는다. 파일이 없으면 예전 노트를 한 번 옮겨 온다."""
    path = blocks_path(month)
    if not path.exists():
        migrated = migrate_legacy_notes(month)
        if migrated is not None:
            return migrated
        # 옮길 게 없어도 빈 파일을 써 둔다 — 안 그러면 이 분기(예전 노트 조회)를
        # 매번 다시 타서 파일이 생길 때까지 계속 같은 비용을 반복하게 된다.
        empty = empty_blocks()
        save_blocks(month, empty)
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        quarantine_corrupt(month)
        return empty_blocks()
    except OSError:
        # 읽기 실패는 파일이 깨졌다는 뜻이 아니다(권한·일시적 잠금 등) — 건드리지 않는다.
        return empty_blocks()
    if not isinstance(data, dict):
        return empty_blocks()
    result = empty_blocks()
    for slot in SLOTS:
        value = data.get(slot)
        if isinstance(value, list):
            result[slot] = [b for b in value if isinstance(b, dict) and b.get("id")]
    return result


def mutate(month: int, fn) -> dict:
    """디스크의 최신 상태를 다시 읽어 고치고 저장한다(read-modify-write).

    화면은 실행 시작 시점에 읽은 스냅샷을 들고 있는데, 그 사이 다른 사람이 자기 블록을
    저장했을 수 있다. 스냅샷을 그대로 통째로 쓰면 남의 저장이 소리 없이 되돌아간다 —
    블록 단위 잠금으로는 못 막는다(각자 자기 블록의 정당한 주인이기 때문).
    """
    data = load_blocks(month)
    fn(data)
    save_blocks(month, data)
    return data


def add_block(
    data: dict, slot: str, block_type: str, title: str = "", position: int | None = None
) -> str:
    """블록을 추가한다. position을 주면 그 자리에 끼워 넣는다(없으면 맨 뒤).

    노션처럼 "블록 사이"에 넣을 수 있어야 순서를 다시 옮기지 않아도 되므로 위치를 받는다.
    """
    block_id = uuid4().hex[:6]
    block = {"id": block_id, "type": block_type}
    # BLOCK_DEFAULTS의 dict/list 값(conditions/images/tables)은 모듈 전역에 하나뿐이라
    # 얕은 복사로 넣으면 모든 블록이 같은 객체를 공유해 한 블록의 in-place 수정이
    # 같은 타입의 다른 블록까지 전부 오염시킨다 — 반드시 깊은 복사로 떼어낸다.
    block.update(copy.deepcopy(BLOCK_DEFAULTS.get(block_type, {})))
    if title:
        block["title"] = title
    items = data.setdefault(slot, [])
    if position is None or position >= len(items):
        items.append(block)
    else:
        items.insert(max(position, 0), block)
    return block_id


def find_block(data: dict, slot: str, block_id: str) -> dict | None:
    for block in data.get(slot, []):
        if block.get("id") == block_id:
            return block
    return None


def remove_block(data: dict, slot: str, block_id: str) -> None:
    data[slot] = [b for b in data.get(slot, []) if b.get("id") != block_id]


def move_block(data: dict, slot: str, block_id: str, delta: int) -> None:
    items = data.get(slot, [])
    ids = [b.get("id") for b in items]
    if block_id not in ids:
        return
    index = ids.index(block_id)
    target = index + delta
    if not 0 <= target < len(items):
        return
    items[index], items[target] = items[target], items[index]


def update_block(data: dict, slot: str, block_id: str, **fields) -> None:
    block = find_block(data, slot, block_id)
    if block is None:
        return
    allowed = BLOCK_DEFAULTS.get(block.get("type"), {})
    block.update({k: v for k, v in fields.items() if k in allowed})


def migrate_legacy_notes(month: int) -> dict | None:
    """예전 insight/next_step 노트를 블록 하나씩으로 옮긴다.

    옮길 게 없으면 None. 원본 파일은 지우지 않는다 — 되돌릴 수 있어야 한다.
    `blocks_<월>.json`이 생기는 순간 이관은 끝나므로 중복 실행되지 않는다.
    """
    insight = next_step.load_note(month, kind="insight")
    legacy = next_step.load_note(month)
    # 아래 본문은 legacy를 'markdown 또는 images 또는 tables'로 판단하므로 가드도 같은 기준이어야
    # 한다. 본문만 이미지·표인 노트가 여기서 걸러지면 이관되지 않고, 그 직후 빈 blocks 파일이
    # 만들어져 다시 이관될 기회조차 사라진다.
    if not insight.get("markdown") and not (
        legacy.get("markdown") or legacy.get("images") or legacy.get("tables")
    ):
        return None

    data = empty_blocks()
    if insight.get("markdown"):
        block_id = add_block(data, SLOT_ANALYSIS, "creative_query", "제작 인사이트")
        update_block(data, SLOT_ANALYSIS, block_id,
                     comment=insight["markdown"], show_table=False)
    if legacy.get("markdown") or legacy.get("images") or legacy.get("tables"):
        block_id = add_block(data, SLOT_NEXT_STEP, "note", "다음 달 액션")
        update_block(data, SLOT_NEXT_STEP, block_id,
                     comment=legacy.get("markdown", ""),
                     images=list(legacy.get("images", [])),
                     tables=list(legacy.get("tables", [])),
                     image_max_height=legacy.get("image_max_height")
                     or next_step.DEFAULT_IMAGE_MAX_HEIGHT)
    save_blocks(month, data)
    return data
