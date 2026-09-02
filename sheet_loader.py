"""구글시트 Media_RAW 로딩 + 디스크 캐시.

Media_RAW는 12만 행 규모라 매 실행마다 API로 받으면 느리다. 시트ID별로 parquet에 캐싱하고
사이드바의 "새로고침"으로만 다시 받는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from creative_data import RAW_SHEET_NAME, attach_creative_attributes, parse_raw_values
from google_data import load_google_creatives
from google_sheets_readonly import (
    fetch_sheet_values,
    fetch_sheet_values_parallel,
    get_credentials,
)
from googleapiclient.discovery import build
from ios_cohort import IOS_COHORT_SHEET_NAME, apply_ios_cohort, parse_ios_cohort

CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def extract_sheet_id(url_or_id: str) -> str:
    text = (url_or_id or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", text):
        return text
    raise ValueError("구글시트 URL 또는 시트 ID를 인식하지 못했습니다.")


#: 소재명 파서를 고칠 때마다 올린다. 캐시 파일 이름에 들어가므로 **옛 파싱 결과가 그대로
#: 재사용되는 일을 원천 차단한다.** 예전에는 시트 id만으로 캐시를 잡아서, 파서를 고쳐도
#: 캐시가 남아 있으면 화면이 조용히 옛 분류를 보여줬다(2026-09-02, USP·Extra Info 하이픈
#: 수정 때 실제로 겪었다 — 이 프로젝트에서 가장 위험한 실패 유형인 "에러 없이 틀림"이다).
#: v2: USP 뒤 `-`로 붙은 Extra Info를 분리 (`TITLE2-comic` → USP `TITLE2` + `comic`)
PARSER_VERSION = "v3"


def _cache_path(sheet_id: str) -> Path:
    return CACHE_DIR / f"{sheet_id}.{PARSER_VERSION}.parquet"


def load_media_raw(sheet_id: str, refresh: bool = False) -> pd.DataFrame:
    """Media_RAW를 소재 속성까지 붙인 DataFrame으로 반환. 캐시가 있으면 재사용.

    iOS 전환 지표는 Media_RAW에 0으로 비어 있으므로 `iOS 코호트 RD` 탭에서 채워 넣는다.
    """
    cache = _cache_path(sheet_id)
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)

    credentials = get_credentials()
    # Media_RAW는 12만 행대라 한 번에 받으면 36초가 걸린다(실측) — 행 구간을 쪼개
    # 병렬로 받는다. 작은 탭은 이 함수가 알아서 단일 요청으로 넘긴다.
    values = fetch_sheet_values_parallel(sheet_id, RAW_SHEET_NAME, credentials)
    df = attach_creative_attributes(parse_raw_values(values))

    try:
        cohort = parse_ios_cohort(
            fetch_sheet_values(sheet_id, IOS_COHORT_SHEET_NAME, credentials)
        )
        df = apply_ios_cohort(df, cohort)
    except Exception as error:  # 코호트 탭이 없어도 나머지는 쓸 수 있어야 한다
        df.attrs["ios_cohort_error"] = str(error)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def cache_timestamp(sheet_id: str) -> float | None:
    cache = _cache_path(sheet_id)
    return cache.stat().st_mtime if cache.exists() else None


def list_tabs(sheet_id: str) -> list[str]:
    service = build("sheets", "v4", credentials=get_credentials())
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def creative_tab_candidates(tabs: list[str]) -> list[str]:
    """구글 블록이 들어있는 크리에이티브 리포트 탭 후보. 탭 이름이 매달 바뀌므로 이름으로 거른다."""
    return [t for t in tabs if "creative" in t.lower()]


def load_google(sheet_id: str, tab_name: str) -> pd.DataFrame:
    """리포트 탭에 붙어있는 구글 소재 블록을 읽는다.

    구글은 `Media_RAW`에 존재하지 않는다 — 매체 대시보드 내보내기를 담당자가 이 탭에 붙여넣는다.
    """
    values = fetch_sheet_values(sheet_id, f"'{tab_name}'", get_credentials())
    return load_google_creatives(values)
