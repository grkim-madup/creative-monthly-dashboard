# -*- coding: utf-8 -*-
"""규격 `ALL` 소재를 Drive에서 찾는 방법.

`ALL`은 여러 규격을 한 캠페인으로 묶어 돌린 것이라 Drive에 그 이름으로 올라가
있지 않다 — 실측(2026-08-25) Drive 8,577개 파일 중 `ALL` 토큰을 가진 파일은 **0개**
였고, 원본은 실제 규격 이름으로 올라가 있었다.

2026-09-07 규리님 요청으로 `1X1` 폴백을 더했다. `ALL` 집행에는 세로 영상뿐 아니라
정방형 배너도 섞여 있다(8월 메타 `ALL` 행 구성 VID 164 / IMG 25 / GIF 3).
"""
import drive_materials as dm


def index_of(*names):
    files = [{"id": f"id{i}", "name": n} for i, n in enumerate(names)]
    return dm.build_index(files)


AD = "10451_紫羅蘭之戀_IMG_Madup_SingleImage_ALL_TITLE1"


def test_exact_name_wins_over_any_substitution():
    exact, flat = index_of(AD + ".jpg", AD.replace("ALL", "9X16") + ".jpg")
    found = dm.find_matches(AD, exact, flat)
    assert [f["name"] for f in found] == [AD + ".jpg"]


def test_falls_back_to_9x16_first():
    exact, flat = index_of(AD.replace("ALL", "9X16") + ".mp4",
                           AD.replace("ALL", "1X1") + ".jpg")
    found = dm.find_matches(AD, exact, flat)
    assert [f["name"] for f in found] == [AD.replace("ALL", "9X16") + ".mp4"]


def test_falls_back_to_1x1_when_9x16_is_missing():
    """실측: 8월 `ALL` 소재 3개가 이 폴백으로 새로 잡혔다."""
    exact, flat = index_of(AD.replace("ALL", "1X1") + ".jpg")
    found = dm.find_matches(AD, exact, flat)
    assert [f["name"] for f in found] == [AD.replace("ALL", "1X1") + ".jpg"]


def test_no_match_stays_empty():
    exact, flat = index_of(AD.replace("ALL", "16X9") + ".mp4")
    assert dm.find_matches(AD, exact, flat) == []


def test_candidates_are_tried_in_order():
    key = dm.normalize_name(AD)
    candidates = dm.all_dimension_candidates(key)
    assert len(candidates) == 2
    assert "9x16" in candidates[0]
    assert "1x1" in candidates[1]


def test_non_all_creatives_have_no_candidates():
    key = dm.normalize_name("10451_紫羅蘭之戀_IMG_Madup_SingleImage_9X16_TITLE1")
    assert dm.all_dimension_candidates(key) == []


def test_substitution_only_touches_the_dimension_token():
    """`ALL`이 USP나 Extra Info에 들어간 경우까지 바꾸면 엉뚱한 파일을 찾는다."""
    key = dm.normalize_name("1_작품_VID_Madup_Highlight_ALL_ALLNIGHT")
    substituted = dm.substitute_all_dimension(key, "9x16")
    assert "9x16" in substituted
    assert "allnight" in substituted        # USP 토큰은 그대로
