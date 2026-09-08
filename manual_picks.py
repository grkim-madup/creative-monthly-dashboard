"""우수·저조 소재를 사람이 직접 지정한다.

규리님·팀원 피드백(2026-09-08): 자동 선정이 *"소진 비용은 신경 안 쓰고 오케이 CPI
좋다 얘 best야"* 하는 식이라, 팀원이 직접 뽑은 픽과 어긋난다. 선정 규칙을 고치는
작업은 별개로 진행하고, **그 사이에도 리포트가 사람 판단대로 나가야** 하므로
수기 지정을 먼저 둔다.

## 키가 왜 (월, os, 정렬기준, 소재명)인가

2번 섹션은 같은 달에 표를 **네 개** 그린다(AOS/iOS × 정렬기준). 팀원 픽을 보면
같은 소재가 한 표에서는 BEST인데 다른 표에서는 무표시다 — 예를 들어
`9981_..._KRLabB-social-2`는 `AOS·D0 Coin` 표에서 BEST이지만 `iOS·인스톨` 표에서는
지정이 없다. 그래서 소재명 하나에 판정 하나를 붙이는 구조로는 담을 수 없다.

## 저장 위치

`overrides.py`와 같은 규칙을 따른다 — Firestore가 켜져 있으면 Firestore,
아니면 전용 구글시트, 둘 다 없으면 `notes/picks_<월>.json`. 백엔드 함수를 새로
만들지 않고 **분류 저장소(`overrides`)의 제네릭 JSON 행 저장을 그대로 쓴다**:
행 키가 `os|정렬기준|소재명`이고 값이 `{"pick": "best"|"worst"}`다.

⚠ 읽기 실패와 "지정 없음"을 절대 같은 값으로 뭉개지 않는다. 실패했을 때 빈 값으로
덮어쓰면 그 순간 한 달치 지정이 사라진다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import fs_store
import google_sheets_writer
import store

PICKS_DIR = Path(__file__).resolve().parent / "notes"

#: 지정할 수 있는 판정. 그 외 값은 저장하지 않는다.
BEST = "best"
WORST = "worst"
VERDICTS = (BEST, WORST)

#: 행 키를 만들 때 쓰는 구분자. 소재명에 `_`가 흔하고 `|`는 안 쓰인다.
_SEP = "|"


def _tab(month: int) -> str:
    return f"picks_{int(month)}"


def _path(month: int) -> Path:
    return PICKS_DIR / f"picks_{int(month)}.json"


def row_key(os_name: str, rank_metric: str, ad: str) -> str:
    """표 하나 안의 소재 하나를 가리키는 키."""
    return _SEP.join([str(os_name), str(rank_metric), str(ad)])


def split_key(key: str) -> tuple[str, str, str] | None:
    parts = str(key).split(_SEP, 2)
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


def _normalize(data) -> dict[str, str]:
    """{행 키: 판정} 으로 맞춘다. 모르는 판정은 버린다."""
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        verdict = value.get("pick") if isinstance(value, dict) else value
        verdict = str(verdict or "").strip().lower()
        if verdict in VERDICTS and split_key(key):
            out[str(key)] = verdict
    return out


def _read_local(month: int) -> dict[str, str]:
    path = _path(month)
    if not path.exists():
        return {}
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_local(month: int, data: dict[str, str]) -> None:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(month)
    # `write_text`는 파일을 먼저 잘라내므로 쓰는 도중 끊기면 한 달치가 깨진 JSON으로
    # 남고, 로더가 그걸 삼켜 전부 사라진 것처럼 보인다. 원자적 교체를 쓴다.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({k: {"pick": v} for k, v in data.items()},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


#: 지정 목록 캐시. 한 화면에 표가 6개(메타·틱톡 4 + 구글 2)이고 표마다 `for_table`이
#: 불리므로, 캐시가 없으면 **같은 문서를 표마다 다시 읽는다**(8월 실측 22건 × 6 = 132회).
#: 강조(`highlights`)와 같은 방식이다. 쓰기가 있는 값이라 TTL을 짧게 둔다 —
#: 남이 방금 넣은 지정이 최대 이 시간만큼 늦게 보인다(`b92de54`의 교훈).
_CACHE_TTL = 20.0
_CACHE: dict[int, tuple[float, dict[str, str]]] = {}


def _cached(month: int) -> dict[str, str] | None:
    hit = _CACHE.get(int(month))
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
        return hit[1]
    return None


def invalidate(month: int) -> None:
    """저장 직후 캐시를 버린다 — 내가 넣은 지정이 바로 보여야 한다."""
    _CACHE.pop(int(month), None)


def load(month: int, use_cache: bool = True) -> dict[str, str]:
    """{행 키: 판정}. 없거나 읽기가 실패하면 빈 dict.

    ⚠ Firestore 분기가 **먼저** 와야 한다. `configured()`(시트 자격증명)를 먼저 보면,
      시트가 설정 안 된 환경에서 Firestore로 저장했을 때 **저장은 되는데 화면에는
      로컬 파일이 보인다** — `overrides`에서 계약 테스트가 잡아낸 실수다.
    """
    if use_cache:
        hit = _cached(month)
        if hit is not None:
            return hit

    if store.is_firestore():
        status, data, _reason = fs_store.read_picks(month)
        found = _normalize(data) if status != "error" else {}
        # ⚠ 읽기 실패는 캐시하지 않는다 — 실패를 "지정 없음"으로 굳히면 그 20초 동안
        #   자동 선정이 사람 판단을 덮는다.
        if status != "error":
            _CACHE[int(month)] = (time.monotonic(), found)
        return found

    if not google_sheets_writer.configured():
        return _read_local(month)
    status, data, _reason = google_sheets_writer.read_picks(month)
    if status == "ok":
        return _normalize(data)
    if status == "error":
        # 읽기 실패에 빈 값을 저장하면 그 순간 한 달치가 사라진다 — 아무것도 쓰지 않는다.
        return {}
    # 탭이 아직 없다 — 이 PC에 남아 있던 로컬 지정을 한 번 옮긴다.
    local = _read_local(month)
    for key, verdict in local.items():
        google_sheets_writer.write_pick(month, key, verdict)
    if local:
        google_sheets_writer.mark_migrated(_tab(month),
                                           google_sheets_writer.PICK_HEADER)
    return local


def save(month: int, os_name: str, rank_metric: str, ad: str,
         verdict: str | None) -> tuple[bool, str | None]:
    """이 표의 이 소재를 우수/저조로 지정한다. `verdict=None`이면 지정을 지운다.

    **(성공 여부, 실패 사유)를 돌려준다** — 저장 결과를 버리면 접속이 몰려 실패해도
    화면은 저장된 것처럼 보인다(`overrides`에서 실제로 그렇게 유실됐다).
    """
    key = row_key(os_name, rank_metric, ad)
    verdict = str(verdict or "").strip().lower() or None
    if verdict is not None and verdict not in VERDICTS:
        return False, f"알 수 없는 판정: {verdict}"

    invalidate(month)
    if store.is_firestore():
        if verdict:
            return fs_store.write_pick(month, key, verdict)
        return fs_store.delete_pick(month, key)
    if google_sheets_writer.configured():
        if verdict:
            return google_sheets_writer.write_pick(month, key, verdict)
        return google_sheets_writer.delete_pick(month, key)

    data = _read_local(month)
    if verdict:
        data[key] = verdict
    else:
        data.pop(key, None)
    _write_local(month, data)
    return True, None


def for_table(month: int, os_name: str, rank_metric: str) -> dict[str, str]:
    """표 하나에 걸린 지정만 {소재명: 판정}으로 추린다."""
    picked: dict[str, str] = {}
    for key, verdict in load(month).items():
        parts = split_key(key)
        if parts and parts[0] == str(os_name) and parts[1] == str(rank_metric):
            picked[parts[2]] = verdict
    return picked


#: 구글 표의 OS 키 접두사. 구글은 소재 식별자가 URL이라 메타·틱톡과 **키 공간을
#: 나눠야 한다** — 같은 달·같은 정렬 기준에서 이름이 겹칠 일은 없지만, 섞어 두면
#: `for_table`이 엉뚱한 표의 지정을 끌어온다.
GOOGLE_PREFIX = "google:"


def google_os(os_name: str) -> str:
    """구글 표의 OS 키(`google:iOS`). 키는 여전히 세 조각이라 `split_key`가 그대로 산다."""
    return f"{GOOGLE_PREFIX}{os_name}"


def apply(table, month: int, os_name: str, rank_metric: str,
          best: dict, worst: dict, id_column: str = "ad") -> tuple[dict, dict]:
    """자동 선정 결과에 수기 지정을 덮어쓴다. `(best, worst)`를 새로 돌려준다.

    **지정이 하나라도 있으면 그 표의 자동 선정은 통째로 버린다.** 섞으면 화면에
    5~6줄이 칠해져서 "무엇이 사람 판단인지" 알 수 없다 — 사람이 손을 댄 표는
    사람 판단만 보여주는 게 정직하다.

    표에 없는 소재를 지정해 둔 경우(정렬 기준을 바꿔 그 소재가 TOP N에서 빠졌을 때)는
    조용히 무시된다 — 그 줄이 화면에 없으므로 칠할 자리도 없다.

    구글 표는 `id_column="asset"`(URL)과 `os_name=google_os("iOS")`로 부른다.

    ⚠ **값은 반드시 표에 실제로 있는 컬럼 이름이어야 한다.** 소비하는 쪽이 이 값을
      `df.loc[index, 값]`으로 쓴다 — 예전에 `"수기 지정"`이라는 문구를 넣었더니
      썸네일 카드가 KeyError로 죽어 **배포판 3번 섹션이 통째로 안 떴다**(2026-09-08).
      `label_column`으로 그 표의 정렬 기준 컬럼을 받아 쓴다.
    """
    manual = for_table(month, os_name, rank_metric)
    if not manual or table is None or getattr(table, "empty", True):
        return best, worst
    # `id_column`은 표마다 다르다 — 메타·틱톡은 소재명(`ad`), 구글은 애셋 URL(`asset`).
    if id_column not in table.columns:
        return best, worst

    column = label_column(table, rank_metric)
    new_best: dict = {}
    new_worst: dict = {}
    for index, ad in table[id_column].items():
        verdict = manual.get(str(ad))
        if verdict == BEST:
            new_best[index] = column
        elif verdict == WORST:
            new_worst[index] = column
    return new_best, new_worst


#: 수기 지정 행에 붙일 지표. 정렬 기준이 그 표에 있으면 그것을 쓴다 — 표를 그 기준으로
#: 줄 세웠으니 카드에도 같은 숫자가 보이는 게 자연스럽다.
_LABEL_FALLBACKS = ("CPI", "cost", "total install")


def label_column(table, rank_metric: str | None) -> str:
    """수기 지정 행이 카드에 보여줄 지표 컬럼. **표에 있는 것만 돌려준다.**"""
    columns = list(getattr(table, "columns", []))
    for candidate in (rank_metric, *_LABEL_FALLBACKS):
        if candidate and candidate in columns:
            return str(candidate)
    return str(columns[0]) if columns else ""
