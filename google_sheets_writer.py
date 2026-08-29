"""구글 애셋 리포트 월별 스냅샷과, 리포트 블록(코멘트·조건 등) 구성을 전용 구글시트에 쓰고 읽는다.

이 파일은 프로젝트에서 유일하게 구글시트에 "쓰는" 코드다. `google_sheets_readonly.py`는
Media_RAW를 읽기만 하는 원칙을 지키므로, 쓰기는 완전히 분리된 이 모듈에서만 일어난다.

권한 격리: OAuth 개인 계정 토큰(읽기용)과 달리, 이 모듈은 이 스냅샷 시트 하나에만 편집자로
공유된 별도 서비스 계정(로봇 계정)을 쓴다. 이 자격증명이 유출돼도 접근 가능한 범위는
GOOGLE_SNAPSHOT_SHEET_ID로 지정된 시트 하나뿐이다 — Media_RAW를 포함해 다른 어떤 시트도
이 서비스 계정에 공유되어 있지 않으면 아예 존재 자체를 모른다.

저장 형식(스냅샷): `google_ads_report.load_google_ads_folder`가 만드는 것과 같은 스키마의
DataFrame을 월별 탭(`snapshot_<월>`)에 그대로 쓴다. 비용은 마크업 적용 전 원가로
저장하고(cost_markup=1.0 기준), 읽을 때 현재 마크업 배율을 곱해서 돌려준다 — 라이브
경로와 똑같이 마크업 슬라이더에 반응하게 하기 위해서다(고정되는 건 원본 수치이지,
그 시점의 마크업 계산 결과가 아니다). 고정 시각은 `_snapshot_meta` 탭에 월별로 남긴다.

저장 형식(블록): `blocks.py`의 월별 블록 구성 전체(제목·코멘트·조건 등)를 JSON 문자열
그대로 월별 탭(`blocks_<월>`) A1 셀 하나에 넣는다. 배포판(Streamlit Community Cloud)의
로컬 디스크는 재배포·리부트마다 초기화되므로, 로컬 파일(`notes/blocks_<월>.json`)만
믿으면 배포판에서 남긴 코멘트가 그대로 휘발된다 — 이미 스냅샷용으로 격리해 둔 같은
서비스 계정·시트를 재사용해 코멘트도 여기 영구 저장한다.

저장 형식(이미지): NEXT STEP/분석 블록에 첨부한 레퍼런스 이미지를 `images_<월>` 탭에 청크
단위로 저장한다. 구글시트 셀 하나는 약 5만자 제한이 있어 base64로 인코딩한 이미지 전체를
셀 하나에 못 넣는 경우가 많으므로, `CHUNK_SIZE`자씩 잘라 (파일명, 순번, 조각) 행으로 여러 줄에
나눠 쓰고 읽을 때 순번대로 이어 붙인다.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
from dataclasses import dataclass, field as dataclass_field

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
META_TAB = "_snapshot_meta"
# 세 번째 컬럼(rev)은 행 단위 upsert용이다. 예전 2컬럼 메타 탭도 그대로 읽힌다.
META_HEADER = ["month", "frozen_at", "rev"]
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

    # 고정 시각은 이 달 행 하나만 갱신한다. 예전에는 메타 탭 전체를 다시 써서, 두 사람이
    # 서로 다른 달을 동시에 고정하면 한쪽 frozen_at이 조용히 사라졌다.
    store_upsert(
        META_TAB, META_HEADER,
        {"month": str(int(month)),
         "frozen_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
         REV_COLUMN: ""},
    )


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


def diagnostics() -> dict:
    """이 배포판이 실제로 어느 시트에 붙어 있는지 화면에서 바로 확인하기 위한 진단 정보.

    자격증명 값 자체는 절대 돌려주지 않는다 — 시트 ID는 앞뒤 몇 글자만 마스킹해서 보여주고,
    실제 접근 가능한 탭 목록으로 "설정은 됐는데 엉뚱한/빈 시트를 보고 있다"는 흔한 실패를
    구분할 수 있게 한다.
    """
    info: dict = {"configured": configured()}
    if not info["configured"]:
        return info
    sheet_id = _sheet_id()
    info["sheet_id_masked"] = (
        f"{sheet_id[:6]}...{sheet_id[-4:]}" if len(sheet_id) > 12 else "***"
    )
    try:
        service = _service()
        info["tabs"] = sorted(_existing_tabs(service))
    except Exception as error:  # noqa: BLE001 - 화면에 원인을 그대로 보여주기 위해 잡는다
        info["error"] = f"{type(error).__name__}: {error}"
    return info


def _blocks_tab_name(month: int) -> str:
    return f"blocks_{int(month)}"


def write_blocks(month: int, data: dict) -> None:
    """블록 구성 전체를 JSON 문자열 하나로 이 달 탭에 통째로 쓴다(있으면 덮어쓴다)."""
    service = _service()
    tab = _blocks_tab_name(month)
    _ensure_tab(service, tab)
    payload = json.dumps(data, ensure_ascii=False)
    service.spreadsheets().values().update(
        spreadsheetId=_sheet_id(), range=f"{tab}!A1",
        valueInputOption="RAW", body={"values": [[payload]]},
    ).execute()


def read_blocks(month: int) -> dict | None:
    """예전 형식(한 셀 JSON)의 블록 구성을 읽는다. 탭이 없거나 비어 있으면 None.

    새 형식(blockrows_<월>)으로 옮긴 뒤에도 **한 번의 이관 원본**으로 계속 필요하다.
    실패와 "없음"을 구분해야 하는 곳에서는 read_blocks_result를 쓴다.
    """
    service = _service()
    tab = _blocks_tab_name(month)
    if tab not in _existing_tabs(service):
        return None
    rows = service.spreadsheets().values().get(
        spreadsheetId=_sheet_id(), range=f"{tab}!A1"
    ).execute().get("values", [])
    if not rows or not rows[0]:
        return None
    try:
        data = json.loads(rows[0][0])
    except (json.JSONDecodeError, TypeError, IndexError):
        return None
    return data if isinstance(data, dict) else None


# ----------------------------------------------------------------------------
# 이미지 첨부 — 청크 단위 저장(셀당 약 5만자 제한 우회)

CHUNK_SIZE = 40_000


def _images_tab_name(month: int) -> str:
    return f"images_{int(month)}"


def write_image(month: int, stored_name: str, data: bytes) -> None:
    """이미지를 base64로 인코딩해 청크로 나눠 이 달 이미지 탭에 추가한다(append)."""
    service = _service()
    tab = _images_tab_name(month)
    _ensure_tab(service, tab)
    encoded = base64.b64encode(data).decode("ascii")
    chunks = [encoded[i : i + CHUNK_SIZE] for i in range(0, len(encoded), CHUNK_SIZE)] or [""]
    rows = [[stored_name, str(seq), chunk] for seq, chunk in enumerate(chunks)]
    service.spreadsheets().values().append(
        spreadsheetId=_sheet_id(), range=f"{tab}!A1",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


# 이미지 바이트 캐시. stored_name은 `{월}_{타임스탬프}_{파일명}`이라 내용이 절대 바뀌지
# 않는(불변) 키다 — 그래서 유효시간 없이 캐시해도 스테일 문제가 없다. 캐시가 없으면
# 첨부 이미지 하나를 그릴 때마다 그 달 이미지 탭 전체를 다시 읽어, 이 앱에서 가장 무거운
# API 소비처가 된다(사람이 여러 명이면 그만큼 배가된다).
_IMAGE_CACHE: dict[tuple[int, str], bytes] = {}
_IMAGE_CACHE_MAX = 64


def clear_image_cache(month: int | None = None, stored_name: str | None = None) -> None:
    if month is None:
        _IMAGE_CACHE.clear()
        return
    _IMAGE_CACHE.pop((int(month), str(stored_name)), None)


def read_image(month: int, stored_name: str) -> bytes | None:
    """저장된 이미지를 청크 순서대로 이어 붙여 원본 바이트로 돌려준다. 없으면 None."""
    cache_key = (int(month), str(stored_name))
    if cache_key in _IMAGE_CACHE:
        return _IMAGE_CACHE[cache_key]

    read = store_read(_images_tab_name(month))
    if not read.ok:
        return None
    matched = [r for r in read.rows if len(r) >= 1 and r[0] == stored_name]
    if not matched:
        return None
    try:
        matched.sort(key=lambda r: int(r[1]) if len(r) > 1 else 0)
        encoded = "".join(r[2] if len(r) > 2 else "" for r in matched)
        data = base64.b64decode(encoded) if encoded else b""
    except (ValueError, TypeError):
        # 잘린 base64(다른 세션의 쓰기 도중에 읽은 경우 등)는 실패로 돌려주되 캐시하지
        # 않는다 — 일시적 오류를 굳히면 그 이미지가 세션 내내 빈칸으로 남는다.
        return None
    if len(_IMAGE_CACHE) >= _IMAGE_CACHE_MAX:
        _IMAGE_CACHE.clear()
    _IMAGE_CACHE[cache_key] = data
    return data


def delete_image(month: int, stored_name: str) -> None:
    """이 이미지의 청크 행만 지운다.

    예전에는 탭을 통째로 읽고 clear한 뒤 나머지를 다시 썼다. 그 사이(clear~재작성)에
    다른 사람이 화면을 열면 그 달 첨부 이미지가 **전부 빈칸**으로 보였고, 그 틈에 올라온
    업로드는 유실됐다. 이제 일치하는 행 번호만 골라 한 번의 batchUpdate로 지운다 —
    탭이 비는 순간이 없다.
    """
    clear_image_cache(month, stored_name)
    read = store_read(_images_tab_name(month))
    if not read.ok:
        return
    numbers = [
        i + 1 for i, row in enumerate(read.rows)
        if row and str(row[0]) == str(stored_name)
    ]
    _delete_rows(_images_tab_name(month), numbers)


# ----------------------------------------------------------------------------
# 행 단위 저장소 (row store) — 동시 저장으로 남의 데이터가 사라지는 것을 막는 핵심 장치
#
# 왜 필요한가: 원래 이 파일의 쓰기는 전부 "탭을 통째로 읽고 → clear() → 통째로 다시 쓰기"
# 였다. 두 사람이 **서로 다른 것**을 저장해도, 늦게 쓴 쪽이 자기가 읽어둔 옛 스냅샷으로
# 탭 전체를 재작성하기 때문에 먼저 저장된 내용이 조용히 사라진다(lost update).
# ASA 위클리 대시보드에서 실제로 이 방식 때문에 한 캠페인의 코멘트 5개가 통째로 날아갔다.
#
# 그래서 여기서는 "키 하나 = 행 하나"로 저장하고, 그 행만 갱신·삭제한다.
# - upsert: 키가 있는 행을 A{행} 범위로만 update, 없으면 append(INSERT_ROWS)
# - delete: 그 행만 deleteDimension (탭 clear 금지)
# 서로 다른 키를 저장하는 두 사람은 이제 원리적으로 충돌하지 않는다.
#
# 같은 키를 동시에 저장하는 경우는 rev(정수 버전) 비교로 막는다. 저장할 때 "내가 읽은
# rev와 시트의 rev가 같을 때만 쓴다"를 요구하면(compare-and-set), 늦게 누른 사람은
# 덮어쓰지 못하고 거부당한다 — 조용히 남의 글을 지우는 것보다 거부가 훨씬 낫다.

REV_COLUMN = "rev"

# 이관 완료 표식 행의 키. 이 키의 행이 있으면 "예전 데이터에서 한 번 옮기는 일"을 이미
# 했다는 뜻이다. 표식이 없으면 탭이 비어 있어도 이관 대상으로 본다.
MIGRATION_KEY = "__migrated__"


@dataclass
class StoreRead:
    """행 저장소 읽기 결과.

    empty(데이터가 아직 없음)와 error(읽기 자체가 실패)를 반드시 구분한다.
    둘을 같은 값으로 뭉개면 "일시적 읽기 실패"를 "데이터 없음"으로 오인해 그 위에
    빈 값을 저장하게 되고, 그 순간 한 달치 내용이 전원에게서 사라진다.
    """

    status: str  # "ok" | "empty" | "error"
    rows: list[list[str]] = dataclass_field(default_factory=list)  # 헤더 행 포함
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def failed(self) -> bool:
        return self.status == "error"


def _as_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def store_read(tab: str) -> StoreRead:
    """탭 전체를 읽는다(헤더 포함). 탭이 없으면 empty, API 실패면 error."""
    try:
        service = _service()
        if tab not in _existing_tabs(service):
            return StoreRead("empty")
        rows = service.spreadsheets().values().get(
            spreadsheetId=_sheet_id(), range=tab
        ).execute().get("values", [])
    except Exception as error:  # noqa: BLE001 - 실패를 삼키지 않고 호출자에게 넘긴다
        return StoreRead("error", reason=f"{type(error).__name__}: {error}")
    if not rows:
        return StoreRead("empty")
    return StoreRead("ok", rows)


def _looks_like_header(row: list[str], header: list[str]) -> bool:
    return bool(row) and str(row[0]).strip() == header[0]


def store_rows(read: StoreRead, header: list[str]) -> list[list[str]]:
    """읽기 결과에서 데이터 행만 헤더 길이에 맞춰 돌려준다(짧은 행은 빈 칸으로 채운다)."""
    if not read.ok:
        return []
    body = read.rows[1:] if _looks_like_header(read.rows[0], header) else read.rows
    width = len(header)
    return [(list(r) + [""] * width)[:width] for r in body if r and str(r[0]).strip()]


def _matches(read: StoreRead, header: list[str], key: str) -> list[tuple[int, dict]]:
    """키에 일치하는 (시트 행 번호, 레코드) 목록. 중복이 있으면 여러 개가 나온다."""
    rows = read.rows
    has_header = bool(rows) and _looks_like_header(rows[0], header)
    start = 1 if has_header else 0
    width = len(header)
    found: list[tuple[int, dict]] = []
    for offset, row in enumerate(rows[start:]):
        if row and str(row[0]) == str(key):
            padded = (list(row) + [""] * width)[:width]
            found.append((start + offset + 1, dict(zip(header, padded))))
    return found


def store_get(read: StoreRead, header: list[str], key: str) -> dict | None:
    """키에 해당하는 행을 {컬럼: 값} 으로 돌려준다. 없으면 None.

    같은 키가 여러 줄이면 rev가 가장 큰 줄을 고른다 — 읽기 결과가 줄 순서에 따라
    달라지지 않게 하기 위해서다.
    """
    found = _matches(read, header, key)
    if not found:
        return None
    return max(found, key=lambda item: _as_int(item[1].get(REV_COLUMN)))[1]


def store_row_numbers(read: StoreRead, header: list[str], key: str) -> list[int]:
    return [number for number, _record in _matches(read, header, key)]


def store_upsert(
    tab: str, header: list[str], values: dict, expected_rev: int | None = None
) -> tuple[bool, str | None]:
    """키(첫 컬럼) 하나에 해당하는 그 행만 갱신한다. 없으면 새 행으로 붙인다.

    expected_rev를 주면 시트의 rev가 그 값과 같을 때만 쓴다. 다르면 아무것도 쓰지 않고
    ("conflict"/"deleted") 이유를 돌려준다 — 그 사이 다른 사람이 같은 것을 고쳤다는 뜻이다.

    돌려주는 값: (성공 여부, 실패 이유). 성공하면 이유는 None.
    """
    key = str(values[header[0]])
    read = store_read(tab)
    if read.failed:
        return False, read.reason

    current = store_get(read, header, key)
    current_rev = _as_int(current.get(REV_COLUMN)) if current else 0
    if expected_rev is not None:
        if current is None and int(expected_rev) != 0:
            return False, "deleted"
        if current is not None and current_rev != int(expected_rev):
            return False, "conflict"

    row = [str(values.get(col, "")) for col in header]
    row[header.index(REV_COLUMN)] = str(current_rev + 1)

    try:
        service = _service()
        _ensure_tab(service, tab)
        if not read.ok:
            # 탭이 완전히 비어 있다 — 헤더부터 놓는다.
            service.spreadsheets().values().update(
                spreadsheetId=_sheet_id(), range=f"{tab}!A1",
                valueInputOption="RAW", body={"values": [header, row]},
            ).execute()
            return True, None
        numbers = store_row_numbers(read, header, key)
        if not numbers:
            service.spreadsheets().values().append(
                spreadsheetId=_sheet_id(), range=f"{tab}!A1",
                valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
        else:
            if len(numbers) > 1:
                # 중복 줄은 여기서 스스로 정리된다(첫 줄만 남긴다).
                _delete_rows(tab, numbers[1:])
            service.spreadsheets().values().update(
                spreadsheetId=_sheet_id(), range=f"{tab}!A{numbers[0]}",
                valueInputOption="RAW", body={"values": [row]},
            ).execute()
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"
    return True, None


def _sheet_ids(service) -> dict[str, int]:
    meta = service.spreadsheets().get(spreadsheetId=_sheet_id()).execute()
    return {
        s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])
    }


def _delete_rows(tab: str, numbers: list[int]) -> None:
    """지정한 시트 행 번호들만 지운다(탭 clear 금지 — 다른 행을 건드리지 않는다).

    한 번의 batchUpdate로 보내되, 앞 행을 지우면 뒤 행 번호가 밀리므로 뒤에서 앞으로
    지운다. 요청 하나로 묶여 있어 중간 상태(탭이 잠깐 비는 순간)가 생기지 않는다 —
    이게 clear-then-rewrite 방식과의 결정적인 차이다.
    """
    if not numbers:
        return
    service = _service()
    sheet_id = _sheet_ids(service).get(tab)
    if sheet_id is None:
        return
    requests = [
        {"deleteDimension": {"range": {
            "sheetId": sheet_id, "dimension": "ROWS",
            "startIndex": n - 1, "endIndex": n,
        }}}
        for n in sorted(numbers, reverse=True)
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=_sheet_id(), body={"requests": requests}
    ).execute()


def mark_migrated(tab: str, header: list[str]) -> None:
    """이 저장소는 예전 데이터에서 이미 한 번 옮겨왔다고 표시한다."""
    values = {col: "" for col in header}
    values[header[0]] = MIGRATION_KEY
    store_upsert(tab, header, values)


def has_migration_mark(read: StoreRead, header: list[str]) -> bool:
    return store_get(read, header, MIGRATION_KEY) is not None


def store_delete(tab: str, header: list[str], key: str) -> None:
    """키에 해당하는 행을 (중복이 있으면 전부) 지운다. 없으면 아무것도 하지 않는다."""
    read = store_read(tab)
    if not read.ok:
        return
    _delete_rows(tab, store_row_numbers(read, header, key))


# ----------------------------------------------------------------------------
# 블록 — 한 셀 JSON에서 "블록 1개 = 1행"으로
#
# 예전 형식(blocks_<월>!A1에 그 달 블록 전체를 JSON 한 덩어리로)은 남겨둔다. 새 탭은
# 이름이 다르므로(blockrows_<월>) 이관 실패 시에도 원본이 그대로 남아 복구할 수 있다.

BLOCK_HEADER = ["block_id", "slot", "seq", REV_COLUMN, "json"]


def block_rows_tab(month: int) -> str:
    return f"blockrows_{int(month)}"


def read_block_rows(month: int) -> tuple[str, list[dict], str | None]:
    """(상태, 블록 행 목록, 실패 이유). 상태는 "ok" | "empty" | "error".

    각 항목: {"block_id","slot","seq","rev","block"} — block은 파싱된 dict.
    JSON이 깨진 행은 버리지 않고 상태를 error로 올린다(빈 값으로 덮어쓰지 못하게).
    """
    read = store_read(block_rows_tab(month))
    if read.failed:
        return "error", [], read.reason
    if not read.ok:
        return "empty", [], None
    by_id: dict[str, dict] = {}
    for row in store_rows(read, BLOCK_HEADER):
        record = dict(zip(BLOCK_HEADER, row))
        if record["block_id"] == MIGRATION_KEY:
            continue
        try:
            block = json.loads(record["json"])
        except (json.JSONDecodeError, TypeError):
            return "error", [], f"블록 {record['block_id']} 의 JSON이 깨져 있습니다"
        if not isinstance(block, dict) or not block.get("id"):
            continue
        item = {
            "block_id": record["block_id"], "slot": record["slot"],
            "seq": _as_int(record["seq"]), "rev": _as_int(record[REV_COLUMN]),
            "block": block,
        }
        # 같은 block_id가 두 줄이면(이관이 두 번 겹쳐 실행된 경우) rev가 큰 쪽만 남긴다.
        # 남은 중복 줄은 다음 저장 때 store_upsert가 스스로 정리한다.
        previous = by_id.get(item["block_id"])
        if previous is None or previous["rev"] <= item["rev"]:
            by_id[item["block_id"]] = item
    items = list(by_id.values())
    if not items and not has_migration_mark(read, BLOCK_HEADER):
        # 탭은 있지만(헤더만) 아직 아무것도 없고 이관 표식도 없다 — 예전 형식에서 한 번
        # 옮겨올 기회를 주어야 한다. 표식이 있으면 "정말로 빈 달"이므로 ok로 둔다.
        return "empty", [], None
    return "ok", items, None


def upsert_block_row(
    month: int, block_id: str, slot: str, seq: int, block: dict,
    expected_rev: int | None = None,
) -> tuple[bool, str | None]:
    return store_upsert(
        block_rows_tab(month), BLOCK_HEADER,
        {
            "block_id": block_id, "slot": slot, "seq": str(int(seq)),
            REV_COLUMN: "", "json": json.dumps(block, ensure_ascii=False),
        },
        expected_rev=expected_rev,
    )


def delete_block_row(month: int, block_id: str) -> None:
    store_delete(block_rows_tab(month), BLOCK_HEADER, block_id)


# ----------------------------------------------------------------------------
# 오버라이드 / 하이라이트 / 편집 잠금 — 전부 같은 행 저장소 위에
#
# 원래 이 셋은 로컬 파일(notes/*.json)에만 있었다. 배포판(Streamlit Community Cloud)은
# 재배포·리부트마다 로컬 디스크가 초기화되므로, 수동 분류·셀 강조·잠금이 조용히 전멸했다
# (블록·이미지를 시트로 옮긴 것과 똑같은 이유다). 게다가 파일 하나를 통째로 다시 쓰기
# 때문에 두 사람이 다른 키를 저장해도 서로를 지웠다.

OVERRIDE_HEADER = ["ad", REV_COLUMN, "json"]
HIGHLIGHT_HEADER = ["table_key", REV_COLUMN, "json"]
LOCK_HEADER = ["key", REV_COLUMN, "owner", "acquired_at", "touched_at"]
LOCKS_TAB = "locks_state"


def _json_store_read(tab: str, header: list[str]) -> tuple[str, dict, str | None]:
    """{키: 파싱된 JSON} 형태로 읽는다. (상태, 값, 실패 이유)."""
    read = store_read(tab)
    if read.failed:
        return "error", {}, read.reason
    if not read.ok:
        return "empty", {}, None
    out: dict = {}
    for row in store_rows(read, header):
        record = dict(zip(header, row))
        if record[header[0]] == MIGRATION_KEY:
            continue
        try:
            out[record[header[0]]] = json.loads(record["json"])
        except (json.JSONDecodeError, TypeError):
            continue  # 값 하나가 깨진 것으로 나머지를 못 읽게 만들지는 않는다
    if not out and not has_migration_mark(read, header):
        return "empty", {}, None
    return "ok", out, None


def read_overrides(month: int) -> tuple[str, dict, str | None]:
    return _json_store_read(f"overrides_{int(month)}", OVERRIDE_HEADER)


def write_override(month: int, ad: str, fields: dict) -> tuple[bool, str | None]:
    return store_upsert(
        f"overrides_{int(month)}", OVERRIDE_HEADER,
        {"ad": ad, REV_COLUMN: "", "json": json.dumps(fields, ensure_ascii=False)},
    )


def delete_override(month: int, ad: str) -> None:
    store_delete(f"overrides_{int(month)}", OVERRIDE_HEADER, ad)


def read_highlights(month: int) -> tuple[str, dict, str | None]:
    return _json_store_read(f"highlights_{int(month)}", HIGHLIGHT_HEADER)


def write_highlight(month: int, table_key: str, cells: list) -> tuple[bool, str | None]:
    return store_upsert(
        f"highlights_{int(month)}", HIGHLIGHT_HEADER,
        {"table_key": table_key, REV_COLUMN: "",
         "json": json.dumps(cells, ensure_ascii=False)},
    )


def delete_highlight(month: int, table_key: str) -> None:
    store_delete(f"highlights_{int(month)}", HIGHLIGHT_HEADER, table_key)


def read_locks() -> tuple[str, dict, str | None]:
    """(상태, {키: {owner, acquired_at, touched_at, rev}}, 실패 이유)."""
    read = store_read(LOCKS_TAB)
    if read.failed:
        return "error", {}, read.reason
    if not read.ok:
        return "empty", {}, None
    out: dict = {}
    for row in store_rows(read, LOCK_HEADER):
        record = dict(zip(LOCK_HEADER, row))
        out[record["key"]] = {
            "owner": record["owner"], "acquired_at": record["acquired_at"],
            "touched_at": record["touched_at"], "rev": _as_int(record[REV_COLUMN]),
        }
    return "ok", out, None


def write_lock(
    key: str, owner: str, acquired_at: str, touched_at: str,
    expected_rev: int | None = None,
) -> tuple[bool, str | None]:
    return store_upsert(
        LOCKS_TAB, LOCK_HEADER,
        {"key": key, REV_COLUMN: "", "owner": owner,
         "acquired_at": acquired_at, "touched_at": touched_at},
        expected_rev=expected_rev,
    )


def delete_lock(key: str) -> None:
    store_delete(LOCKS_TAB, LOCK_HEADER, key)


def ensure_block_rows_tab(month: int) -> None:
    """블록 행 탭과 헤더를 만들어 둔다(이미 있으면 아무것도 하지 않는다).

    빈 달에도 헤더만 놓아 두는 이유: 탭이 아예 없으면 매 리런마다 "옮겨올 예전 데이터가
    있나" 조회를 다시 타서 같은 비용을 계속 지불하게 된다.
    """
    service = _service()
    if block_rows_tab(month) in _existing_tabs(service):
        return
    _ensure_tab(service, block_rows_tab(month))
    service.spreadsheets().values().update(
        spreadsheetId=_sheet_id(), range=f"{block_rows_tab(month)}!A1",
        valueInputOption="RAW", body={"values": [BLOCK_HEADER]},
    ).execute()
