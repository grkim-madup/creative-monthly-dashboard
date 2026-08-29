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
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import google.auth.transport.requests
import imageio_ffmpeg
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from google_sheets_readonly import get_credentials

# 광고주 공유 드라이브 — 모든 소재 영상 원본이 여기 소재명으로 검색 가능한 형태로 올라간다.
SHARED_DRIVE_ID = "0AH7dm5OxdfsNUk9PVA"

# 디스크 캐시 — 서버를 껐다 켜도 살아남는다(2026-08-28 도입).
#
#  * 파일 목록: 8,721개를 매번 API로 받으면 19초다(실측). 하루쯤 낡아도 실무상 문제가
#    없어 24시간 캐시한다. 새 소재가 안 잡히면 사이드바 '소재 목록 새로고침'이 지운다.
#  * 썸네일: 같은 Drive 파일이면 그림이 바뀔 일이 없으므로 기간 제한을 두지 않는다.
#    버튼으로도 지우지 않는다 — 누를 때마다 8개를 다시 받는 게 배보다 배꼽이 크다.
#
# 배포판은 재배포마다 파일시스템이 초기화돼 다시 받는다. 그건 정상이다.
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "drive"
FILE_LIST_CACHE = CACHE_DIR / "file_list.json"
THUMBNAIL_CACHE_DIR = CACHE_DIR / "thumbnails"
FILE_LIST_TTL_SECONDS = 24 * 60 * 60

# 썸네일 만드는 방식이 바뀌면 이 값을 올린다 — 예전 방식으로 만든 캐시가 섞이지 않게
# 폴더를 갈라 놓는다. v2 = Drive 자동 썸네일 우선(2026-08-28).
THUMBNAIL_CACHE_VERSION = "v2"


def _cache_age(path: Path) -> float | None:
    """파일이 만들어진 지 몇 초 됐는지. 없으면 None."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _atomic_write(path: Path, data: bytes) -> None:
    """쓰다 끊겨도 반쪽 파일이 남지 않게 tmp에 쓰고 바꿔치기한다."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        pass  # 캐시를 못 써도 동작 자체를 막지 않는다


def clear_file_list_cache() -> None:
    """파일 목록 캐시를 버린다. '소재 목록 새로고침'을 눌렀을 때만 부른다."""
    try:
        FILE_LIST_CACHE.unlink()
    except OSError:
        pass


def _thumbnail_path(file_id: str) -> Path:
    return THUMBNAIL_CACHE_DIR / THUMBNAIL_CACHE_VERSION / f"{file_id}.txt"


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


# 집행 데이터에서 규격이 `ALL`인 소재(여러 규격을 한 캠페인으로 묶어 돌린 것)는 Drive에
# 그 이름으로 올라가 있지 않다 — 실측(2026-08-25) 결과 Drive 8,577개 파일 중 `ALL` 토큰을
# 가진 파일은 0개였고, 원본 파일은 세로형(9X16) 이름으로 올라가 있었다. 그래서 `ALL`은
# `9X16`으로 바꿔 한 번 더 찾아본다(실측: 118개 중 0개 → 56개 매칭. `16X9`로 바꾸면 49개라
# 세로형이 더 잘 맞는다).
_DIMENSION_ALL = "all"
_DIMENSION_ALL_SUBSTITUTE = "9x16"


def _lookup_key(key: str, exact: dict[str, list[dict]],
                flat: list[tuple[str, dict]]) -> list[dict]:
    """정규화 키로 정확 매칭 → 접두사 폴백 순으로 찾는다."""
    if key in exact:
        return exact[key]
    return [
        f for candidate_key, f in flat
        if candidate_key.startswith(key)
        and (len(candidate_key) == len(key) or candidate_key[len(key)] in "-_")
    ]


def substitute_all_dimension(key: str) -> str | None:
    """정규화 키의 `all` 토큰을 `9x16`으로 바꾼다. 바꿀 게 없으면 None."""
    tokens = key.split("_")
    if _DIMENSION_ALL not in tokens:
        return None
    return "_".join(
        _DIMENSION_ALL_SUBSTITUTE if t == _DIMENSION_ALL else t for t in tokens
    )


def find_matches(ad_name: str, exact: dict[str, list[dict]], flat: list[tuple[str, dict]]) -> list[dict]:
    """소재명에 대응하는 Drive 파일들을 찾는다.

    1순위 정확 매칭, 없으면 접두사 폴백 — Drive 이름이 RAW 키로 시작하고 그다음 글자가
    `-`/`_` 구분자인 것만 인정한다(예: RAW `..._BEFOREAFTER` ↔ Drive `..._BEFOREAFTER-tt`,
    캐러셀 분할본 `..._TITLE1-vari-1.jpg`~`-8.jpg`). 이 구분자 체크가 없으면 `_1`이 `_10`,
    `_11`...에도 우연히 매칭되는 오탐이 난다.

    그래도 못 찾으면 마지막으로 규격 `ALL`을 `9X16`으로 바꿔 한 번 더 찾는다. 원래 이름으로
    찾은 결과가 있으면 그걸 그대로 쓰므로, 이 치환이 정상 매칭을 밀어내는 일은 없다.
    """
    key = normalize_name(ad_name)
    if key is None:
        return []

    matches = _lookup_key(key, exact, flat)
    if matches:
        return matches

    substituted = substitute_all_dimension(key)
    if substituted is not None:
        return _lookup_key(substituted, exact, flat)
    return []


def list_shared_drive_files(max_age_seconds: int = FILE_LIST_TTL_SECONDS) -> list[dict]:
    """공유 드라이브 전체 파일 목록. 디스크 캐시가 신선하면 그걸 쓴다(기본 24시간).

    API로 받으면 8,721개 기준 19초가 걸린다(2026-08-28 실측). 목록이 하루쯤 낡아도
    실무상 문제가 없다 — 새 소재가 안 잡히면 '소재 목록 새로고침'으로 해소한다.
    """
    age = _cache_age(FILE_LIST_CACHE)
    if age is not None and age < max_age_seconds:
        try:
            cached = json.loads(FILE_LIST_CACHE.read_text(encoding="utf-8"))
            if isinstance(cached, list) and cached:
                return cached
        except (OSError, ValueError):
            pass  # 깨진 캐시는 무시하고 새로 받는다

    files = _fetch_shared_drive_files()
    if files:
        _atomic_write(FILE_LIST_CACHE, json.dumps(files, ensure_ascii=False).encode("utf-8"))
    return files


def _fetch_shared_drive_files() -> list[dict]:
    """실제 Drive API 호출(약 9번의 페이지 요청, 19초)."""
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
        credentials = get_credentials()
        credentials.refresh(google.auth.transport.requests.Request())
        request = urllib.request.Request(
            thumbnail_link,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Authorization": f"Bearer {credentials.token}",
            },
        )
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

# 소재 하나당(=Drive 파일 id당) 뽑아둔 썸네일을 프로세스 안에 들고 있는다.
#
# 왜 필요한가: 예전에는 Streamlit 쪽에서 "한 표의 하이라이트 4개 묶음" 전체를 캐시 키로
# 썼다. 그러면 정렬 기준이나 표시 개수를 바꿔 **4개 중 1개만 달라져도 키가 달라져서 4개를
# 전부 다시 뽑았다**(실측 사용자 피드백: 기준 바꿀 때마다 오래 걸림). 뽑는 비용은 소재
# 단위인데 캐시는 묶음 단위였던 게 원인이라, 캐시 단위를 소재로 내린다.
#
# 실패(빈 문자열)는 담지 않는다 — 일시적인 네트워크 오류를 영구히 굳혀버리면 그 카드가
# 세션 내내 썸네일 없이 남는다.
_THUMBNAIL_CACHE: dict[str, str] = {}
_THUMBNAIL_CACHE_LOCK = threading.Lock()
# 한 세션에서 여러 달·여러 정렬을 오래 만지면 계속 쌓이므로 상한을 둔다(오래된 것부터 버림).
# 항목당 수십 KB 수준이라 256개면 십수 MB 안쪽이다.
_THUMBNAIL_CACHE_MAX = 256


def thumbnail_cache_stats() -> dict[str, int]:
    """캐시 상태(항목 수/상한). 진단용 — 동작에는 영향이 없다."""
    with _THUMBNAIL_CACHE_LOCK:
        return {"size": len(_THUMBNAIL_CACHE), "max": _THUMBNAIL_CACHE_MAX}


def has_thumbnail(file_id: str) -> bool:
    """이미 뽑아둔 썸네일이 있는지. 스피너에 '몇 개 새로 받는지' 띄우는 데 쓴다."""
    return _cache_get(file_id) is not None


def clear_thumbnail_cache() -> None:
    """메모리와 디스크 캐시를 모두 비운다. 강제 갱신이 필요할 때만 부른다.

    사이드바 버튼은 이걸 부르지 않는다 — 누를 때마다 8개를 다시 받는 비용이 크고,
    같은 파일의 썸네일이 낡을 일도 사실상 없기 때문이다(2026-08-28 결정).
    """
    with _THUMBNAIL_CACHE_LOCK:
        _THUMBNAIL_CACHE.clear()
    directory = THUMBNAIL_CACHE_DIR / THUMBNAIL_CACHE_VERSION
    try:
        for path in directory.glob("*.txt"):
            path.unlink()
    except OSError:
        pass


def _cache_get(file_id: str) -> str | None:
    """메모리 → 디스크 순으로 찾는다. 디스크에서 찾으면 메모리로 끌어올린다."""
    with _THUMBNAIL_CACHE_LOCK:
        cached = _THUMBNAIL_CACHE.get(file_id)
    if cached is not None:
        return cached
    try:
        uri = _thumbnail_path(file_id).read_text(encoding="utf-8")
    except OSError:
        return None
    if not uri:
        return None
    with _THUMBNAIL_CACHE_LOCK:
        _THUMBNAIL_CACHE[file_id] = uri
    return uri


def _cache_put(file_id: str, uri: str) -> None:
    """메모리와 디스크 양쪽에 담는다. 실패(빈 문자열)는 담지 않는다.

    디스크에 남기면 서버를 껐다 켜도 다시 뽑지 않는다 — 같은 Drive 파일이면 그림이
    바뀔 일이 없어 기간 제한도 두지 않는다.
    """
    if not uri:
        return
    with _THUMBNAIL_CACHE_LOCK:
        _THUMBNAIL_CACHE[file_id] = uri
        while len(_THUMBNAIL_CACHE) > _THUMBNAIL_CACHE_MAX:
            _THUMBNAIL_CACHE.pop(next(iter(_THUMBNAIL_CACHE)))
    _atomic_write(_thumbnail_path(file_id), uri.encode("utf-8"))


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
    """카드용 썸네일 하나를 정한다 — Drive 자동 썸네일 우선, 없으면 첫 프레임 추출.

    2026-08-28에 순서를 뒤집었다. 첫 프레임 추출은 영상을 내려받아 디코딩해야 해서
    개당 약 5.4초가 들고, 필터를 한 번 바꿀 때마다 8개를 다시 뽑아 43초가 걸렸다.
    Drive가 이미 만들어 둔 썸네일을 쓰면 같은 8개가 7.7초다(실측).

    대가: 자동 썸네일은 Drive가 임의로 고른 대표 프레임이라 재생 시작 화면과 다를 수
    있다. 속도를 택한 결정이다(사용자 확인). 자동 썸네일이 없는 파일(8,721개 중 116개,
    1.3%)은 종전대로 첫 프레임을 뽑는다.
    """
    uri = fetch_default_thumbnail_data_uri(file.get("thumbnailLink", ""))
    if uri:
        return uri
    return extract_first_frame_data_uri(file.get("id", ""), file.get("name", ""))


def material_thumbnails(specs: list[tuple[str, str, str]]) -> dict[str, str]:
    """여러 소재의 썸네일을 병렬로 만든다.

    specs: [(file_id, file_name, thumbnail_link)] — 결과는 {file_id: data URI}.
    한 건이 실패해도 나머지는 그대로 살린다(그 카드만 썸네일 없이 렌더된다).
    """
    if not specs:
        return {}

    # 이미 뽑아둔 건 그대로 쓰고, 없는 것만 받는다 — 정렬 기준을 바꿔 소재 한둘만
    # 갈렸을 때 나머지를 다시 뽑지 않게 하는 것이 이 함수의 핵심이다.
    result: dict[str, str] = {}
    pending: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for spec in specs:
        file_id = spec[0]
        if file_id in seen:
            continue
        seen.add(file_id)
        cached = _cache_get(file_id)
        if cached is not None:
            result[file_id] = cached
        else:
            pending.append(spec)

    if not pending:
        return result

    def one(spec: tuple[str, str, str]) -> tuple[str, str]:
        file_id, file_name, thumbnail_link = spec
        try:
            uri = material_thumbnail_data_uri(
                {"id": file_id, "name": file_name, "thumbnailLink": thumbnail_link}
            )
        except Exception:  # noqa: BLE001 - 한 건 실패가 전체를 막지 않는다
            uri = ""
        return file_id, uri

    workers = min(_MAX_PARALLEL_THUMBNAILS, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for file_id, uri in pool.map(one, pending):
            _cache_put(file_id, uri)
            result[file_id] = uri
    return result
