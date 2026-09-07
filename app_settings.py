"""대시보드 전역 설정 — 세션이 아니라 저장소에 남는다.

## 왜 필요한가 (2026-09-08)

`Media_RAW` 시트 링크가 사이드바 `st.text_input`에만 있었다. `st.session_state`는
**그 탭·그 세션 동안만** 산다 — 새로고침·재로그인·재배포마다 코드 상수
(`DEFAULT_SHEET`)로 돌아갔다. 규리님이 링크를 갈아끼워도 다음 리런에 사라져서
*"왜 자꾸 내가 고정해둔 걸로 안 쓰냐"*가 됐다.

⚠ 코드 주석에 "`key`가 있으니 값이 남는다"고 적혀 있었는데 **틀린 설명**이었다.
`key`는 한 세션 안에서만 값을 지킨다.

## 성격

이건 **전원이 공유하는 상태**다 — 광고주가 보는 화면의 데이터 원본을 정한다.
그래서 편집 권한이 있는 사람만 바꿀 수 있게 호출부에서 막고(`auth.can_edit`),
읽기는 누구나 한다. 월별이 아니라 **하나**다(지금 무엇을 보고 있는가).

과거 달의 기준은 여기가 아니라 **스냅샷**이 지킨다(`media_snapshot.frozen_settings`).

## 저장 위치

`overrides`와 같은 규칙: Firestore → 전용 구글시트 → 로컬 `notes/app_settings.json`.
읽기 실패와 "설정 없음"을 뭉개지 않는다 — 실패면 기본값을 **저장하지 않고** 넘긴다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import fs_store
import store

SETTINGS_PATH = Path(__file__).resolve().parent / "notes" / "app_settings.json"

#: 저장할 수 있는 키. 모르는 키는 버린다 — 저장소가 잡동사니가 되면 무엇이 쓰이는지
#: 알 수 없어진다.
KEYS = ("sheet_url", "google_folder")


def _clean(data) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in KEYS and str(v or "").strip()}


def _read_local() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return _clean(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_local(data: dict[str, str]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)


def load() -> dict[str, str]:
    """{키: 값}. 없거나 읽기가 실패하면 빈 dict."""
    if store.is_firestore():
        status, data, _reason = fs_store.read_app_settings()
        return _clean(data) if status != "error" else {}
    return _read_local()


def get(key: str, default: str = "") -> str:
    return load().get(key) or default


def save(key: str, value: str) -> tuple[bool, str | None]:
    """설정 하나를 바꾼다. **(성공 여부, 실패 사유)** 를 돌려준다.

    결과를 버리면 접속이 몰려 실패해도 화면은 저장된 것처럼 보인다
    (`overrides`에서 실제로 그렇게 유실됐다).
    """
    if key not in KEYS:
        return False, f"알 수 없는 설정: {key}"
    value = str(value or "").strip()
    if not value:
        return False, "빈 값은 저장하지 않습니다"

    if store.is_firestore():
        return fs_store.write_app_setting(key, value)
    data = _read_local()
    data[key] = value
    _write_local(data)
    return True, None
