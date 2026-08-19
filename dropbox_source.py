"""구글 애셋 보고서 폴더를 로컬 드롭박스 동기화 대신 Dropbox API로 직접 내려받는다.

배포 서버에는 이 PC의 드롭박스 동기화 폴더(`DEFAULT_GOOGLE_FOLDER`)가 없다. 공개/무제한 공유
링크는 광고주 성과 데이터를 인증 없이 노출하는 것이라 조직 보안 원칙과 맞지 않으므로, 대신
**scope가 좁은 Dropbox 앱 + refresh token**으로 팀 폴더 파일만 읽어온다(쓰기 권한 없음).

자격증명은 코드에 절대 넣지 않는다 — `st.secrets`(배포 시 Streamlit Cloud의 Secrets 설정) 또는
환경변수로만 받는다. 셋 중 하나라도 없으면 `configured()`가 False를 반환하고, 호출부는 이 PC의
로컬 드롭박스 동기화 경로로 그대로 폴백한다(기존 동작 유지).

최초 1회 설정: `dropbox_get_refresh_token.py` 참고.
"""

from __future__ import annotations

import os
from pathlib import Path

import dropbox
from dropbox.common import PathRoot

CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "google_ads_dropbox"

_KEYS = ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN", "DROPBOX_FOLDER_PATH")


def _secret(name: str) -> str | None:
    """Streamlit secrets 우선, 없으면 환경변수. streamlit 미설치/미설정이면 조용히 건너뛴다."""
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name)


def _config() -> dict[str, str] | None:
    values = {key: _secret(key) for key in _KEYS}
    if not all(values.values()):
        return None
    return values


def configured() -> bool:
    """Dropbox API 자격증명이 갖춰져 있으면 True (로컬 개발 PC는 보통 False)."""
    return _config() is not None


def sync_google_folder(dest_dir: Path | str = CACHE_DIR) -> Path:
    """설정된 Dropbox 폴더의 CSV를 전부 `dest_dir`에 내려받고 그 경로를 반환한다.

    폴더 구조(하위 폴더 포함)를 그대로 복제한다 — `google_ads_report.py`가
    폴더명(AOS/iOS, ACa/ACi)에서 메타데이터를 유도하기 때문에 구조 보존이 필수다.
    매번 전체를 새로 받는다(수십~수백 KB대 CSV 43개 수준이라 증분 동기화가 필요 없다).
    """
    config = _config()
    if config is None:
        raise RuntimeError(
            "Dropbox 자격증명이 설정되지 않았습니다 "
            "(DROPBOX_APP_KEY/DROPBOX_APP_SECRET/DROPBOX_REFRESH_TOKEN/DROPBOX_FOLDER_PATH)."
        )

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    client = dropbox.Dropbox(
        oauth2_refresh_token=config["DROPBOX_REFRESH_TOKEN"],
        app_key=config["DROPBOX_APP_KEY"],
        app_secret=config["DROPBOX_APP_SECRET"],
    )
    # 매드업은 Dropbox Business 팀 계정이라 "광고사업부" 폴더는 로그인한 사람의 개인
    # 홈 네임스페이스가 아니라 팀 스페이스 루트에 있다(개인 홈은 팀 스페이스 안의
    # "<이름>" 폴더 하나일 뿐). 기본 클라이언트는 홈 네임스페이스를 봐서 경로를 못 찾으므로,
    # 계정의 root_namespace_id로 경로 기준을 바꿔야 한다. 개인(non-team) 계정은 두 값이
    # 같아서 이 처리를 해도 동작이 그대로다.
    root_namespace_id = client.users_get_current_account().root_info.root_namespace_id
    client = client.with_path_root(PathRoot.root(root_namespace_id))
    root = config["DROPBOX_FOLDER_PATH"].rstrip("/")

    downloaded = 0
    result = client.files_list_folder(root, recursive=True)
    while True:
        for entry in result.entries:
            if not isinstance(entry, dropbox.files.FileMetadata):
                continue
            if not entry.path_lower.endswith(".csv"):
                continue
            relative = entry.path_display[len(root) :].lstrip("/")
            local_path = dest / relative
            local_path.parent.mkdir(parents=True, exist_ok=True)
            client.files_download_to_file(str(local_path), entry.path_lower)
            downloaded += 1
        if not result.has_more:
            break
        result = client.files_list_folder_continue(result.cursor)

    if downloaded == 0:
        raise RuntimeError(f"Dropbox 폴더에서 CSV를 하나도 받지 못했습니다: {root}")

    return dest
