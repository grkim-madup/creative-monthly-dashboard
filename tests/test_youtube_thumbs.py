"""YouTube 썸네일 비율 판별 — 세로 소재가 작게 보이던 문제의 핵심 로직.

구글 보고서의 '방향' 컬럼은 iOS에 아예 없어서(실측 55건 전부 비어 있음) 믿을 수 없다.
그래서 원본 비율 썸네일을 실제로 받아 크기를 읽는다.
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import youtube_thumbs as yt  # noqa: E402


def make_jpeg(width: int, height: int) -> bytes:
    """SOF0 마커만 갖춘 최소 JPEG 바이트."""
    return (
        b"\xff\xd8"
        + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
        + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9
    )


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """실제 .cache를 건드리지 않는다."""
    monkeypatch.setattr(yt, "CACHE_PATH", tmp_path / "yt_shape.json")
    monkeypatch.setattr(yt, "_cache", None, raising=False)
    yield
    monkeypatch.setattr(yt, "_cache", None, raising=False)


def test_jpeg_size_reads_dimensions():
    assert yt.jpeg_size(make_jpeg(1080, 1920)) == (1080, 1920)
    assert yt.jpeg_size(make_jpeg(480, 360)) == (480, 360)


@pytest.mark.parametrize("data", [b"", b"not a jpeg", b"\xff\xd8"])
def test_jpeg_size_returns_none_for_garbage(data):
    assert yt.jpeg_size(data) is None


def test_video_id_from_every_url_shape():
    for url in ("https://www.youtube.com/watch?v=6FLWVG_5Ewc",
                "https://youtu.be/6FLWVG_5Ewc",
                "https://www.youtube.com/embed/6FLWVG_5Ewc",
                "https://www.youtube.com/shorts/6FLWVG_5Ewc"):
        assert yt.video_id(url) == "6FLWVG_5Ewc"
    assert yt.video_id("광고 제목입니다") == ""


def test_vertical_video_fills_the_card(monkeypatch):
    monkeypatch.setattr(yt, "_fetch_size", lambda vid: [1080, 1920])
    url = "https://www.youtube.com/watch?v=6FLWVG_5Ewc"
    yt.prefetch([url])
    assert yt.resolve(url) == ("https://i.ytimg.com/vi/6FLWVG_5Ewc/oardefault.jpg", True)


def test_landscape_video_keeps_its_ratio(monkeypatch):
    monkeypatch.setattr(yt, "_fetch_size", lambda vid: [1920, 1080])
    url = "https://www.youtube.com/watch?v=6FLWVG_5Ewc"
    yt.prefetch([url])
    assert yt.resolve(url) == ("https://i.ytimg.com/vi/6FLWVG_5Ewc/hqdefault.jpg", False)


def test_missing_original_thumbnail_falls_back(monkeypatch):
    """원본 비율 썸네일이 없는 영상 — 그대로 쓰면 회색 빈 이미지가 뜬다."""
    monkeypatch.setattr(yt, "_fetch_size", lambda vid: None)
    url = "https://www.youtube.com/watch?v=6FLWVG_5Ewc"
    yt.prefetch([url])
    assert yt.resolve(url) == ("https://i.ytimg.com/vi/6FLWVG_5Ewc/hqdefault.jpg", False)


def test_unprobed_video_is_treated_as_landscape(monkeypatch):
    """확인 전에는 안전한 쪽(비율 유지)으로 둔다 — 잘라내서 그림을 망치지 않는다."""
    url = "https://www.youtube.com/watch?v=NEVERPROBED"
    assert yt.resolve(url) == ("https://i.ytimg.com/vi/NEVERPROBED/hqdefault.jpg", False)


def test_image_asset_url_is_used_as_is():
    url = "https://tpc.googlesyndication.com/simgad/123"
    assert yt.resolve(url) == (url, False)


def test_text_asset_has_no_thumbnail():
    assert yt.resolve("광고 제목입니다") == ("", False)
    assert yt.resolve("") == ("", False)


def test_probe_result_is_cached_on_disk(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(yt, "_fetch_size", lambda vid: calls.append(vid) or [1080, 1920])
    url = "https://www.youtube.com/watch?v=6FLWVG_5Ewc"
    yt.prefetch([url])
    yt.prefetch([url])  # 두 번째는 네트워크를 타지 않는다
    assert calls == ["6FLWVG_5Ewc"]
    assert yt.CACHE_PATH.exists()
