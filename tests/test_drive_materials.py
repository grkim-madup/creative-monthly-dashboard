import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drive_materials as dm  # noqa: E402


def test_normalize_drops_the_title_token():
    """RAW와 Drive는 작품명 토큰만 다르다 — 그걸 빼면 같은 키가 나와야 한다."""
    raw = "9622_不良少年的初戀_VID_Madup_Visual_9X16_BEFOREAFTER"
    drive = "9622_不良少年的初戀_VID_Madup_Visual_9X16_BEFOREAFTER"
    assert dm.normalize_name(raw) == dm.normalize_name(drive)

    raw_en = "2416_mercenarysoldier_VID_Webtoon_Trailer_9x16_1"
    drive_cn = "2416_誤打誤撞成為怪物天才演員_VID_Webtoon_Trailer_9x16_1"
    assert dm.normalize_name(raw_en) == dm.normalize_name(drive_cn)


def test_normalize_is_case_insensitive_and_strips_extension():
    assert dm.normalize_name("1_TITLE_VID_A_B_1X1_C.mp4") == dm.normalize_name(
        "1_title_vid_a_b_1x1_c"
    )


def test_normalize_rejects_names_with_too_few_tokens():
    assert dm.normalize_name("just_two") is None
    assert dm.normalize_name("") is None


def test_build_index_groups_by_normalized_key():
    files = [
        {"id": "a", "name": "1_TitleA_VID_X_Y_1X1_Z"},
        {"id": "b", "name": "1_TitleB_VID_X_Y_1X1_Z"},  # 작품명만 다름 — 같은 키
        {"id": "c", "name": "2_TitleC_VID_X_Y_1X1_Z"},
    ]
    exact, flat = dm.build_index(files)
    key = dm.normalize_name(files[0]["name"])
    assert {f["id"] for f in exact[key]} == {"a", "b"}
    assert len(flat) == 3


def test_build_index_skips_unmatchable_names():
    files = [{"id": "a", "name": "two_tokens"}]
    exact, flat = dm.build_index(files)
    assert exact == {}
    assert flat == []


def test_find_matches_exact_hit():
    files = [{"id": "a", "name": "1_TitleA_VID_X_Y_1X1_Z"}]
    exact, flat = dm.build_index(files)
    result = dm.find_matches("1_TitleB_VID_X_Y_1X1_Z", exact, flat)
    assert [f["id"] for f in result] == ["a"]


def test_find_matches_returns_empty_when_nothing_fits():
    files = [{"id": "a", "name": "1_TitleA_VID_X_Y_1X1_Z"}]
    exact, flat = dm.build_index(files)
    assert dm.find_matches("9_Other_VID_X_Y_1X1_Z", exact, flat) == []


def test_find_matches_prefix_fallback_for_suffix_variants():
    """RAW '..._BEFOREAFTER' ↔ Drive '..._BEFOREAFTER-tt' 같은 실제 접미사 차이를 잡는다."""
    files = [{"id": "a", "name": "9622_TitleA_VID_Madup_Visual_9X16_BEFOREAFTER-tt"}]
    exact, flat = dm.build_index(files)
    result = dm.find_matches("9622_TitleB_VID_Madup_Visual_9X16_BEFOREAFTER", exact, flat)
    assert [f["id"] for f in result] == ["a"]


def test_find_matches_prefix_fallback_for_carousel_splits():
    """캐러셀 8분할본(TITLE1-vari-1.jpg ~ -8.jpg)을 전부 후보로 잡아야 한다."""
    files = [
        {"id": f"img{i}", "name": f"2401_TitleA_IMG_Madup_Carousel_4X5_TITLE1-vari-{i}.jpg"}
        for i in range(1, 9)
    ]
    exact, flat = dm.build_index(files)
    result = dm.find_matches("2401_TitleB_IMG_Madup_Carousel_4X5_TITLE1-vari", exact, flat)
    assert len(result) == 8


def test_find_matches_prefix_fallback_rejects_false_numeric_prefix():
    """'_1'이 '_10', '_11'에 우연히 매칭되면 안 된다 — 구분자 검사가 이걸 막아야 한다."""
    files = [{"id": "a", "name": "1_TitleA_VID_X_Y_1X1_10"}]
    exact, flat = dm.build_index(files)
    result = dm.find_matches("1_TitleB_VID_X_Y_1X1_1", exact, flat)
    assert result == []


def test_find_matches_unmatchable_ad_name_returns_empty():
    files = [{"id": "a", "name": "1_TitleA_VID_X_Y_1X1_Z"}]
    exact, flat = dm.build_index(files)
    assert dm.find_matches("too_few", exact, flat) == []


def test_fetch_default_thumbnail_data_uri_empty_link_returns_empty_string():
    assert dm.fetch_default_thumbnail_data_uri("") == ""


def test_fetch_default_thumbnail_data_uri_swallows_network_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(dm.urllib.request, "urlopen", boom)
    assert dm.fetch_default_thumbnail_data_uri("https://example.com/thumb.jpg") == ""


def test_extract_first_frame_swallows_errors_and_returns_empty(monkeypatch):
    """자격증명이나 다운로드가 실패해도 카드 전체를 죽이지 않고 빈 문자열을 돌려준다."""
    def boom():
        raise RuntimeError("no credentials")

    monkeypatch.setattr(dm, "get_credentials", boom)
    assert dm.extract_first_frame_data_uri("file123", "clip.mp4") == ""


def test_material_thumbnail_prefers_first_frame(monkeypatch):
    monkeypatch.setattr(dm, "extract_first_frame_data_uri", lambda fid, name: "data:image/jpeg;base64,FIRSTFRAME")
    monkeypatch.setattr(dm, "fetch_default_thumbnail_data_uri", lambda link: "data:image/jpeg;base64,DEFAULT")
    result = dm.material_thumbnail_data_uri({"id": "a", "name": "x.mp4", "thumbnailLink": "https://x"})
    assert result == "data:image/jpeg;base64,FIRSTFRAME"


def test_material_thumbnail_falls_back_to_default_when_extraction_fails(monkeypatch):
    monkeypatch.setattr(dm, "extract_first_frame_data_uri", lambda fid, name: "")
    monkeypatch.setattr(dm, "fetch_default_thumbnail_data_uri", lambda link: "data:image/jpeg;base64,DEFAULT")
    result = dm.material_thumbnail_data_uri({"id": "a", "name": "x.mp4", "thumbnailLink": "https://x"})
    assert result == "data:image/jpeg;base64,DEFAULT"


def test_material_thumbnails_returns_empty_dict_for_no_specs():
    assert dm.material_thumbnails([]) == {}


def test_material_thumbnails_maps_each_file_id(monkeypatch):
    monkeypatch.setattr(dm, "material_thumbnail_data_uri",
                        lambda f: "uri:" + f["id"])
    result = dm.material_thumbnails([("a", "a.mp4", "l1"), ("b", "b.mp4", "l2")])
    assert result == {"a": "uri:a", "b": "uri:b"}


def test_material_thumbnails_isolates_one_failure(monkeypatch):
    """한 건이 터져도 나머지 카드 썸네일은 살아야 한다."""
    def flaky(f):
        if f["id"] == "bad":
            raise RuntimeError("download blew up")
        return "uri:" + f["id"]

    monkeypatch.setattr(dm, "material_thumbnail_data_uri", flaky)
    result = dm.material_thumbnails([("good", "g.mp4", ""), ("bad", "b.mp4", "")])
    assert result == {"good": "uri:good", "bad": ""}


def test_extract_first_frame_returns_empty_for_blank_file_id():
    assert dm.extract_first_frame_data_uri("", "x.mp4") == ""


def test_extract_first_frame_uses_partial_download_when_it_decodes(monkeypatch):
    """앞부분만 받아 디코딩되면 전체 다운로드는 하지 않아야 한다(속도 최적화의 핵심)."""
    monkeypatch.setattr(dm, "get_credentials", lambda: object())

    class FakeResponse:
        status_code = 206
        content = b"partial-bytes"

    class FakeSession:
        def __init__(self, creds):
            pass

        def get(self, url, headers=None, timeout=None):
            assert headers and "Range" in headers  # 부분 요청이어야 한다
            return FakeResponse()

    monkeypatch.setattr(dm.google.auth.transport.requests, "AuthorizedSession", FakeSession)
    monkeypatch.setattr(dm, "_frame_from_video_bytes",
                        lambda data, suffix: "data:image/jpeg;base64,PARTIAL")

    def must_not_run(*args, **kwargs):
        raise AssertionError("부분 다운로드가 성공했으면 전체를 받지 않아야 한다")

    monkeypatch.setattr(dm, "build", must_not_run)
    assert dm.extract_first_frame_data_uri("fid", "clip.mp4") == "data:image/jpeg;base64,PARTIAL"


# ----------------------------------------------------------------------------
# 규격 ALL 폴백 — 집행 데이터의 ALL 소재는 Drive에 9X16 이름으로 올라가 있다.


def test_substitute_all_dimension_replaces_the_all_token():
    assert dm.substitute_all_dimension("6405_vid_webtoon-vs_votrailer_all_1-kr") == (
        "6405_vid_webtoon-vs_votrailer_9x16_1-kr"
    )


def test_substitute_all_dimension_returns_none_without_all():
    assert dm.substitute_all_dimension("6405_vid_webtoon-vs_votrailer_9x16_1-kr") is None


def test_substitute_all_dimension_leaves_partial_words_alone():
    """'all'이 토큰 전체일 때만 바꾼다 — 'ballad', 'all-in' 같은 값은 건드리지 않는다."""
    assert dm.substitute_all_dimension("1_vid_a_b_1x1_ballad") is None
    assert dm.substitute_all_dimension("1_vid_a_b_1x1_all-in") is None


def test_find_matches_falls_back_to_9x16_for_all_dimension():
    """RAW가 ALL이면 Drive의 9X16 파일을 찾아야 한다(실제 실패 사례)."""
    files = [{"id": "a", "name": "6405_青梅竹馬情結_VID_Webtoon-VS_VoTrailer_9X16_1-KR"}]
    exact, flat = dm.build_index(files)
    result = dm.find_matches("6405_青梅竹馬情結_VID_Webtoon-VS_VoTrailer_ALL_1-KR", exact, flat)
    assert [f["id"] for f in result] == ["a"]


def test_all_fallback_does_not_override_a_real_match():
    """원래 이름으로 찾은 결과가 있으면 치환 결과가 그걸 밀어내면 안 된다."""
    files = [
        {"id": "literal", "name": "1_TitleA_VID_X_Y_ALL_Z"},
        {"id": "vertical", "name": "1_TitleA_VID_X_Y_9X16_Z"},
    ]
    exact, flat = dm.build_index(files)
    result = dm.find_matches("1_TitleB_VID_X_Y_ALL_Z", exact, flat)
    assert [f["id"] for f in result] == ["literal"]


def test_all_fallback_still_returns_empty_when_nothing_matches():
    files = [{"id": "a", "name": "9_Other_VID_X_Y_9X16_Z"}]
    exact, flat = dm.build_index(files)
    assert dm.find_matches("1_TitleB_VID_X_Y_ALL_Z", exact, flat) == []
