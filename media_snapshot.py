"""메타·틱톡 원본(`Media_RAW`)을 월 단위로 고정한다.

## 왜 필요한가 (2026-09-08 규리님 결정)

예전에는 **구글 애셋 보고서만** 고정했다. 드롭박스 폴더가 다음 달 파일로 덮어써지면
과거 달이 아예 사라지기 때문이다. `Media_RAW`는 시트에 누적되니 사라지지 않아서
라이브로 읽어도 된다고 봤는데, **그 전제가 틀렸다.**

*"매달 보여야 하는 데이터의 기준이 달라"* — 사라지지 않는 것과 **바뀌지 않는 것**은
다르다. 시트가 갱신되거나(8월 마감 반영) 정본 시트가 갈리면(실제로 두 개가 됐다)
**이미 광고주에게 보낸 달의 1·2·4·5번 숫자가 함께 움직인다.**

그래서 고정 버튼을 누르면 그 시점의 `Media_RAW` 행까지 함께 얼린다.

## 무엇을 저장하는가

`sheet_loader.load_media_raw`가 돌려준 프레임의 **그 달 행 전부**를, 소재명 파싱까지
끝난 상태로 저장한다. 파싱 전 원본을 저장하고 읽을 때 다시 파싱하면, 나중에 파서를
고칠 때 **이미 고정한 달의 분류가 조용히 달라진다**(USP·태그가 갈라진 전례가 있다).
고정의 뜻은 "그때 화면에 있던 것 그대로"다.

실측 크기(행리스트 JSON): 월 2.7~6.0MB · 청크 10~20개 · 7개월 합계 29.9MB
(Firestore 무료 저장 1GiB). 청크·원자적 커밋 기계는 구글 스냅샷 것을 그대로 쓴다
(`fs_store.write_snapshot(kind="media")`).

## 백엔드

| 백엔드 | 지원 | 이유 |
|---|---|---|
| Firestore | ✅ 정본 | 청크 + 메타 문서 한 번 쓰기로 원자적 교체 |
| 구글시트 | ❌ | 월 34만 셀이라 한 스프레드시트 상한(1,000만 셀)을 몇 달 만에 먹는다 |
| 로컬 파일 | ✅ 폴백 | parquet 하나. 로컬 개발·테스트용 |

시트 백엔드를 쓰는 환경에서는 **로컬 폴백으로 내려간다** — 조용히 안 얼리는 것보다
낫고, 운영은 Firestore를 쓴다(2026-09-01 컷오버 완료).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

import fs_store
import store

_KIND = "media"

SNAPSHOT_DIR = Path(__file__).resolve().parent / "notes" / "media_snapshot"
_STAMP_SUFFIX = ".frozen_at.txt"


def _parquet(month: int) -> Path:
    return SNAPSHOT_DIR / f"{int(month)}.parquet"


def _stamp(month: int) -> Path:
    return SNAPSHOT_DIR / f"{int(month)}{_STAMP_SUFFIX}"


def _settings_path(month: int) -> Path:
    return SNAPSHOT_DIR / f"{int(month)}.settings.json"


def meta(month: int) -> dict | None:
    """이 달 고정 메타(`frozen_at`·`row_count`·`settings`). 안 고정됐으면 None.

    ⚠ **화면은 항목마다 따로 묻지 말고 이걸 한 번 쓴다.** 따로 물으면 Firestore
      읽기가 월당 4회씩 나가서, 12개월을 훑는 것만으로 리런마다 48회가 된다.
    """
    if store.is_firestore():
        return fs_store.snapshot_meta(month, kind=_KIND)
    target = _parquet(month)
    if not target.exists():
        return None
    return {"frozen_at": frozen_at(month), "row_count": row_count(month),
            "settings": frozen_settings(month)}


def exists(month: int) -> bool:
    if store.is_firestore():
        return fs_store.snapshot_exists(month, kind=_KIND)
    return _parquet(month).exists()


def frozen_at(month: int) -> str | None:
    """고정 시각. 아직 안 고정됐으면 None."""
    if store.is_firestore():
        return fs_store.snapshot_frozen_at(month, kind=_KIND)
    stamp = _stamp(month)
    return stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None


def frozen_settings(month: int) -> dict:
    """고정 시점의 설정(시트 링크 등). 예전 스냅샷에는 없어서 빈 dict가 나온다."""
    if store.is_firestore():
        return fs_store.snapshot_settings(month, kind=_KIND)
    path = _settings_path(month)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def row_count(month: int) -> int | None:
    """고정된 행 수. 고정 시각만으로는 "8/23까지"인지 "마감본"인지 알 수 없다."""
    if store.is_firestore():
        return fs_store.snapshot_row_count(month, kind=_KIND)
    target = _parquet(month)
    if not target.exists():
        return None
    try:
        return int(len(pd.read_parquet(target, columns=["month"])))
    except Exception:
        return None


def source_label(month: int) -> str:
    if store.is_firestore():
        return f"Firestore (reports/{int(month)}/mediameta)"
    return str(_parquet(month))


def frozen_months() -> list[int]:
    """고정된 달 목록. 화면이 '어느 달이 얼려졌나'를 묻는 데 쓴다.

    Firestore에는 월 목록을 훑는 값싼 방법이 없어서, 데이터가 있을 수 있는 달만
    확인한다(리포트는 월 단위이고 12개를 넘지 않는다).
    """
    return [month for month in range(1, 13) if exists(month)]


def save(month: int, frame: pd.DataFrame, frozen_at: str | None = None,
         settings: dict | None = None) -> None:
    """이 달의 `Media_RAW` 행을 고정한다. 실패하면 예전 스냅샷이 그대로 남는다.

    `frame`은 **월 필터를 걸기 전 전체 프레임**을 줘도 된다 — 여기서 그 달만 뽑는다.
    """
    month = int(month)
    rows = frame[frame["month"] == month] if "month" in frame.columns else frame
    if rows.empty:
        raise ValueError(f"{month}월 행이 없어 고정할 수 없습니다.")

    if store.is_firestore():
        fs_store.write_snapshot(month, rows, frozen_at=frozen_at,
                                kind=_KIND, settings=settings)
        return

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    # ⚠ 원자적 교체. `to_parquet`이 파일을 먼저 잘라내므로, 쓰는 도중 끊기면 한 달치가
    #    깨진 파일로 남고 로더가 그걸 삼켜 "데이터가 없다"로 보인다.
    target = _parquet(month)
    tmp = target.with_suffix(".parquet.tmp")
    rows.to_parquet(tmp, index=False)
    os.replace(tmp, target)
    _stamp(month).write_text(frozen_at or store.report_timestamp(),
                             encoding="utf-8")
    # 설정도 함께 남긴다 — Firestore만 남기면 로컬에서는 마크업·시트 칸이 빈칸이 돼
    # "고정됐는데 무엇으로 고정했는지 모르는" 상태가 된다.
    if settings:
        _settings_path(month).write_text(
            json.dumps(dict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8")


def load(month: int) -> pd.DataFrame | None:
    """고정된 그 달 행. 없으면 None. **깨졌으면 예외를 던진다.**

    잘린 표를 정상처럼 보여주는 것이 이 프로젝트에서 가장 나쁜 실패다.
    """
    if store.is_firestore():
        return fs_store.read_snapshot(month, kind=_KIND)
    target = _parquet(month)
    return pd.read_parquet(target) if target.exists() else None


def apply(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    """고정된 달의 행을 스냅샷 것으로 갈아끼운다. `(프레임, 갈아끼운 달)`.

    라이브 시트를 나중에 갱신해도 이미 고정한 달의 숫자가 안 움직이게 하는 지점이다.
    **읽기가 실패하면 라이브 행을 그대로 둔다** — 한 달을 못 읽었다고 리포트를
    통째로 막으면 안 되고, 대신 호출부가 그 사실을 화면에 띄운다(아래 `swapped`에
    안 들어가므로 구분된다).
    """
    if raw is None or raw.empty or "month" not in raw.columns:
        return raw, []

    swapped: list[int] = []
    pieces: list[pd.DataFrame] = []
    for month in sorted({int(m) for m in raw["month"].dropna().unique()}):
        live = raw[raw["month"] == month]
        if not exists(month):
            pieces.append(live)
            continue
        frozen = load(month)
        if frozen is None or frozen.empty:
            pieces.append(live)
            continue
        # 컬럼이 늘어난 뒤에 고정한 달을 읽으면 없는 컬럼이 생긴다 — 라이브 쪽 컬럼
        # 구성에 맞춰 채워 넣어야 아래에서 concat이 어긋나지 않는다.
        for column in live.columns:
            if column not in frozen.columns:
                frozen[column] = pd.NA
        pieces.append(frozen[list(live.columns)])
        swapped.append(month)

    if not swapped:
        return raw, []
    merged = pd.concat(pieces, ignore_index=True)
    # 라이브에는 있었지만 스냅샷에는 없던 달의 dtype이 object로 흐트러질 수 있다.
    for column in raw.columns:
        if pd.api.types.is_numeric_dtype(raw[column]):
            merged[column] = pd.to_numeric(merged[column], errors="coerce")
    return merged, swapped
