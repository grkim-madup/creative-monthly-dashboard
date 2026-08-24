"""메타/틱톡 TOP 소재의 우수·저조 하이라이트 소재를 광고주 공유 드라이브의 실제 영상과 잇는다.

배경: RAW의 소재명(`ad`)과 Drive 파일명은 **작품명 토큰이 다르다** — RAW는 영문 코드네임
(`mercenarysoldier`), Drive는 실제 중국어 작품명(`誤打誤撞成為怪物天才演員`)을 쓴다. 그래서
소재명 전체 문자열 비교로는 절대 매칭이 안 되고, **작품번호·포맷·제작주체·유형·규격·USP 등
작품명을 제외한 나머지 토큰**으로 맞춰야 한다(2026-08-24 실측: 하이라이트 8건 기준 8/8 매칭,
전체 VID 기준 81% — 나머지는 Madup 자체 제작본이 광고주 드라이브에 없거나 구형 네이밍이라
이 폴백으로도 못 잡는 소수 사례).

인증: Media_RAW 읽기용 OAuth 토큰(`google_sheets_readonly.get_credentials`)을 그대로 쓴다 —
이 폴더가 광고주 소유 공유 드라이브라 서비스 계정을 공유받을 권한이 없고(계정 관리자만 가능),
대신 이 대시보드를 쓰는 사람 본인 계정에는 이미 Drive 접근 권한이 있다. 토큰에 `drive` 스코프가
이미 포함돼 있어 별도 재인증 없이 동작한다(2026-08-24 확인).

폴더 자체가 8,576개 파일(2026-08 기준)이라 매번 전체 나열하는 대신 1시간 캐시로 재사용한다.
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import google.auth.transport.requests
import imageio_ffmpeg
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from google_sheets_readonly import get_credentials

# 광고주 공유 드라이브 — 모든 소재 영상 원본이 여기 소재명으로 검색 가능한 형태로 올라간다.
SHARED_DRIVE_ID = "0AH7dm5OxdfsNUk9PVA"

_VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif")
_KNOWN_EXTENSIONS = _VIDEO_EXTENSIONS + _IMAGE_EXTENSIONS


def _strip_extension(name: str) -> str:
    lowered = name.lower()
    for ext in _KNOWN_EXTENSIONS:
        if lowered.endswith(ext):
            return name[: -len(ext)]
    return name


def normalize_name(name: str) -> str | None:
    """소재명/파일명에서 작품명 토큰(두 번째, `_` 구분)만 빼고 소문자로 합친 매칭 키를 만든다.

    `{작품번호}_{작품명}_{포맷}_{제작주체}_...` 구조를 전제한다 — 토큰이 3개 미만이면
    이 컨벤션을 안 따르는 이름이라 매칭 대상에서 제외한다(None).
    """
    tokens = _strip_extension(str(name)).split("_")
    if len(tokens) < 3:
        return None
    return "_".join(token.lower() for i, token in enumerate(tokens) if i != 1)


def build_index(files: list[dict]) -> tuple[dict[str, list[dict]], list[tuple[str, dict]]]:
    """파일 목록에서 {정규화키: [파일...]} 색인과, 접두사 폴백용 (키, 파일) 평탄 목록을 만든다."""
    exact: dict[str, list[dict]] = {}
    flat: list[tuple[str, dict]] = []
    for f in files:
        key = normalize_name(f["name"])
        if key is None:
            continue
        exact.setdefault(key, []).append(f)
        flat.append((key, f))
    return exact, flat


def find_matches(ad_name: str, exact: dict[str, list[dict]], flat: list[tuple[str, dict]]) -> list[dict]:
    """소재명에 대응하는 Drive 파일들을 찾는다.

    1순위 정확 매칭, 없으면 접두사 폴백 — Drive 이름이 RAW 키로 시작하고 그다음 글자가
    `-`/`_` 구분자인 것만 인정한다(예: RAW `..._BEFOREAFTER` ↔ Drive `..._BEFOREAFTER-tt`,
    캐러셀 분할본 `..._TITLE1-vari-1.jpg`~`-8.jpg`). 이 구분자 체크가 없으면 `_1`이 `_10`,
    `_11`...에도 우연히 매칭되는 오탐이 난다.
    """
    key = normalize_name(ad_name)
    if key is None:
        return []
    if key in exact:
        return exact[key]
    return [
        f for candidate_key, f in flat
        if candidate_key.startswith(key)
        and (len(candidate_key) == len(key) or candidate_key[len(key)] in "-_")
    ]


def list_shared_drive_files() -> list[dict]:
    """공유 드라이브의 전체 파일 목록(폴더 제외)을 가져온다. 약 9번의 API 호출, 수 초 소요."""
    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)

    files: list[dict] = []
    page_token = None
    while True:
        response = service.files().list(
            corpora="drive", driveId=SHARED_DRIVE_ID,
            includeItemsFromAllDrives=True, supportsAllDrives=True,
            q="trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            fields="files(id,name,mimeType,thumbnailLink,webViewLink),nextPageToken",
            pageSize=1000, pageToken=page_token,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def fetch_default_thumbnail_data_uri(thumbnail_link: str) -> str:
    """Drive가 자동 생성한 thumbnailLink를 내려받아 data URI로 바꾼다.

    Drive의 기본 썸네일은 영상 중간의 대표 프레임을 임의로 골라주는 것이라, 실제 재생
    시작 화면과 다를 때가 많다 — `extract_first_frame_data_uri`가 실패했을 때만 쓰는
    폴백이다. 이 URL 자체는 시간이 지나면 만료되므로 화면에 그대로 박아두지 않고, 매번
    새로 받은 뒤 바이트를 직접 심는다(next_step.py의 첨부 이미지와 같은 방식).
    """
    if not thumbnail_link:
        return ""
    try:
        request = urllib.request.Request(thumbnail_link, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read()
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()
    except Exception:  # noqa: BLE001 - 썸네일 하나 실패했다고 카드 전체를 죽이지 않는다
        return ""


# 첫 프레임만 필요하니 파일 앞부분만 받아본다. 실측(2026-08-24, 34~53MB 영상 3개)에서 앞 1MB로
# 뽑은 JPG가 전체를 받아 뽑은 것과 **바이트 단위로 동일**했고, 개당 6~7초 → 3~4초로 줄었다.
# moov atom이 뒤에 있는(faststart 아닌) 파일은 이걸로 디코딩이 안 되므로 전체 다운로드로 폴백한다.
_PARTIAL_PROBE_BYTES = 1024 * 1024

# 카드가 4~8개씩 붙어서, 순차로 돌리면 지연(latency)이 그대로 누적된다. 실측에서 4개 병렬이
# 49초 → 16초로 줄었다. 광고주 Drive에 부담을 주지 않는 선으로 동시 실행 수를 묶어둔다.
_MAX_PARALLEL_THUMBNAILS = 8


def _frame_from_video_bytes(data: bytes, suffix: str) -> str:
    """영상 바이트에서 첫 프레임을 뽑아 data URI로 만든다. 못 뽑으면 빈 문자열."""
    video_path = frame_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as video_file:
            video_file.write(data)
            video_path = video_file.name
        frame_path = video_path + ".jpg"

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_exe, "-y", "-i", video_path, "-vframes", "1", "-q:v", "2", frame_path],
            capture_output=True, timeout=60,
        )
        if result.returncode != 0 or not os.path.exists(frame_path):
            return ""
        if os.path.getsize(frame_path) == 0:
            return ""

        with open(frame_path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except Exception:  # noqa: BLE001 - 폴백 경로가 있으니 여기서 죽이지 않는다
        return ""
    finally:
        for path in (video_path, frame_path):
            if path and os.path.exists(path):
                os.remove(path)


def extract_first_frame_data_uri(file_id: str, file_name: str = "") -> str:
    """영상의 재생 시작 지점(첫 프레임)을 뽑아 data URI로 돌려준다.

    Drive의 자동 썸네일은 대표 프레임을 임의로 골라서 실제 재생 화면과 다를 수 있다는
    피드백을 받아 도입했다. `imageio-ffmpeg`가 받아오는 정적 ffmpeg 바이너리를 쓰므로
    시스템에 ffmpeg를 따로 설치할 필요가 없다(배포판도 pip 설치만으로 동일하게 동작).

    먼저 앞부분만 받아 시도하고(대부분 성공), 안 되면 전체를 받는다. 실패하면 빈 문자열을
    돌려주고 호출부가 Drive 기본 썸네일로 폴백한다.
    """
    if not file_id:
        return ""
    suffix = os.path.splitext(file_name)[1] or ".mp4"
    try:
        creds = get_credentials()

        session = google.auth.transport.requests.AuthorizedSession(creds)
        url = (f"https://www.googleapis.com/drive/v3/files/{file_id}"
               "?alt=media&supportsAllDrives=true")
        response = session.get(
            url, headers={"Range": f"bytes=0-{_PARTIAL_PROBE_BYTES - 1}"}, timeout=60
        )
        if response.status_code in (200, 206):
            uri = _frame_from_video_bytes(response.content, suffix)
            if uri:
                return uri

        # 앞부분만으로는 디코딩이 안 되는 컨테이너 — 통째로 받아 다시 시도한다.
        service = build("drive", "v3", credentials=creds)
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return _frame_from_video_bytes(buffer.getvalue(), suffix)
    except Exception:  # noqa: BLE001 - 실패하면 기본 썸네일로 폴백한다
        return ""


def material_thumbnail_data_uri(file: dict) -> str:
    """카드용 썸네일 하나를 정한다 — 첫 프레임 추출을 우선하고, 실패하면 기본 썸네일."""
    uri = extract_first_frame_data_uri(file.get("id", ""), file.get("name", ""))
    if uri:
        return uri
    return fetch_default_thumbnail_data_uri(file.get("thumbnailLink", ""))


def material_thumbnails(specs: list[tuple[str, str, str]]) -> dict[str, str]:
    """여러 소재의 썸네일을 병렬로 만든다.

    specs: [(file_id, file_name, thumbnail_link)] — 결과는 {file_id: data URI}.
    한 건이 실패해도 나머지는 그대로 살린다(그 카드만 썸네일 없이 렌더된다).
    """
    if not specs:
        return {}

    def one(spec: tuple[str, str, str]) -> tuple[str, str]:
        file_id, file_name, thumbnail_link = spec
        try:
            uri = material_thumbnail_data_uri(
                {"id": file_id, "name": file_name, "thumbnailLink": thumbnail_link}
            )
        except Exception:  # noqa: BLE001 - 한 건 실패가 전체를 막지 않는다
            uri = ""
        return file_id, uri

    workers = min(_MAX_PARALLEL_THUMBNAILS, len(specs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, specs))
