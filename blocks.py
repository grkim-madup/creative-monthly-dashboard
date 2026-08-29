"""리포트의 분석 블록 구성.

5번(소재 찾아보기)과 7번(NEXT STEP)은 고정 섹션이 아니라 블록의 목록이다. 매달 분석 축이
달라지므로 월별 파일로 나누고, 새 달은 빈 상태에서 시작한다.

저장 위치: `google_sheets_writer`(스냅샷용 서비스 계정)가 설정돼 있으면 전용 구글시트의
`blockrows_<월>` 탭에 **블록 하나당 한 행**. 아니면(로컬 개발 PC 등)
`notes/blocks_<월>.json` 로컬 파일 한 개.

왜 블록당 한 행인가: 예전에는 그 달 블록 전체를 `blocks_<월>!A1` 한 셀에 JSON으로 넣고
저장할 때마다 통째로 덮어썼다. 그러면 두 사람이 **서로 다른 블록**의 완료를 눌러도 늦게
저장한 쪽이 먼저 저장된 블록 편집을 조용히 지운다(lost update) — 블록 단위 잠금으로는
막을 수 없다(각자 자기 블록의 정당한 주인이기 때문). 행으로 쪼개고 바뀐 행만 갱신하면
이 충돌이 원리적으로 사라진다. 같은 블록을 동시에 저장하는 경우만 남고, 그건 `rev`
비교(compare-and-set)로 덮어쓰기를 **거부**한다.

예전 한 셀 형식(`blocks_<월>` 탭)은 지우지 않는다 — 새 탭 이름이 다르므로 이관이
잘못돼도 원본이 그대로 남아 되돌릴 수 있다.

시트 백엔드가 필요한 이유: 배포판(Streamlit Community Cloud)은 재배포·리부트마다
로컬 디스크가 초기화된다. 로컬 파일만 믿으면 배포판에서 남긴 코멘트가 재배포 시점에
그대로 사라진다 — google_snapshot.py가 스냅샷을 시트에 영구 저장하는 것과 같은 이유로,
블록(코멘트·조건 등)도 같은 시트에 영구 저장한다.
"""

from __future__ import annotations

import copy
import json
import os
from time import monotonic
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import google_sheets_writer
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


def save_blocks(month: int, data: dict) -> Path | None:
    """전체를 통째로 저장한다(로컬 파일 모드, 그리고 이관·초기 생성 전용).

    편집 저장 경로에서는 이 함수를 쓰지 않는다 — `mutate`가 바뀐 행만 갱신한다.
    """
    payload = {slot: [_strip_meta(b) for b in data.get(slot, [])] for slot in SLOTS}
    if google_sheets_writer.configured():
        google_sheets_writer.ensure_block_rows_tab(month)
        for slot in SLOTS:
            for seq, block in enumerate(payload[slot]):
                google_sheets_writer.upsert_block_row(
                    month, block["id"], slot, seq, block
                )
        return None
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    path = blocks_path(month)
    # write_text는 먼저 파일을 잘라내기 때문에, 쓰는 도중 끊기면 한 달치 블록이 깨진 JSON으로
    # 남는다. 임시 파일에 다 쓴 뒤 os.replace로 갈아끼우면 교체가 원자적이라
    # 이전 내용이나 새 내용 둘 중 하나만 남는다(중간 상태가 없다).
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


# `_rev`는 시트 행의 버전이다. 블록 본문이 아니므로 저장 payload에서는 반드시 뺀다 —
# 안 그러면 rev가 본문 안에 눌러앉아 "바뀐 게 있나" 비교가 매번 어긋난다.
_META_FIELDS = ("_rev",)


def _strip_meta(block: dict) -> dict:
    return {k: v for k, v in block.items() if k not in _META_FIELDS}


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


@dataclass
class BlocksState:
    """블록 구성을 읽은 결과.

    status가 "error"면 **절대 저장하지 않는다.** 예전에는 읽기 실패와 "아직 데이터 없음"을
    똑같이 None으로 뭉개고 그 위에 빈 값을 저장했다 — 일시적 읽기 실패 한 번으로 그 달
    블록 전체가 전원에게서 사라질 수 있는 구조였다.
    """

    data: dict
    revs: dict = dc_field(default_factory=dict)  # block_id -> rev
    status: str = "ok"                           # "ok" | "error"
    reason: str | None = None


def _normalize(data: dict) -> dict:
    result = empty_blocks()
    for slot in SLOTS:
        value = data.get(slot)
        if isinstance(value, list):
            result[slot] = [b for b in value if isinstance(b, dict) and b.get("id")]
    return result


def _read_local_blocks_file(month: int) -> dict | None:
    """로컬 `blocks_<월>.json`을 그대로 읽는다(격리 없이). 없거나 깨졌으면 None."""
    path = blocks_path(month)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _state_from_rows(items: list[dict]) -> BlocksState:
    data = empty_blocks()
    revs: dict[str, int] = {}
    for item in sorted(items, key=lambda i: (i["slot"], i["seq"])):
        if item["slot"] not in SLOTS:
            continue
        block = dict(item["block"])
        block["_rev"] = item["rev"]
        data[item["slot"]].append(block)
        revs[item["block_id"]] = item["rev"]
    return BlocksState(data=data, revs=revs)


# 한 화면을 그릴 때 5번(분석)과 7번(NEXT STEP) 섹션이 각각 이 상태를 읽는다 — 같은 탭을
# 두 번 읽는 셈이라 조작당 API 호출이 그만큼 늘었다. 아주 짧게 캐시해 한 번의 렌더 안에서만
# 재사용한다. 저장(mutate)은 **절대 캐시를 쓰지 않고** 늘 시트를 다시 읽으며, 저장 직후
# 캐시를 비운다 — 낡은 rev로 "다른 사람이 수정했습니다"가 잘못 뜨는 일을 막기 위해서다.
_STATE_TTL = 3.0
_STATE_CACHE: dict[int, tuple[float, list[dict]]] = {}


def clear_state_cache(month: int | None = None) -> None:
    if month is None:
        _STATE_CACHE.clear()
    else:
        _STATE_CACHE.pop(int(month), None)


def seed_state(month: int, items: list[dict]) -> None:
    """다른 곳에서 읽어 온 블록 행들을 캐시에 넣는다(prefetch.py)."""
    _STATE_CACHE[int(month)] = (monotonic(), copy.deepcopy(items))


def load_state(month: int, use_cache: bool = False) -> BlocksState:
    """블록 구성 + 각 블록의 rev + 읽기 성공 여부를 함께 돌려준다.

    use_cache=True는 **화면을 그리는 경로 전용**이다. 저장 경로는 기본값(False)으로
    항상 최신을 읽는다.
    """
    if not google_sheets_writer.configured():
        return BlocksState(data=_load_blocks_from_disk(month))

    if use_cache:
        cached = _STATE_CACHE.get(int(month))
        if cached and (monotonic() - cached[0]) < _STATE_TTL:
            return _state_from_rows(copy.deepcopy(cached[1]))

    status, items, reason = google_sheets_writer.read_block_rows(month)
    if status == "error":
        # 여기서 빈 값을 돌려주고 저장까지 하면 그 순간 한 달치가 날아간다. 화면에는
        # 빈 리포트가 아니라 에러가 떠야 하고, 저장은 막혀야 한다.
        return BlocksState(data=empty_blocks(), status="error", reason=reason)
    if status == "ok":
        _STATE_CACHE[int(month)] = (monotonic(), copy.deepcopy(items))
        return _state_from_rows(items)

    # 새 형식 탭이 아직 없다 — 옮겨올 것이 있으면 한 번만 옮긴다.
    migrated = _migrate_into_rows(month)
    if migrated is not None:
        again, items, _ = google_sheets_writer.read_block_rows(month)
        if again == "ok":
            return _state_from_rows(items)
        return BlocksState(data=_normalize(migrated))
    # 옮길 게 없으면 헤더와 이관 표식만 남긴다 — 안 그러면 리런마다 이관 조회를 다시 탄다.
    google_sheets_writer.ensure_block_rows_tab(month)
    google_sheets_writer.mark_migrated(
        google_sheets_writer.block_rows_tab(month), google_sheets_writer.BLOCK_HEADER
    )
    return BlocksState(data=empty_blocks())


def _migrate_into_rows(month: int) -> dict | None:
    """예전 한 셀 형식 / 로컬 파일 / 레거시 노트를 새 행 형식으로 한 번 옮긴다.

    옮길 게 없으면 None. 원본은 어느 쪽도 지우지 않는다.
    """
    # 어느 경로로 옮겼든(또는 옮길 게 없었든) 표식을 남겨 다시 옮기지 않게 한다.
    legacy_cell = google_sheets_writer.read_blocks(month)
    if legacy_cell is not None and (
        legacy_cell.get(SLOT_ANALYSIS) or legacy_cell.get(SLOT_NEXT_STEP)
    ):
        normalized = _normalize(legacy_cell)
        save_blocks(month, normalized)
        google_sheets_writer.mark_migrated(
            google_sheets_writer.block_rows_tab(month), google_sheets_writer.BLOCK_HEADER
        )
        return normalized
    local = _read_local_blocks_file(month)
    if local is not None and (local.get(SLOT_ANALYSIS) or local.get(SLOT_NEXT_STEP)):
        normalized = _normalize(local)
        save_blocks(month, normalized)
        google_sheets_writer.mark_migrated(
            google_sheets_writer.block_rows_tab(month), google_sheets_writer.BLOCK_HEADER
        )
        return normalized
    migrated = migrate_legacy_notes(month)
    if migrated is not None:
        google_sheets_writer.mark_migrated(
            google_sheets_writer.block_rows_tab(month), google_sheets_writer.BLOCK_HEADER
        )
    return migrated


def load_blocks(month: int) -> dict:
    """블록 구성만 돌려준다(기존 호출부 호환). 읽기 실패 여부까지 필요하면 load_state."""
    return load_state(month).data


def _load_blocks_from_disk(month: int) -> dict:
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
    return _normalize(data)


def mutate(month: int, fn, expect: dict | None = None) -> tuple[bool, str | None]:
    """저장소의 최신 상태를 다시 읽어 고치고, **바뀐 블록만** 저장한다.

    화면은 실행 시작 시점에 읽은 스냅샷을 들고 있는데, 그 사이 다른 사람이 자기 블록을
    저장했을 수 있다. 그래서 저장 직전에 최신 상태를 다시 읽고, 그 위에 fn을 적용한 뒤
    실제로 달라진 행만 갱신한다 — 남의 블록은 아예 쓰기 대상에 들어가지 않는다.

    expect는 {block_id: 내가 화면에서 보고 있던 rev}다. 그 사이 같은 블록이 바뀌었으면
    아무것도 쓰지 않고 (False, "conflict")를 돌려준다 — 조용히 덮어쓰는 것보다 낫다.

    돌려주는 값: (성공 여부, 실패 이유).
    """
    clear_state_cache(month)
    state = load_state(month)
    if state.status == "error":
        return False, state.reason or "저장소를 읽지 못했습니다"

    if expect:
        for block_id, seen_rev in expect.items():
            if state.revs.get(block_id, 0) != int(seen_rev):
                return False, "conflict"

    baseline = {
        block["id"]: (slot, seq, _strip_meta(block))
        for slot in SLOTS
        for seq, block in enumerate(state.data.get(slot, []))
        if block.get("id")
    }
    fn(state.data)

    if not google_sheets_writer.configured():
        save_blocks(month, state.data)
        return True, None

    # 바뀐 행을 모아 **한 번에** 저장한다. 블록을 하나 추가하면 뒤따르는 블록의 seq가
    # 전부 밀려 여러 행이 달라지는데, 행마다 따로 저장하면 매번 탭을 다시 읽고 쓰느라
    # 왕복이 몇 배가 된다(실측: 추가 1회에 읽기 3번 + 쓰기 2번 = 2.3초).
    seen: set[str] = set()
    changed: list[dict] = []
    expected: dict = {}
    for slot in SLOTS:
        for seq, block in enumerate(state.data.get(slot, [])):
            block_id = block.get("id")
            if not block_id:
                continue
            seen.add(block_id)
            payload = _strip_meta(block)
            if baseline.get(block_id) == (slot, seq, payload):
                continue  # 바뀐 게 없으면 쓰지 않는다(쿼터·충돌 둘 다 줄인다)
            changed.append(
                {"block_id": block_id, "slot": slot, "seq": seq, "payload": payload}
            )
            expected[block_id] = state.revs.get(block_id, 0)

    if changed:
        ok, reason = google_sheets_writer.upsert_block_rows(
            month, changed, expected_revs=expected
        )
        if not ok:
            return False, reason
    removed = sorted(set(baseline) - seen)
    if removed:
        google_sheets_writer.delete_block_rows(month, removed)
    clear_state_cache(month)
    return True, None


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
