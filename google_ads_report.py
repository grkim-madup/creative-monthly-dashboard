"""구글 광고 '애셋 세부정보 보고서' 폴더 로더.

구글 소재 성과는 `Media_RAW`에 없다. 담당자가 구글 광고에서 캠페인별로 '애셋 세부정보 보고서'를
내려받아 드롭박스 폴더에 모아두고, 그 값을 리포트 시트에 붙여넣어 왔다. 이 모듈은 붙여넣기 결과가
아니라 **그 원본 CSV 폴더를 직접 읽는다.**

파일 규칙(2026-08 확인):
- 전부 UTF-16 · 탭 구분 · 1행 보고서명 / 2행 기간 / **3행 헤더**.
- 폴더명이 OS와 캠페인 목적을 담는다 — `AOS ACa`, `AOS ACi`, `iOS ACa coin 캠페인`, `iOS ACi 캠페인`.
  (ACi = 설치 목적, ACa = 액션(코인/열람) 목적)
- 파일명이 캠페인 구분과 작품명을 담는다 — `AOS ACa Read 여성향 캠페인_녹음의 관.csv`.
- **AOS와 iOS의 컬럼 구성이 다르다**: AOS에는 `방향`이 있고, iOS에는 대신 `애셋 이름`(파일명에
  `1200x1500` 같은 규격이 들어있음)이 있으며 CTR·평균 CPC 컬럼이 없다. 비율은 어차피 합계에서
  다시 계산하므로 문제되지 않는다.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pandas as pd

from creative_data import add_derived_metrics, size_orientation, to_number

HEADER_ROW_INDEX = 2
ENCODINGS = ("utf-16", "utf-8-sig", "cp949")

# 보고서의 `비용`은 구글 원가다. 리포트 시트의 `cost (마크업 포함)`은 여기에 마크업을 얹은 값이며,
# 2026-07 실측으로 배율이 정확히 1.0830임을 확인했다(여러 소재에서 소수점까지 일치).
DEFAULT_COST_MARKUP = 1.0830

COLUMN_ALIASES = {
    "asset": ["확장 소재"],
    "asset_type": ["애셋 유형"],
    "asset_name": ["애셋 이름"],
    "rating": ["실적"],
    "direction": ["방향"],
    "impression": ["노출수"],
    "click": ["클릭수"],
    "cost": ["비용"],
    "total install": ["설치"],
    "in_app_action": ["인앱 액션"],
    "status": ["상태"],
}

# 구글 표기 → 대시보드 표기
DIRECTION_ALIASES = {
    "가로 모드": "가로",
    "가로": "가로",
    "세로": "세로",
    "정사각형": "정방형",
}

CREATIVE_ASSET_TYPES = ("YouTube 동영상", "이미지")

_PERIOD_PATTERN = re.compile(r"(\d{4})년\s*(\d{1,2})월")
_SIZE_IN_NAME = re.compile(r"(\d{2,4})[xX](\d{2,4})")


def _decode(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _find(columns, target: str):
    normalized = {re.sub(r"\s+", "", c): c for c in columns}
    return normalized.get(re.sub(r"\s+", "", target))


def parse_period_month(text: str) -> int | None:
    """'2026년 7월 1일 - 2026년 7월 31일' → 7"""
    match = _PERIOD_PATTERN.search(text or "")
    return int(match.group(2)) if match else None


def parse_meta_from_path(path: Path) -> dict:
    """폴더/파일 이름에서 OS·캠페인 목적·작품명을 뽑는다."""
    folder = path.parent.name
    stem = path.stem

    os_name = "iOS" if "ios" in folder.lower() else "AOS" if "aos" in folder.lower() else None
    upper = f"{folder} {stem}".upper()
    if "ACA" in upper:
        objective = "ACa (액션)"
    elif "ACI" in upper:
        objective = "ACi (설치)"
    else:
        objective = None

    title = stem.split("_", 1)[1].strip() if "_" in stem else None
    campaign = stem.split("_", 1)[0].strip()

    segment = None
    for keyword in ("남성향", "여성향", "Coin", "coin", "install", "Read"):
        if keyword in stem:
            segment = {"Coin": "코인", "coin": "코인", "install": "설치", "Read": "열람"}.get(
                keyword, keyword
            )
            break

    return {
        "os": os_name,
        "objective": objective,
        "campaign": campaign,
        "title_kr": title,
        "segment": segment,
    }


def read_asset_report(path: Path) -> pd.DataFrame:
    """애셋 세부정보 보고서 CSV 하나를 표준 스키마로 읽는다."""
    text = _decode(Path(path))
    lines = text.splitlines()
    if len(lines) <= HEADER_ROW_INDEX:
        return pd.DataFrame()

    month = parse_period_month(lines[1] if len(lines) > 1 else "")
    reader = csv.reader(lines[HEADER_ROW_INDEX:], delimiter="\t")
    rows = list(reader)
    if not rows:
        return pd.DataFrame()

    header = rows[0]
    body = [r + [""] * (len(header) - len(r)) for r in rows[1:] if any(c.strip() for c in r)]
    if not body:
        return pd.DataFrame()

    raw = pd.DataFrame([r[:len(header)] for r in body], columns=header)

    out = pd.DataFrame(index=raw.index)
    for target, aliases in COLUMN_ALIASES.items():
        column = next((_find(raw.columns, a) for a in aliases if _find(raw.columns, a)), None)
        if column is None:
            out[target] = pd.NA
            continue
        if target in ("impression", "click", "cost", "total install", "in_app_action"):
            out[target] = raw[column].map(to_number)
        else:
            out[target] = raw[column].astype(str).str.strip()

    meta = parse_meta_from_path(Path(path))
    for key, value in meta.items():
        out[key] = value
    out["month"] = month
    out["media"] = "Google"
    out["source_file"] = Path(path).name

    # AOS는 '방향' 컬럼, iOS는 '애셋 이름'의 규격(1200x1500)에서 방향을 유도한다.
    direction = out["direction"].map(
        lambda v: DIRECTION_ALIASES.get(str(v).strip()) if pd.notna(v) else None
    )
    out["direction"] = direction.fillna(out["asset_name"].map(_orientation_from_name))
    out["direction"] = out["direction"].astype("object").where(out["direction"].notna(), None)

    out = out[out["asset"].astype(str).str.strip().astype(bool)]
    return out.reset_index(drop=True)


def _orientation_from_name(name) -> str | None:
    if name is None or pd.isna(name):
        return None
    match = _SIZE_IN_NAME.search(str(name))
    if not match:
        return None
    return size_orientation(f"{match.group(1)}X{match.group(2)}")


def load_google_ads_folder(
    folder: str | Path, cost_markup: float = DEFAULT_COST_MARKUP
) -> pd.DataFrame:
    """폴더(하위 폴더 포함)의 모든 애셋 보고서를 읽어 하나로 합친다.

    `cost_markup`을 곱해 리포트 시트의 `cost (마크업 포함)` 기준과 맞춘다.
    """
    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {root}")

    frames = []
    failures = []
    for path in sorted(root.rglob("*.csv")):
        try:
            frame = read_asset_report(path)
        except Exception as error:  # 한 파일이 깨져도 나머지는 읽되, 무엇이 빠졌는지는 남긴다
            failures.append(f"{path.name}: {error}")
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        combined = pd.DataFrame()
    else:
        combined = pd.concat(frames, ignore_index=True)
        combined["cost_raw"] = combined["cost"]
        combined["cost"] = combined["cost"] * cost_markup
    combined.attrs["failures"] = failures
    return combined


def creative_assets(df: pd.DataFrame) -> pd.DataFrame:
    """영상·이미지 애셋만 남긴다(설명·제목·앱 딥 링크 등 텍스트 애셋 제외)."""
    if df.empty:
        return df
    return df[df["asset_type"].isin(CREATIVE_ASSET_TYPES)].reset_index(drop=True)


def aggregate_google(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """키 기준 합산 후 비율 재계산. 다른 섹션과 동일하게 비율은 절대 평균내지 않는다."""
    if df.empty:
        return df
    metrics = ["impression", "click", "cost", "total install", "in_app_action"]
    present = [m for m in metrics if m in df.columns]
    grouped = (
        df.groupby(keys, dropna=False)[present]
        .sum(min_count=1)
        .reset_index()
        .sort_values("cost", ascending=False)
    )
    for column in ("D0 read", "D0 coin", "D7 coin"):
        grouped[column] = pd.NA
    grouped = add_derived_metrics(grouped)
    if "in_app_action" in grouped.columns:
        grouped["인앱 CPA"] = grouped["cost"] / grouped["in_app_action"].replace(0, pd.NA)
    return grouped.reset_index(drop=True)
