"""어느 저장소를 쓸지 고르는 스위치 하나.

`STORAGE_BACKEND` 시크릿이 `firestore`면 Firestore, 아니면(기본) 구글 시트다.
기본값을 시트로 두는 이유: 컷오버 전까지 운영 동작이 한 줄도 바뀌지 않아야 하고,
문제가 생기면 시크릿 하나만 되돌려 2분 안에 복귀할 수 있어야 한다.

**첨부 이미지는 이 스위치와 무관하게 항상 시트에 남는다.** Cloud Storage가 결제 계정을
요구해서 이번 이전 범위에서 뺐다(2026-08-30 결정). 이미지는 월 1~2장이라 경합이 거의
없고, 지금 코드가 잘 돌고 있다. 나중에 결제 계정이 붙으면 그때 옮긴다.
"""

from __future__ import annotations

import datetime as dt

SHEETS = "sheets"
FIRESTORE = "firestore"


def backend() -> str:
    """지금 쓸 저장소 이름. 알 수 없는 값이면 안전한 쪽(시트)으로 떨어진다."""
    # 순환 import를 피하려고 함수 안에서 읽는다(google_sheets_writer가 store를 쓸 수 있다).
    import google_sheets_writer

    value = str(google_sheets_writer._secret("STORAGE_BACKEND") or SHEETS).strip().lower()
    return FIRESTORE if value == FIRESTORE else SHEETS


def is_firestore() -> bool:
    return backend() == FIRESTORE


#: 한국 표준시. 배포 컨테이너(python:3.12-slim)에는 시간대 설정이 없어 서버 시각이
#: UTC다. `datetime.now()`를 그대로 쓰면 **광고주에게 보이는 시각이 9시간 어긋난다**
#: (2026-09-02 확인 — 사이드바 "마지막 동기화"가 하루 전으로 보였다).
#: 한국은 서머타임이 없어 고정 +9 오프셋이 정확하다. slim 이미지에 tzdata가 없을 수
#: 있어 zoneinfo 대신 이 방식을 쓴다.
KST = dt.timezone(dt.timedelta(hours=9))


def report_timestamp() -> str:
    """리포트 화면에 보이는 시각(스냅샷 고정 시각 등). 저장소 백엔드와 무관하게 항상 KST."""
    return dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
