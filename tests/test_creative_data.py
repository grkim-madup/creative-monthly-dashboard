import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from creative_data import (
    split_extra_info,  # noqa: E402
    add_derived_metrics,
    aggregate_by,
    attach_creative_attributes,
    normalize_media,
    parse_ad_name,
    parse_raw_values,
    producer_group,
    size_orientation,
    to_number,
    top_creatives,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("₩8,010,750", 8010750.0),
        ("572,380", 572380.0),
        ("18.5%", 0.185),
        ("0.04%", 0.0004),
        ("-", np.nan),
        ("", np.nan),
        (1234, 1234.0),
    ],
)
def test_to_number(text, expected):
    result = to_number(text)
    if np.isnan(expected):
        assert np.isnan(result)
    else:
        assert result == pytest.approx(expected)


def test_normalize_media_maps_facebook_to_meta():
    assert normalize_media("Facebook") == "Meta"
    assert normalize_media("TikTok") == "TikTok"
    assert normalize_media("googleadwords_int") == "Google"


def test_parse_ad_name_standard():
    parsed = parse_ad_name("2401_極權教師_VID_Webtoon-VS_MixTitle_9X16_1")
    assert parsed["title_code"] == "2401"
    assert parsed["title_name"] == "極權教師"
    assert parsed["format"] == "VID"
    assert parsed["producer"] == "Webtoon-VS"
    assert parsed["creative_type"] == "MixTitle"
    assert parsed["size"] == "9X16"
    assert parsed["orientation"] == "세로"
    assert parsed["variants"] == []


def test_parse_ad_name_collects_variant_tags():
    parsed = parse_ad_name("3924_金部長_VID_Webtoon-KE_Trend_9X16_8_6s")
    assert parsed["creative_type"] == "Trend"
    assert parsed["variants"] == ["6초 컷다운"]

    parsed = parse_ad_name("9981_丟臉遊戲_VID_Webtoon_VoTrailer_9X16_1_socialmainfilmsong_KR")
    assert parsed["producer"] == "Webtoon"
    assert parsed["creative_type"] == "VoTrailer"
    assert "한국어 VO" in parsed["variants"]


def test_parse_ad_name_handles_title_name_with_underscore():
    parsed = parse_ad_name("6014_12週年WEBTOON嘉年華W1_VID_Webtoon_Mix_9X16_1")
    assert parsed["title_code"] == "6014"
    assert parsed["title_name"] == "12週年WEBTOON嘉年華W1"
    assert parsed["creative_type"] == "Mix"


def test_parse_ad_name_lowercase_size_and_gif():
    parsed = parse_ad_name("10398_劍術名門的死靈法師_GIF_Madup_Visual_1X1_TITLE2_new")
    assert parsed["format"] == "GIF"
    assert parsed["orientation"] == "정방형"
    assert parsed["variants"] == ["신규 리프레시"]

    parsed = parse_ad_name("10401_神魔大帝_VID_Webtoon-YJ_Highlight_1x1_5")
    assert parsed["size"] == "1X1"
    assert parsed["orientation"] == "정방형"


def test_parse_ad_name_legacy_order_size_before_format():
    parsed = parse_ad_name("1618_某天成為公主_9X16_VID_VS_Teaser_1")
    assert parsed["title_code"] == "1618"
    assert parsed["title_name"] == "某天成為公主"
    assert parsed["format"] == "VID"
    assert parsed["size"] == "9X16"
    assert parsed["orientation"] == "세로"
    assert parsed["producer"] == "VS"
    assert parsed["creative_type"] == "Teaser_1"


def test_parse_ad_name_legacy_bare_version_is_not_a_producer():
    parsed = parse_ad_name("5300_再婚皇后_9X16_VID_2")
    assert parsed["size"] == "9X16"
    assert parsed["producer"] is None
    assert parsed["creative_type"] is None


def test_size_orientation_computed_from_ratio_not_lookup():
    assert size_orientation("32X5") == "가로"
    assert size_orientation("1080X1920") == "세로"
    assert size_orientation("4X5") == "세로"
    assert size_orientation("1X1") == "정방형"
    assert size_orientation("ALL") == "혼합"
    assert size_orientation(None) is None


def test_parse_ad_name_unparseable_returns_none_not_guess():
    parsed = parse_ad_name("완전히_다른_이름")
    assert parsed["format"] is None
    assert parsed["size"] is None
    assert parsed["title_code"] is None


def test_producer_group():
    assert producer_group("Webtoon-VS") == "네이버웹툰"
    assert producer_group("Webtoon") == "네이버웹툰"
    assert producer_group("Madup") == "매드업"
    assert producer_group(None) is None


def _raw_values():
    header = [
        "월", "주차", "요일", "date", "매체명", "UA / non-UA 구분", "Part", "OS 구분",
        "campaign", "group", "ad", "Title ID (작품코드 상세)", "타이틀 명 (국문)",
        "impression", "click", "cost (마크업 포함)", "total install",
        "D0(uni) read", "D0(uni) coin", "D7(uni) coin", "UA D7(uni) read", "최종 AD", "유형",
    ]
    rows = [
        ["7", "27", "화", "2026-07-01", "TikTok", "UA", "AppInstall", "AOS",
         "c1", "g1", "ad1", "2401", "극권교사",
         "100,000", "18,500", "₩8,010,750", "4,529", "2,334", "0", "2", "1",
         "2401_極權教師_VID_Webtoon-VS_MixTitle_9X16_1", "ACTION"],
        ["7", "28", "수", "2026-07-08", "Facebook", "UA", "AppInstall", "AOS",
         "c1", "g1", "ad1", "2401", "극권교사",
         "50,000", "500", "₩311,544", "119", "53", "1", "1", "0",
         "2401_極權教師_VID_Webtoon-VS_MixTitle_9X16_1", "ACTION"],
        ["8", "32", "금", "2026-08-01", "TikTok", "UA", "AppInstall", "iOS",
         "c2", "g2", "ad2", "9981", "쪽팔려",
         "10,000", "300", "₩100,000", "50", "30", "5", "6", "3",
         "9981_丟臉遊戲_VID_Webtoon_VoTrailer_9X16_1-KR", "ROMANCE"],
    ]
    return [header] + rows


def test_parse_raw_values_normalizes_types_and_media():
    df = parse_raw_values(_raw_values())
    assert len(df) == 3
    assert set(df["media"]) == {"TikTok", "Meta"}
    assert df.loc[0, "cost"] == pytest.approx(8010750.0)
    assert df.loc[0, "month"] == 7
    assert df.loc[0, "os"] == "AOS"


def test_parse_raw_values_requires_ad_column():
    with pytest.raises(ValueError):
        parse_raw_values([["월", "매체명"], ["7", "TikTok"]])


def test_parse_raw_values_keeps_google_rows_without_creative_ad():
    """구글은 '최종 AD'(소재명) 컬럼이 항상 비어 있다 — 소재 단위 태깅이 없어서지 데이터가

    없는 게 아니다. 빈 소재명 행을 걸러내는 필터에 휩쓸려 구글 행 전체가 사라지면 안 된다.
    """
    header, row = _raw_values()[0], _raw_values()[1]
    google_row = list(row)
    google_row[header.index("매체명")] = "Google"
    google_row[header.index("ad")] = "-"
    google_row[header.index("최종 AD")] = ""  # 구글은 이 컬럼이 항상 빈 값

    df = parse_raw_values([header, google_row])
    assert len(df) == 1
    assert df.loc[0, "media"] == "Google"
    assert df.loc[0, "ad"] == "-"


def test_attach_creative_attributes():
    df = attach_creative_attributes(parse_raw_values(_raw_values()))
    assert df.loc[0, "format"] == "VID"
    assert df.loc[0, "producer_group"] == "네이버웹툰"
    assert df.loc[0, "orientation"] == "세로"
    assert df.loc[0, "variant_label"] == "기본"
    assert df.loc[2, "variant_label"] == "한국어 VO"


def test_add_derived_metrics_and_zero_division():
    df = pd.DataFrame({
        "impression": [1000, 0],
        "click": [100, 0],
        "cost": [5000.0, 0.0],
        "total install": [10, 0],
        "D0 read": [5, 0],
        "D0 coin": [1, 0],
        "D7 coin": [2, 0],
    })
    out = add_derived_metrics(df)
    assert out.loc[0, "CTR"] == pytest.approx(0.1)
    assert out.loc[0, "CPC"] == pytest.approx(50.0)
    assert out.loc[0, "CPI"] == pytest.approx(500.0)
    assert out.loc[0, "D0 read CVR"] == pytest.approx(0.5)
    assert np.isnan(out.loc[1, "CTR"])
    assert np.isnan(out.loc[1, "CPI"])


def test_aggregate_by_recomputes_ratios_from_sums_not_averages():
    df = add_derived_metrics(parse_raw_values(_raw_values()))
    agg = aggregate_by(df, ["ad"])
    row = agg[agg["ad"].str.startswith("2401")].iloc[0]
    assert row["impression"] == 150_000
    assert row["click"] == 19_000
    # 두 행의 CTR 평균(0.185, 0.01)이 아니라 합계 기반 19000/150000 이어야 한다.
    assert row["CTR"] == pytest.approx(19_000 / 150_000)


def test_top_creatives_ranks_and_limits():
    df = add_derived_metrics(parse_raw_values(_raw_values()))
    top = top_creatives(df, "total install", limit=2)
    assert len(top) == 2
    assert top.loc[0, "total install"] == 4529
    assert top.loc[0, "media"] == "TikTok"


def test_top_creatives_min_cost_filter_removes_noise():
    df = add_derived_metrics(parse_raw_values(_raw_values()))
    top = top_creatives(df, "total install", limit=10, min_cost=500_000)
    assert set(top["media"]) == {"TikTok"}
    assert len(top) == 1


def test_parse_ad_name_splits_usp_and_extra_info():
    """네이밍 컨벤션 Y~AH열: Dimension 뒤 첫 토큰이 USP, 그 뒤가 Extra Info1/2/3."""
    parsed = parse_ad_name("9981_丟臉遊戲_VID_Webtoon_VoTrailer_9X16_1_socialmainfilmsong_KR")
    assert parsed["size"] == "9X16"
    assert parsed["usp"] == "1"
    assert parsed["extra_info"] == "socialmainfilmsong_KR"

    parsed = parse_ad_name("3924_金部長_VID_Webtoon-KE_Trend_9X16_8_6s")
    assert parsed["usp"] == "8"
    assert parsed["extra_info"] == "6s"


def test_parse_ad_name_usp_without_extra_info():
    parsed = parse_ad_name("2401_極權教師_VID_Webtoon-VS_MixTitle_9X16_1")
    assert parsed["usp"] == "1"
    assert parsed["extra_info"] is None


def test_named_usp_is_kept_verbatim():
    parsed = parse_ad_name("9622_不良少年的初戀_VID_Madup_Visual_9X16_BEFOREAFTER")
    assert parsed["usp"] == "BEFOREAFTER"


def test_extra_info_label_defaults_to_none_marker():
    df = attach_creative_attributes(parse_raw_values(_raw_values()))
    assert df.loc[0, "extra_info_label"] == "없음"
    # `1-KR`은 USP `1` + Extra Info `KR`이다. 예전에는 통째로 USP였고, 그 바람에
    # 같은 USP가 `1`/`1-KR`/`1-kr`/`1-new`로 갈렸다(2026-09-02 수정).
    assert df.loc[2, "usp"] == "1"
    assert df.loc[2, "extra_info"] == "KR"


def test_hyphen_after_usp_is_extra_info():
    """실무 표기는 Extra Info를 `_`가 아니라 USP 뒤에 `-`로 붙이기도 한다.

    이걸 안 쪼개서 `comic`·`epn` 같은 태그가 조건 드롭다운에 아예 뜨지 않았다.
    2월부터 쭉 있던 표기라 8월에 새로 생긴 문제가 아니다.
    """
    parsed = parse_ad_name("3510_狂魔重生記_IMG_Madup_SingleImage_1X1_TITLE2-comic")
    assert parsed["usp"] == "TITLE2"
    assert parsed["extra_info"] == "comic"

    parsed = parse_ad_name("3510_狂魔重生記_VID_Madup_Highlight_9X16_BACK-6s-text-epn")
    assert parsed["usp"] == "BACK"
    assert split_extra_info(parsed["extra_info"]) == ["6s", "text", "epn"]


def test_hyphen_and_underscore_extra_info_combine():
    """`-`로 붙인 것과 `_`로 붙인 것이 한 소재명에 같이 오면 둘 다 살린다."""
    parsed = parse_ad_name("1234_작품_VID_Madup_Highlight_9X16_BACK-6s_text")
    assert parsed["usp"] == "BACK"
    assert split_extra_info(parsed["extra_info"]) == ["6s", "text"]


def test_usp_without_hyphen_is_untouched():
    """하이픈이 없는 USP는 한 글자도 건드리지 않는다 — 이름을 잘라내면 안 된다."""
    assert parse_ad_name(
        "9622_不良少年的初戀_VID_Madup_Visual_9X16_BEFOREAFTER")["usp"] == "BEFOREAFTER"


def test_normalize_creative_type_covers_convention_vocabulary():
    from creative_data import normalize_creative_type
    for canonical in ("SlideShow", "RECAP", "Spoiler", "Actional", "OST", "Prologue"):
        assert normalize_creative_type(f"{canonical}_9X16_1") == canonical


def test_normalize_creative_type_treats_nan_as_missing():
    """pandas .map()을 거치면 결측이 None이 아니라 float('nan')으로 들어올 때가 있다.

    bool(float('nan'))은 True라서 `not x` 체크로는 안 걸러지고, 그대로 str(nan)="nan"
    문자열이 남아 차트·표에 진짜 값처럼 찍히는 실제 버그가 있었다.
    """
    from creative_data import normalize_creative_type
    assert normalize_creative_type(float("nan")) is None
    assert normalize_creative_type(None) is None
    assert normalize_creative_type(pd.NA) is None


def test_split_extra_info_breaks_on_both_separators():
    from creative_data import split_extra_info
    assert split_extra_info("text-thumb") == ["text", "thumb"]
    # 대소문자만 다른 표기가 섞여 있어 소문자로 통일한다 — 안 그러면 sns/SNS가 따로 집계된다.
    assert split_extra_info("social_KR") == ["social", "kr"]
    assert split_extra_info("SNS") == split_extra_info("sns") == ["sns"]
    assert split_extra_info("text-TEXT") == ["text"]
    assert split_extra_info("6s") == ["6s"]
    assert split_extra_info(None) == ["없음"]
    assert split_extra_info("") == ["없음"]


def test_explode_extra_info_puts_a_creative_in_every_tag_row():
    from creative_data import explode_extra_info
    df = pd.DataFrame({
        "ad": ["a", "b"],
        "extra_info": ["text-thumb", None],
        "cost": [100.0, 50.0],
    })
    out = explode_extra_info(df)
    assert sorted(out["extra_info_tag"]) == ["text", "thumb", "없음"]
    # 태그가 2개인 소재는 두 행에 들어가므로 합계가 원본보다 커진다(의도된 동작).
    assert out["cost"].sum() == pytest.approx(250.0)
    assert out[out["extra_info_tag"] == "text"]["cost"].sum() == pytest.approx(100.0)
