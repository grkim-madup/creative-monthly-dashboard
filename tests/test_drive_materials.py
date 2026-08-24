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


def test_fetch_thumbnail_data_uri_empty_link_returns_empty_string():
    assert dm.fetch_thumbnail_data_uri("") == ""


def test_fetch_thumbnail_data_uri_swallows_network_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(dm.urllib.request, "urlopen", boom)
    assert dm.fetch_thumbnail_data_uri("https://example.com/thumb.jpg") == ""
