"""소재명 규칙 파싱이 실패한 소재의 분류를 수동으로 고쳐 쓴다.

구글의 '-' 자리표시자(소재 단위 태깅이 아예 없음)와는 다른 문제다 — 이건 실제로 집행된
메타·틱톡 소재인데 이름이 명명 규칙(작품코드_작품명_Format_제작주체_Type_Dimension_USP_
Extra Info)과 안 맞아 Creative Type 등이 비어 '미분류'로 빠진 경우다. 성과 수치(소진액·
설치 등)는 원본 그대로 두고, 분류 컬럼만 사용자가 지정한 값으로 덮어쓴다.

저장 위치: `notes/overrides_<월>.json` — {소재명: {컬럼: 값}}
"""

from __future__ import annotations

import json
from pathlib import Path

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


def load(month: int) -> dict[str, dict[str, str]]:
    """소재명 → {컬럼: 값} 매핑을 돌려준다. 없거나 파일이 깨졌으면 빈 dict."""
    path = _path(month)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(ad): {k: str(v) for k, v in fields.items() if k in FIELDS and v}
        for ad, fields in data.items()
        if isinstance(fields, dict)
    }


def save(month: int, ad: str, fields: dict[str, str]) -> None:
    """이 소재의 수동 분류를 저장한다. 값이 있는 필드만 남긴다."""
    data = load(month)
    cleaned = {k: v.strip() for k, v in fields.items() if k in FIELDS and v and v.strip()}
    if cleaned:
        data[ad] = cleaned
    else:
        data.pop(ad, None)

    OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    _path(month).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remove(month: int, ad: str) -> None:
    data = load(month)
    if data.pop(ad, None) is not None:
        OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
        _path(month).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
