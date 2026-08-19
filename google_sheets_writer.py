"""구글 애셋 리포트 월별 스냅샷을 전용 구글시트에 쓰고 읽는다.

이 파일은 프로젝트에서 유일하게 구글시트에 "쓰는" 코드다. `google_sheets_readonly.py`는
Media_RAW를 읽기만 하는 원칙을 지키므로, 쓰기는 완전히 분리된 이 모듈에서만 일어난다.

권한 격리: OAuth 개인 계정 토큰(읽기용)과 달리, 이 모듈은 이 스냅샷 시트 하나에만 편집자로
공유된 별도 서비스 계정(로봇 계정)을 쓴다. 이 자격증명이 유출돼도 접근 가능한 범위는
GOOGLE_SNAPSHOT_SHEET_ID로 지정된 시트 하나뿐이다 — Media_RAW를 포함해 다른 어떤 시트도
이 서비스 계정에 공유되어 있지 않으면 아예 존재 자체를 모른다.

저장 형식: `google_ads_report.load_google_ads_folder`가 만드는 것과 같은 스키마의
DataFrame을 월별 탭(`snapshot_<월>`)에 그대로 쓴다. 비용은 마크업 적용 전 원가로
저장하고(cost_markup=1.0 기준), 읽을 때 현재 마크업 배율을 곱해서 돌려준다 — 라이브
경로와 똑같이 마크업 슬라이더에 반응하게 하기 위해서다(고정되는 건 원본 수치이지,
그 시점의 마크업 계산 결과가 아니다). 고정 시각은 `_snapshot_meta` 탭에 월별로 남긴다.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
META_TAB = "_snapshot_meta"
_NUMERIC_COLUMNS = ("impression", "click", "cost_raw", "total install", "in_app_action", "month")


def _secret(name: str):
    """Streamlit secrets 우선, 없으면 환경변수. streamlit 미설치/미설정이면 조용히 건너뛴다."""
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def _service_account_info() -> dict | None:
    info = _secret("gcp_service_account")
    return dict(info) if info else None


def configured() -> bool:
    """서비스 계정 + 시트 ID가 모두 설정돼 있으면 True (로컬 개발 PC는 설정 전엔 False)."""
    return _service_account_info() is not None and bool(_secret("GOOGLE_SNAPSHOT_SHEET_ID"))


def _sheet_id() -> str:
    return str(_secret("GOOGLE_SNAPSHOT_SHEET_ID"))


def _service():
    creds = service_account.Credentials.from_service_account_info(
        _service_account_info(), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def _tab_name(month: int) -> str:
    return f"snapshot_{int(month)}"


def _existing_tabs(service) -> set[str]:
    meta = service.spreadsheets().get(spreadsheetId=_sheet_id()).execute()
    return {s["properties"]["title"] for s in meta.get("sheets", [])}


def _ensure_tab(service, title: str) -> None:
    if title in _existing_tabs(service):
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=_sheet_id(),
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()


def month_exists(month: int) -> bool:
    try:
        return _tab_name(month) in _existing_tabs(_service())
    except Exception:
        return False


def frozen_at(month: int) -> str | None:
    try:
        service = _service()
        if META_TAB not in _existing_tabs(service):
            return None
        rows = service.spreadsheets().values().get(
            spreadsheetId=_sheet_id(), range=META_TAB
        ).execute().get("values", [])
        for row in rows[1:]:
            if len(row) >= 2 and row[0] == str(month):
                return row[1]
    except Exception:
        return None
    return None


def write_month(month: int, df: pd.DataFrame) -> None:
    """df(마크업 적용 전 원가 기준)를 이 달 스냅샷 탭에 통째로 쓴다. 이미 있으면 덮어쓴다."""
    service = _service()
    tab = _tab_name(month)
    _ensure_tab(service, tab)
    service.spreadsheets().values().clear(spreadsheetId=_sheet_id(), range=tab).execute()

    body_df = df.astype(object).where(df.notna(), "")
    values = [list(body_df.columns)] + body_df.values.tolist()
    service.spreadsheets().values().update(
        spreadsheetId=_sheet_id(), range=f"{tab}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()

    _ensure_tab(service, META_TAB)
    existing_meta = service.spreadsheets().values().get(
        spreadsheetId=_sheet_id(), range=META_TAB
    ).execute().get("values", [])
    meta = {row[0]: row[1] for row in existing_meta[1:] if len(row) >= 2}
    meta[str(month)] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    meta_values = [["month", "frozen_at"]] + [[k, v] for k, v in meta.items()]
    service.spreadsheets().values().update(
        spreadsheetId=_sheet_id(), range=f"{META_TAB}!A1",
        valueInputOption="RAW", body={"values": meta_values},
    ).execute()


def read_month(month: int) -> pd.DataFrame | None:
    """스냅샷 탭을 원가 기준 DataFrame으로 돌려준다. 탭이 없으면 None."""
    service = _service()
    tab = _tab_name(month)
    if tab not in _existing_tabs(service):
        return None
    rows = service.spreadsheets().values().get(
        spreadsheetId=_sheet_id(), range=tab
    ).execute().get("values", [])
    if not rows:
        return None
    header, *body = rows
    body = [r + [""] * (len(header) - len(r)) for r in body]  # 짧은 행(뒤 빈 칸) 채우기
    df = pd.DataFrame(body, columns=header)
    for col in _NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.replace("", pd.NA)
