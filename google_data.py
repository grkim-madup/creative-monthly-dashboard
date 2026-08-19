"""구글(App Campaign) 소재 성과 데이터 계층.

구글은 다른 매체와 데이터 경로가 완전히 다르다:

- `Media_RAW`에 **구글 행이 아예 없다.** 구글 소재 성과는 구글 광고 대시보드에서 내보낸 값을
  담당자가 매달 리포트 탭에 직접 붙여넣는다(시트에 수식 없이 하드코딩되어 있음).
- 소재 식별자가 소재명이 아니라 **유튜브 URL**이다. 따라서 작품/포맷/사이즈를 소재명에서
  분해할 수 없고, 메타·틱톡 소재와 같은 표에 섞어 순위를 매길 수도 없다.
- 성과 기준도 다르다 — 메타/틱톡은 앱스플라이어 코호트 기준, 구글은 매체 대시보드 기준이다.

그래서 구글은 별도 섹션으로만 다룬다. 이 모듈은 리포트 탭에 붙어있는 구글 블록을 위치가
매달 바뀌어도 찾아낼 수 있도록 **유튜브 URL이 들어있는 행을 기준으로 자동 탐지**한다.
"""

from __future__ import annotations

import re

import pandas as pd

from creative_data import _find_column, add_derived_metrics, to_number

URL_PATTERN = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/", re.IGNORECASE)

# 구글 내보내기 헤더 → 대시보드 표준 컬럼. 시트마다 표기가 조금씩 달라 퍼지 매칭한다.
GOOGLE_COLUMN_ALIASES = {
    "cost": ["cost (마크업 포함)", "cost(마크업 포함)", "cost", "비용"],
    "impression": ["impression", "노출수", "노출"],
    "click": ["click", "클릭수", "클릭"],
    "total install": ["매체 Install", "total install", "install", "설치"],
    "in_app_action": ["매체 인앱 액션", "인앱 액션", "인앱액션"],
    "install_cvr": ["전환율(설치)", "install CVR", "전환율"],
    "rating": ["실적", "성과", "평가"],
}

MIN_HEADER_HITS = 2
HEADER_SEARCH_DEPTH = 6
OS_SEARCH_DEPTH = 10

_OS_PATTERN = re.compile(r"\b(AOS|iOS)\b", re.IGNORECASE)


def detect_block_os(grid: list[list[str]], block_start: int) -> str | None:
    """블록 위쪽 소제목에서 OS를 읽는다(예: '■ 틱톡/메타 AOS - …', '* 구글 AOS').

    같은 URL이 'install TOP10'과 'coin TOP10'에 중복 등장할 수 있어, 합산 전에 OS를 알아야
    OS 안에서는 중복을 제거하고 OS 사이에서만 더할 수 있다.
    """
    for back in range(1, OS_SEARCH_DEPTH + 1):
        index = block_start - back
        if index < 0:
            break
        match = _OS_PATTERN.search(" ".join(str(c) for c in grid[index]))
        if match:
            return "iOS" if match.group(1).lower() == "ios" else "AOS"
    return None


def _is_url_row(row: list[str]) -> bool:
    return any(URL_PATTERN.search(str(cell)) for cell in row)


def _url_column(row: list[str]) -> int | None:
    for index, cell in enumerate(row):
        if URL_PATTERN.search(str(cell)):
            return index
    return None


def _looks_like_header(row: list[str]) -> bool:
    text = " ".join(str(c) for c in row).lower()
    hits = sum(
        1 for key in ("impression", "click", "cost", "install", "노출", "클릭", "비용")
        if key in text
    )
    return hits >= MIN_HEADER_HITS


def find_google_blocks(values: list[list[str]]) -> list[pd.DataFrame]:
    """시트 2차원 값에서 유튜브 URL 행 묶음을 찾아 각각 DataFrame으로 돌려준다.

    블록 위치가 매달 바뀌어도 URL을 기준으로 찾으므로 셀 주소를 하드코딩하지 않는다.
    """
    if not values:
        return []

    width = max(len(row) for row in values)
    grid = [list(row) + [""] * (width - len(row)) for row in values]

    blocks: list[pd.DataFrame] = []
    index = 0
    while index < len(grid):
        if not _is_url_row(grid[index]):
            index += 1
            continue

        start = index
        while index < len(grid) and _is_url_row(grid[index]):
            index += 1
        body = grid[start:index]

        header = None
        for back in range(1, HEADER_SEARCH_DEPTH + 1):
            candidate = start - back
            if candidate < 0:
                break
            if _looks_like_header(grid[candidate]):
                header = grid[candidate]
                break
        if header is None:
            continue

        url_col = _url_column(body[0])
        left = url_col if url_col is not None else 0
        right = max(
            (i for i, cell in enumerate(header) if str(cell).strip()),
            default=left,
        )
        if right <= left:
            continue

        columns = [str(c).strip() for c in header[left:right + 1]]
        rows = [row[left:right + 1] for row in body]
        frame = pd.DataFrame(rows, columns=columns)
        frame = frame.loc[:, [bool(c) for c in frame.columns]]
        if not frame.empty:
            frame.attrs["os"] = detect_block_os(grid, start)
            blocks.append(frame)

    return blocks


def normalize_google_block(frame: pd.DataFrame) -> pd.DataFrame:
    """구글 블록을 대시보드 표준 스키마로 정규화하고 파생 지표를 다시 계산한다."""
    if frame.empty:
        return frame

    out = pd.DataFrame()

    url_column = next(
        (c for c in frame.columns if frame[c].astype(str).str.contains(URL_PATTERN).any()),
        frame.columns[0],
    )
    out["ad"] = frame[url_column].astype(str).str.strip()

    for target, aliases in GOOGLE_COLUMN_ALIASES.items():
        column = None
        for alias in aliases:
            column = _find_column(frame.columns, alias)
            if column is not None:
                break
        if column is None:
            continue
        if target == "rating":
            out[target] = frame[column].astype(str).str.strip()
        else:
            out[target] = frame[column].map(to_number)

    out = out[out["ad"].str.contains(URL_PATTERN, na=False)]
    if out.empty:
        return out

    out["media"] = "Google"
    out["os"] = frame.attrs.get("os")
    for required in ("impression", "click", "cost", "total install"):
        if required not in out.columns:
            out[required] = pd.NA

    # 파생 지표는 붙여온 값을 믿지 않고 항상 합계에서 다시 계산한다(다른 섹션과 같은 규칙).
    out = add_derived_metrics(
        out.assign(**{
            column: out[column] if column in out.columns else pd.NA
            for column in ("D0 read", "D0 coin", "D7 coin")
        })
    )
    if "in_app_action" in out.columns:
        out["인앱 CPA"] = out["cost"] / out["in_app_action"].replace(0, pd.NA)
    return out.sort_values("cost", ascending=False).reset_index(drop=True)


def load_google_creatives(values: list[list[str]]) -> pd.DataFrame:
    """리포트 탭의 구글 블록들을 하나의 소재 성과 표로 합친다.

    같은 URL이 한 OS 안에서 여러 블록(install TOP10 / coin TOP10 등)에 중복 등장할 수 있으므로
    **OS 안에서는 중복을 제거하고(가장 큰 소진 행을 채택), OS 사이에서만 합산한다.**
    그냥 전부 더하면 고객사에 나가는 숫자가 부풀려진다.
    """
    blocks = [normalize_google_block(b) for b in find_google_blocks(values)]
    blocks = [b for b in blocks if not b.empty]
    if not blocks:
        return pd.DataFrame()

    merged = pd.concat(blocks, ignore_index=True)
    metrics = [
        c for c in ("impression", "click", "cost", "total install", "in_app_action")
        if c in merged.columns
    ]

    merged["os"] = merged["os"].fillna("미상")
    deduped = (
        merged.sort_values("cost", ascending=False)
        .drop_duplicates(subset=["ad", "os"], keep="first")
    )
    grouped = deduped.groupby("ad", as_index=False)[metrics].sum(min_count=1)
    grouped["media"] = "Google"

    ratings = (
        merged.dropna(subset=["rating"]).drop_duplicates("ad").set_index("ad")["rating"]
        if "rating" in merged.columns
        else None
    )
    if ratings is not None:
        grouped["rating"] = grouped["ad"].map(ratings)

    for column in ("D0 read", "D0 coin", "D7 coin"):
        grouped[column] = pd.NA
    grouped = add_derived_metrics(grouped)
    if "in_app_action" in grouped.columns:
        grouped["인앱 CPA"] = grouped["cost"] / grouped["in_app_action"].replace(0, pd.NA)
    return grouped.sort_values("cost", ascending=False).reset_index(drop=True)


def youtube_id(url: str) -> str | None:
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", str(url))
    return match.group(1) if match else None
