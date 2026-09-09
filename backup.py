# -*- coding: utf-8 -*-
"""코멘트 백업 — 모으고 문서로 만드는 **순수 로직**.

왜 `tools/`가 아니라 최상위인가: 동기화 스크립트는 **최상위 `*.py`와 `tests/`만**
배포판에 복사한다. 로직이 `tools/`에 있으면 화면에서 부를 수 없어서, 규리님이
백업하려면 매번 개발자가 터미널을 열어야 했다(2026-09-09에 *"내가 대시보드에서
버튼을 눌러?"* 라고 물어서 드러났다 — 그때까지 버튼이 없었다).

⚠ **읽기는 버튼을 누를 때만 일어나야 한다.** 화면이 그려질 때마다 모으면 무료 한도를
태운다 — 2026-09-08에 그렇게 라이브가 멈췄다. 그래서 이 모듈은 아무것도 캐시하지
않고, 부르는 쪽이 "지금 모아라"를 명시할 때만 읽는다.

⚠ **전체 백업(`tools/backup_store.py`)과 다르다.** 그쪽은 스냅샷 2,000행까지 읽어
쿼터가 흔들릴 때 실패한다(실제로 실패했다). 이 경로는 블록·강조·분류·수기지정만
뽑아 읽기 수십 회로 끝낸다 — 사고 당일 실제로 쓸 수 있었던 유일한 경로다.
"""
from __future__ import annotations

import html
import io
import json
import re
import time
import zipfile

import fs_store
import store

#: 리포트가 다루는 달. 데이터가 없는 달은 결과에서 빠진다.
MONTHS = range(2, 13)

SLOT_LABEL = {"analysis": "신규 소재 유형별 성과", "next_step": "NEXT STEP"}

#: 한 달에서 뽑는 것. 이름 = 백업 JSON의 키.
SOURCES = (
    ("blocks", "read_block_rows"),
    ("hlcells", "read_hl_cells"),
    ("overrides", "read_overrides"),
    ("picks", "read_picks"),
)


def _retry(fn, attempts: int = 5, sleep: float = 5.0):
    """쿼터가 흔들릴 때를 대비해 몇 번 다시 시도한다.

    실패를 **삼키지 않는다.** 못 읽은 것을 조용히 빼고 "백업 완료"라고 하면
    그게 가장 나쁜 실패다 — 정작 복구할 때 없다.
    """
    last = None
    for _ in range(attempts):
        status, data, reason = fn()
        if status in ("ok", "empty"):
            return status, data, None
        last = reason
        time.sleep(sleep)
    return "error", None, last


def plain(value: str) -> str:
    """Quill HTML을 사람이 읽는 평문으로. 백업의 요점은 **읽을 수 있는 것**이다."""
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""))
    text = re.sub(r"</(p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def collect(months=MONTHS, on_progress=None) -> tuple[dict, list[str]]:
    """저장소에서 백업 대상을 모은다. `(데이터, 못 읽은 것)`.

    `on_progress(월, 요약)`을 주면 진행 상황을 알려준다(화면 표시용).
    """
    # 시각은 **항상 KST**로 찍는다 — 배포 컨테이너는 UTC라서 그냥 `now()`를 쓰면
    # 백업 파일 이름과 내용이 9시간 어긋난다(예전에 화면에서 겪었다).
    out: dict = {
        "backed_up_at": store.report_timestamp(),
        "backend": store.backend(),
        "months": {},
    }
    failed: list[str] = []
    for month in months:
        bucket = {}
        for name, method in SOURCES:
            status, data, reason = _retry(
                lambda m=month, f=method: getattr(fs_store, f)(m))
            if status == "error":
                failed.append(f"{month}월 {name} ({str(reason)[:40]})")
            elif data:
                bucket[name] = data
        if bucket:
            out["months"][str(month)] = bucket
            if on_progress:
                on_progress(month, " · ".join(f"{k} {len(v)}" for k, v in bucket.items()))
    return out, failed


def stamp() -> str:
    """백업 파일 이름에 붙일 시각(`20260909_1249`).

    **항상 KST다** — 배포 컨테이너는 UTC라서 그냥 `now()`를 쓰면 파일 이름이 9시간
    어긋난다. 진입점과 터미널 도구가 이 함수를 함께 쓴다(각자 만들면 이름 규칙이
    갈린다).
    """
    return (store.report_timestamp()
            .replace("-", "").replace(":", "").replace(" ", "_"))


def to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def to_markdown(data: dict) -> str:
    """사람이 읽는 사본. Firestore 콘솔은 비개발자가 읽기 어렵다 —
    사고 당일 실제로 필요했던 건 이 형식이었다."""
    lines = [f"# 코멘트 백업 {data.get('backed_up_at', '')}", ""]
    for month, bucket in sorted(data.get("months", {}).items(),
                                key=lambda kv: int(kv[0])):
        rows = bucket.get("blocks") or []
        if not rows:
            continue
        lines += [f"## {month}월", ""]
        for row in sorted(rows, key=lambda r: (str(r.get("slot")), r.get("seq") or 0)):
            block = row.get("block") or {}
            slot = str(row.get("slot"))
            lines += [f"### [{SLOT_LABEL.get(slot, slot)}] "
                      f"{block.get('title') or '(제목 없음)'}", ""]
            for field, label in (("comment", None), ("insight", "추후 제작 인사이트")):
                text = plain(block.get(field))
                if text:
                    if label:
                        lines += [f"**{label}**", ""]
                    lines += [text, ""]
    return "\n".join(lines)


def now_text() -> str:
    """사람이 읽는 지금 시각(`2026-09-09 15:00`) — **항상 KST.**

    진입점이 `store`를 직접 import하지 않으므로 여기서 감싼다(2026-09-09에 진입점
    최상위에서 `store`를 부르다 화면을 죽였다 — 같은 실수를 두 번 했다).
    """
    return store.report_timestamp()


def to_zip(data: dict, name: str | None = None) -> bytes:
    """JSON + md를 **한 파일로** 묶는다.

    왜: 예전에는 버튼이 둘이라 규리님이 *"내려받기할 때 뭘 눌러두는 게 좋아?"* 를
    물어야 했다. 백업은 판단이 필요한 일이 아니어야 한다 — 한 번 눌러 둘 다 받는다.

    둘 다 필요한 이유: JSON은 복원되는 유일한 형식이고, md는 **읽을 수 있는** 형태다.
    2026-09-08 사고에서 실제로 필요했던 건 후자였다(읽기가 막혀 콘솔로도 못 꺼냈다).
    """
    tag = name or stamp()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"comments_{tag}.json", to_json(data))
        archive.writestr(f"comments_{tag}.md", to_markdown(data))
    return buffer.getvalue()


def summary(data: dict) -> str:
    """버튼을 누른 사람에게 보여줄 한 줄 — **분량이 보여야** 백업이 됐는지 안다."""
    months = data.get("months", {})
    if not months:
        return "백업할 내용이 없습니다"
    counts: dict[str, int] = {}
    for bucket in months.values():
        for name, rows in bucket.items():
            counts[name] = counts.get(name, 0) + len(rows)
    label = {"blocks": "코멘트", "hlcells": "강조", "overrides": "분류", "picks": "수기지정"}
    parts = [f"{label.get(k, k)} {v}건" for k, v in counts.items()]
    # ⚠ 예전에는 `2개월`이라고만 찍었다 — 규리님이 *"2개월은 무슨 표시야?"* 라고
    #   물었다. 담긴 달 **수**보다 **어느 달인지**가 알고 싶은 것이다.
    span = "·".join(str(int(m)) for m in sorted(months, key=int)) + "월"
    return f"{span} · " + " · ".join(parts)
