"""화면 한 번을 그릴 때 필요한 시트 탭을 **한 번의 호출**로 읽어 각 모듈 캐시에 나눠 담는다.

왜 필요한가: 구글 시트 API 읽기 한도는 **분당 60회이고 서비스 계정(=사용자) 단위**다.
프로젝트 단위가 아니라서 여러 명이 함께 쓰면 그 하나의 한도를 나눠 갖는다. 조작 한 번에
블록 1회 + 강조 1회를 읽던 구조에서는 전체 사용자 합쳐 분당 30회 조작이 상한이었고,
6명이 동시에 쓰자 15초 만에 429가 났다(2026-08-29 실측).

`values.batchGet`은 탭을 몇 개 읽든 **호출 1회**로 계산된다. 그래서 화면을 그리기 직전에
여기서 한 번에 읽고, blocks·highlights·locks 캐시에 넣어 둔다.

안전 규칙:
- 저장 경로는 이 캐시를 쓰지 않는다. `blocks.mutate`와 `highlights.apply`는 늘 시트를
  다시 읽고 `rev`를 대조한다 — 낡은 값으로 남의 작업을 덮어쓰지 않기 위해서다.
- `empty`(탭이 아직 없음)는 담지 않는다. 블록·강조에는 "예전 형식에서 한 번 옮기는"
  이관 경로가 걸려 있어, 빈 값을 정상으로 담아두면 그 이관이 건너뛰어진다.
- 읽기 실패(`error`)도 담지 않는다. 실패를 "데이터 없음"으로 굳히면 그 위에 빈 값을
  저장하는 최악의 사고로 이어진다.

⚠ **Firestore 백엔드에서는 이 모듈이 아무 일도 하지 않는다.** Firestore에는 분당 절벽이
없어(하루 5만 읽기) 미리 읽기의 존재 이유가 사라지고, 무엇보다 **저장은 Firestore인데
화면 캐시를 시트에서 심으면** 지운 블록이 되살아나 보인다. 2026-09-01 컷오버 직후 실제로
그 사고가 났다 — 편집 모드에서 블록을 지우면 Firestore에서는 지워지는데, 다음 리런에서
여기가 시트의 옛 행을 캐시에 심어 보기 모드에 그대로 다시 나타났다.
"""

from __future__ import annotations

import blocks
import google_sheets_writer
import highlights
import locks
import store


def warm(month: int) -> bool:
    """이 달 화면에 필요한 탭들을 한 번에 읽어 캐시에 담는다. 담았으면 True.

    **이미 신선하면 아무것도 하지 않는다.** 예전에는 캐시를 보지 않고 리런마다 무조건
    batchGet을 쏴서, 시트 읽기가 사람 수에 그대로 비례했다(6명 실측 분당 55회 / 한도 60회).
    캐시는 프로세스 전역이라 한 사람이 읽어 오면 그 순간 접속한 전원이 같이 쓴다 — 이
    게이트 하나로 읽기 상한이 인원과 무관해진다.
    """
    # 저장소가 Firestore면 미리 읽기를 하지 않는다. 여기서 시트를 읽어 캐시에 심으면
    # 화면이 저장소와 다른 곳을 보게 된다(지운 블록이 되살아난다).
    if store.is_firestore():
        return False

    if not google_sheets_writer.configured():
        return False

    month = int(month)
    if (blocks.cache_is_fresh(month) and highlights.cache_is_fresh(month)
            and locks.cache_is_fresh()):
        return False
    block_tab = google_sheets_writer.block_rows_tab(month)
    highlight_tab = google_sheets_writer.hl_cells_tab(month)
    lock_tab = google_sheets_writer.LOCKS_TAB

    try:
        reads = google_sheets_writer.store_read_many(
            [block_tab, highlight_tab, lock_tab]
        )
    except Exception:  # noqa: BLE001 - 미리 읽기는 실패해도 화면이 그대로 돌아야 한다
        return False

    seeded = False

    block_read = reads.get(block_tab)
    if block_read is not None and block_read.ok:
        status, items, _reason = google_sheets_writer.read_block_rows(
            month, known_read=block_read
        )
        if status == "ok":
            blocks.seed_state(month, items)
            seeded = True

    highlight_read = reads.get(highlight_tab)
    if highlight_read is not None and highlight_read.ok:
        status, data, _reason = google_sheets_writer.read_hl_cells(
            month, known_read=highlight_read
        )
        if status == "ok":
            highlights.seed_cache(month, data)
            seeded = True

    lock_read = reads.get(lock_tab)
    if lock_read is not None and not lock_read.failed:
        status, data, _reason = google_sheets_writer.read_locks(known_read=lock_read)
        if status in ("ok", "empty"):
            locks.seed_cache(data)
            seeded = True

    return seeded
