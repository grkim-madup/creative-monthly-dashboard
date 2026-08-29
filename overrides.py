"""소재명 규칙 파싱이 실패한 소재의 분류를 수동으로 고쳐 쓴다.

구글의 '-' 자리표시자(소재 단위 태깅이 아예 없음)와는 다른 문제다 — 이건 실제로 집행된
메타·틱톡 소재인데 이름이 명명 규칙(작품코드_작품명_Format_제작주체_Type_Dimension_USP_
Extra Info)과 안 맞아 Creative Type 등이 비어 '미분류'로 빠진 경우다. 성과 수치(소진액·
설치 등)는 원본 그대로 두고, 분류 컬럼만 사용자가 지정한 값으로 덮어쓴다.

저장 위치: `google_sheets_writer`가 설정돼 있으면 전용 구글시트 `overrides_<월>` 탭에
**소재 하나당 한 행**. 아니면(로컬 개발 PC 등) `notes/overrides_<월>.json`.

시트로 옮긴 이유가 두 가지다.
1. 배포판(Streamlit Community Cloud)은 재배포·리부트마다 로컬 디스크가 초기화된다.
   블록·이미지는 이미 시트로 옮겼는데 이 수동 분류만 로컬에 남아 있어서, 재배포 때마다
   조용히 전멸했다(에러가 안 나서 더 늦게 발견된다).
2. 파일 하나를 통째로 다시 쓰는 방식이라, 두 사람이 **서로 다른 소재**를 분류해도 늦게
   저장한 쪽이 먼저 저장된 분류를 지웠다. 이제 소재 행 하나만 갱신한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import google_sheets_writer

OVERRIDES_DIR = Path(__file__).resolve().parent / "notes"

# 덮어쓸 수 있는 컬럼과 화면에 보여줄 라벨. size/orientation은 실제 픽셀 크기에서
# 자동 계산되는 값이라 수동 입력 대상에서 뺐다.
FIELDS = {
    "creative_type": "Creative Type",
    "format": "Creative Format",
    "producer_group": "제작 주체",
    "extra_info": "Extra Info",
    "usp": "USP",
}


def _path(month: int) -> Path:
    return OVERRIDES_DIR / f"overrides_{int(month)}.json"


def _clean(fields) -> dict[str, str]:
    if not isinstance(fields, dict):
        return {}
    return {k: str(v) for k, v in fields.items() if k in FIELDS and v}


def _normalize(data) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict):
        return {}
    return {str(ad): _clean(fields) for ad, fields in data.items() if _clean(fields)}


def _read_local(month: int) -> dict[str, dict[str, str]]:
    path = _path(month)
    if not path.exists():
        return {}
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_local(month: int, data: dict) -> None:
    OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(month)
    # write_text는 파일을 먼저 잘라내므로 쓰는 도중 끊기면 한 달치 분류가 깨진 JSON으로
    # 남고, 로더가 그걸 삼켜 전부 사라진 것처럼 보인다. 원자적 교체를 쓴다.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load(month: int) -> dict[str, dict[str, str]]:
    """소재명 → {컬럼: 값} 매핑을 돌려준다. 없거나 읽기가 실패하면 빈 dict."""
    if not google_sheets_writer.configured():
        return _read_local(month)

    status, data, _reason = google_sheets_writer.read_overrides(month)
    if status == "ok":
        return _normalize(data)
    if status == "error":
        # 읽기 실패에 빈 값을 저장하면 그 순간 한 달치가 사라진다 — 아무것도 쓰지 않는다.
        return {}
    # 시트 탭이 아직 없다 — 이 PC에 시트 백엔드를 켜기 전에 쓰던 로컬 분류가 있으면
    # 한 번 옮긴다. 안 그러면 시트가 비어 있다는 이유만으로 이미 해 둔 분류가 사라진다.
    local = _read_local(month)
    for ad, fields in local.items():
        google_sheets_writer.write_override(month, ad, fields)
    # 이관 표식을 남긴다 — 안 그러면 사용자가 전부 지운 분류가 로컬 파일에서 되살아난다.
    google_sheets_writer.mark_migrated(
        f"overrides_{int(month)}", google_sheets_writer.OVERRIDE_HEADER
    )
    return local


def save(month: int, ad: str, fields: dict[str, str]) -> None:
    """이 소재의 수동 분류를 저장한다. 값이 있는 필드만 남긴다."""
    cleaned = {k: v.strip() for k, v in fields.items() if k in FIELDS and v and v.strip()}
    if google_sheets_writer.configured():
        if cleaned:
            google_sheets_writer.write_override(month, ad, cleaned)
        else:
            google_sheets_writer.delete_override(month, ad)
        return

    data = _read_local(month)
    if cleaned:
        data[ad] = cleaned
    else:
        data.pop(ad, None)
    _write_local(month, data)


def remove(month: int, ad: str) -> None:
    if google_sheets_writer.configured():
        google_sheets_writer.delete_override(month, ad)
        return
    data = _read_local(month)
    if data.pop(ad, None) is not None:
        _write_local(month, data)


def apply(df, month: int):
    """overview 프레임에 이 달의 수동 분류를 patch해서 돌려준다(원본은 건드리지 않음).

    extra_info를 고치면 그 값으로 만들어지는 extra_info_label도 같이 새로 계산해야
    화면에 일관되게 반영된다.
    """
    manual = load(month)
    if not manual or df.empty:
        return df

    out = df.copy()
    for ad, fields in manual.items():
        mask = out["ad"] == ad
        if not mask.any():
            continue
        for column, value in fields.items():
            if column in out.columns:
                out.loc[mask, column] = value

    if "extra_info" in out.columns:
        out["extra_info_label"] = out["extra_info"].fillna("없음").replace("", "없음")

    return out
