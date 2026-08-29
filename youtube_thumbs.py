"""YouTube 소재 썸네일의 실제 비율을 확인해, 카드에 쓸 주소와 표시 방식을 정한다.

왜 필요한가(2026-08-29):
- 기본 썸네일(`hqdefault`)은 영상 비율과 무관하게 항상 16:9다. 세로 소재는 좌우가 배경
  으로 채워져 정작 그림이 작게 보인다.
- 원본 비율 썸네일(`oardefault`)은 진짜 비율을 준다(실측: 1080×1920, 886×1920). 다만
  **모든 영상에 있지는 않다** — 없는 영상은 404이고, 그걸 그냥 쓰면 회색 빈 이미지가 뜬다.
- 구글 보고서의 `방향` 컬럼으로 가르려 했지만 **iOS 보고서에는 그 컬럼이 아예 없다**
  (실측: iOS 55건 전부 비어 있고, 그중 상당수가 실제로는 세로 소재였다).

그래서 방향을 추측하지 않고 **원본 비율 썸네일을 실제로 받아 크기를 읽는다.** 세로면
카드를 꽉 채우고, 없거나 가로면 기본 썸네일을 비율 그대로 보여준다.

받은 결과는 디스크에 남긴다 — 같은 영상의 비율은 바뀌지 않으므로 한 번만 확인하면 된다.
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "drive" / "yt_shape.json"

# JPEG 헤더는 파일 앞부분에 있다. 전체(수백 KB)를 받을 필요가 없다.
_PROBE_BYTES = 64 * 1024
_MAX_WORKERS = 8

_YOUTUBE_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/embed/|/shorts/)([\w-]{6,})")

_lock = threading.Lock()
_cache: dict[str, list | None] | None = None


def video_id(asset: str) -> str:
    """소재 URL에서 YouTube 영상 ID. 유튜브가 아니면 빈 문자열."""
    match = _YOUTUBE_ID.search(str(asset or ""))
    return match.group(1) if match else ""


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """JPEG 바이트에서 (가로, 세로)를 읽는다. 못 읽으면 None. 순수 함수 — pytest 대상.

    외부 라이브러리를 쓰지 않는다. 이 하나를 위해 Pillow를 배포에 얹을 이유가 없다.
    """
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    index = 2
    while index < len(data) - 9:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        # SOF0~SOF15 중 크기를 담는 마커들(재시작·인코딩 전용 마커는 제외)
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB,
                      0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        try:
            index += 2 + struct.unpack(">H", data[index + 2:index + 4])[0]
        except struct.error:
            return None
    return None


def _load_cache() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    loaded: dict = {}
    try:
        loaded = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        loaded = {}
    with _lock:
        _cache = loaded if isinstance(loaded, dict) else {}
        return _cache


def _save_cache() -> None:
    with _lock:
        snapshot = dict(_cache or {})
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass  # 캐시를 못 써도 동작 자체는 막지 않는다


def _fetch_size(vid: str) -> list | None:
    """원본 비율 썸네일의 크기. 그 썸네일이 없으면 None."""
    url = f"https://i.ytimg.com/vi/{vid}/oardefault.jpg"
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{_PROBE_BYTES - 1}"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            size = jpeg_size(response.read())
    except Exception:  # noqa: BLE001 - 없는 썸네일(404)도 여기로 온다
        return None
    return list(size) if size else None


def prefetch(assets: list[str]) -> None:
    """여러 소재의 비율을 한 번에 확인해 캐시에 채운다(카드 4장이면 4건 병렬)."""
    cache = _load_cache()
    pending = []
    seen = set()
    for asset in assets:
        vid = video_id(asset)
        if vid and vid not in cache and vid not in seen:
            seen.add(vid)
            pending.append(vid)
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(pending))) as pool:
        sizes = list(pool.map(_fetch_size, pending))
    with _lock:
        for vid, size in zip(pending, sizes):
            (_cache if _cache is not None else cache)[vid] = size
    _save_cache()


def resolve(asset: str) -> tuple[str, bool]:
    """카드에 쓸 (썸네일 주소, 꽉 채울지 여부).

    - 세로 영상: 원본 비율 썸네일 + 꽉 채우기(좌우 배경 띠가 없으니 잘릴 것도 없다)
    - 가로 영상·원본 비율 썸네일이 없는 영상: 기본 16:9 + 비율 그대로
    - 유튜브가 아닌 이미지 애셋: 주소가 곧 그림이고, 비율 그대로 둔다
    """
    text = str(asset or "").strip()
    if not text.startswith("http"):
        return "", False
    vid = video_id(text)
    if not vid:
        return text, False  # 이미지 애셋
    size = _load_cache().get(vid)
    if size and len(size) == 2 and size[1] > size[0]:
        return f"https://i.ytimg.com/vi/{vid}/oardefault.jpg", True
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", False
