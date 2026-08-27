"""
구글시트를 읽기 전용으로만 조회하는 얇은 래퍼.

이 파일에는 `spreadsheets.values.get` 호출만 존재해야 한다 — `update`/`batchUpdate`/`append` 등
쓰기 계열 API는 절대 추가하지 않는다 (원본 시트를 수정하지 않는다는 요구사항).
"""

import json
import os
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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

# 큰 탭을 행 구간으로 쪼개 병렬로 받을 때의 설정.
# 병목이 전송량이 아니라 요청당 왕복 지연이라(2026-08-28 실측: 12.6만 행 한 방 요청 36.0초),
# 구간을 나눠 동시에 받으면 크게 줄어든다. 실측 6등분 8.1초 / 8등분 8.7초 / 12등분 10.3초 —
# 더 쪼개면 구글 쪽 처리 경쟁으로 오히려 느려져서 6을 기본값으로 둔다.
PARALLEL_CHUNKS = 6
# 이 행 수 이하인 탭은 쪼개도 이득이 없다(요청 1회가 이미 몇 초 안쪽). iOS 코호트 탭
# 1만 행이 2.1초라 그 근처를 경계로 잡는다.
PARALLEL_MIN_ROWS = 20_000


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


def column_letter(count):
    """1-based 열 번호 → A1 표기 열 문자(1→A, 26→Z, 27→AA, 49→AW). 순수 함수 — pytest 대상."""
    if count < 1:
        raise ValueError(f"열 수는 1 이상이어야 합니다: {count}")
    letters = ""
    while count:
        count, remainder = divmod(count - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def row_chunks(total_rows, chunks=PARALLEL_CHUNKS):
    """1..total_rows를 chunks개의 (시작행, 끝행) 구간으로 나눈다. 순수 함수 — pytest 대상.

    구간은 빈틈도 겹침도 없어야 한다 — 빈틈이 생기면 소재가 조용히 사라지고, 겹치면
    같은 행이 두 번 집계된다. 이 프로젝트에서 가장 위험한 두 가지 실패 방식이라
    호출부가 아니라 이 함수에서 못 박고 테스트로 고정한다.
    """
    if total_rows < 1:
        return []
    chunks = max(1, min(chunks, total_rows))
    step = -(-total_rows // chunks)  # 위로 올림
    out = []
    start = 1
    while start <= total_rows:
        out.append((start, min(total_rows, start + step - 1)))
        start += step
    return out


def _grid_size(spreadsheet_id, sheet_name, credentials):
    """탭의 격자 크기(행, 열)를 돌려준다. 값을 받지 않으므로 빠르다(실측 0.7초).

    격자는 값을 넣을 수 있는 공간 전체라서, **격자보다 아래/오른쪽에 데이터가 있을 수는
    없다**(실제로 격자 밖 범위를 요청하면 API가 400으로 거부한다 — 2026-08-28 확인).
    따라서 이 값은 실제 데이터 범위의 상한으로 안전하게 쓸 수 있다.
    """
    service = build("sheets", "v4", credentials=credentials)

    def run():
        return service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(title,gridProperties(rowCount,columnCount)))",
        ).execute()

    wanted = sheet_name.strip().strip("'")
    for sheet in read_with_retry(run).get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == wanted:
            grid = properties.get("gridProperties", {})
            return grid.get("rowCount", 0), grid.get("columnCount", 0)
    raise ValueError(f"'{wanted}' 탭을 찾을 수 없습니다.")


def fetch_sheet_values_parallel(
    spreadsheet_id, sheet_name, credentials, chunks=PARALLEL_CHUNKS
):
    """큰 탭을 행 구간으로 쪼개 병렬로 받는다. 반환 형식은 fetch_sheet_values와 같다.

    작은 탭은 쪼개도 이득이 없어 그냥 단일 요청으로 넘긴다. 격자 크기를 **매 호출마다**
    새로 읽으므로 시트가 커져도 구간이 자동으로 다시 나뉜다 — 행 수를 코드에 박으면
    다음 달에 늘어난 만큼이 조용히 빠진다.
    """
    rows, columns = _grid_size(spreadsheet_id, sheet_name, credentials)
    if rows < PARALLEL_MIN_ROWS or columns < 1:
        return fetch_sheet_values(spreadsheet_id, sheet_name, credentials)

    ranges = row_chunks(rows, chunks)
    last_column = column_letter(columns)
    tab = sheet_name.strip().strip("'")
    local = threading.local()

    def service():
        # 구글 API 클라이언트는 내부에 http 세션을 들고 있어 스레드 간 공유 안전이
        # 보장되지 않는다 — 워커마다 자기 것을 만들어 쓴다.
        if not hasattr(local, "value"):
            local.value = build("sheets", "v4", credentials=credentials)
        return local.value

    def fetch(bounds):
        start, end = bounds

        def run():
            return service().spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"'{tab}'!A{start}:{last_column}{end}",
            ).execute()

        return read_with_retry(run).get("values", [])

    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        # list()로 감싸 예외를 그대로 올린다 — 한 구간만 실패해도 그만큼 소재가
        # 사라진 채 "정상"으로 보이는 게 최악이다.
        parts = list(pool.map(fetch, ranges))

    values = [row for part in parts for row in part]
    if not values:
        raise RuntimeError(
            f"'{tab}' 탭을 {len(ranges)}개 구간으로 나눠 받았으나 한 행도 오지 않았습니다."
        )
    # 구간 합이 격자보다 많으면 범위가 겹쳤다는 뜻이다(같은 행 이중 집계).
    if len(values) > rows:
        raise RuntimeError(
            f"'{tab}' 탭 수신 행({len(values):,})이 격자 행({rows:,})을 넘었습니다 — 구간이 겹쳤습니다."
        )
    return values
