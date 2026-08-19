"""
구글시트를 읽기 전용으로만 조회하는 얇은 래퍼.

이 파일에는 `spreadsheets.values.get` 호출만 존재해야 한다 — `update`/`batchUpdate`/`append` 등
쓰기 계열 API는 절대 추가하지 않는다 (원본 시트를 수정하지 않는다는 요구사항).
"""

import json
import os
import socket
import ssl
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_PATH = os.path.expanduser("~/.config/claude-mcp/token.json")

# Media_RAW 탭이 12만 행대라 응답이 느리고 "The read operation timed out"이 간헐적으로 난다.
# ASA 위클리 대시보드와 같은 재시도 로직을 그대로 가져온다.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (3, 8)
RETRYABLE_HTTP_STATUS = (429, 500, 502, 503, 504)
_RETRYABLE_MESSAGES = ("timed out", "timeout", "connection reset", "connection aborted")


def is_retryable_error(exc):
    """일시적인 네트워크/서버 오류인지 판단한다 (순수 함수 — pytest 대상).

    권한 오류나 잘못된 시트 ID처럼 다시 시도해도 똑같이 실패할 오류는 걸러낸다."""
    if isinstance(exc, (socket.timeout, ssl.SSLError, ConnectionError, TimeoutError)):
        return True
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in RETRYABLE_HTTP_STATUS:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_MESSAGES)


def read_with_retry(run, sleep=time.sleep, attempts=MAX_ATTEMPTS):
    """run()을 실행하고, 일시적 오류면 잠깐 쉬었다 다시 시도한다.

    마지막 시도까지 실패하거나 재시도 대상이 아닌 오류면 그대로 올려보낸다 —
    사이드바에 원인이 그대로 보여야 하기 때문."""
    for attempt in range(attempts):
        try:
            return run()
        except Exception as exc:  # noqa: BLE001 - 판단은 is_retryable_error에 맡긴다
            last_attempt = attempt == attempts - 1
            if last_attempt or not is_retryable_error(exc):
                raise
            wait = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
            sleep(wait)


def _credentials_from_streamlit_secrets():
    """배포 환경(Streamlit Cloud)에서는 로컬 TOKEN_PATH 파일이 없다 — 대신 그 서버의 자체
    Secrets 저장소에 [google_oauth] 테이블로 넣어둔 값을 쓴다. 로컬 개발 중이거나 Streamlit
    없이 이 파일만 테스트할 때는 조용히 None을 돌려주고 기존 파일 경로로 넘어간다."""
    try:
        import streamlit as st
    except ImportError:
        return None
    try:
        if "google_oauth" not in st.secrets:
            return None
        return dict(st.secrets["google_oauth"])
    except Exception:  # noqa: BLE001 - secrets.toml이 아예 없는 로컬 실행도 여기로 온다
        return None


def get_credentials():
    """자격증명을 가져온다. 배포 환경의 Streamlit secrets를 먼저 보고, 없으면 로컬
    TOKEN_PATH 파일을 쓴다 — 같은 코드로 로컬 개발과 배포 둘 다 동작하게 하기 위해서다."""
    info = _credentials_from_streamlit_secrets()
    if info is not None:
        creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
        if not creds.valid:
            creds.refresh(Request())
        return creds

    with open(TOKEN_PATH) as f:
        info = json.load(f)
    creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if not creds.valid:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def fetch_sheet_values(spreadsheet_id, sheet_name, credentials):
    """sheet_name 탭 전체 값을 2차원 리스트(첫 행이 헤더)로 반환한다. 읽기 전용 호출만 사용."""
    service = build("sheets", "v4", credentials=credentials)

    def run():
        return service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=sheet_name,
        ).execute()

    result = read_with_retry(run)
    return result.get("values", [])
