# -*- coding: utf-8 -*-
"""소재명 끝의 버전 꼬리표(`-v2`)를 원본과 같은 소재로 본다.

규리님(2026-09-29): *"-v2가 붙어있는 소재들... 동일한 이름에 v2 안 붙은 소재랑
동일한 소재야. 동일한 소재로 취급해줘."*

실측 배경: 11224는 **원본이 Meta, `-v2`가 TikTok 재업로드**였다. 매체 축이 있는
표에서는 여전히 두 줄로 갈리므로 매체별 집행 사실은 사라지지 않는다.

⚠ 이건 **숫자가 바뀌는 수정**이다(소재 수가 줄고 소재별 소진이 합쳐진다).
   `sheet_loader.PARSER_VERSION`을 올려야 옛 parquet 캐시가 재사용되지 않는다.
"""

from __future__ import annotations

import pandas as pd

import sheet_loader
from creative_data import VERSION_SUFFIX_TITLES, merge_version_suffix

BASE = "11224_勇者之歌_VID_Webtoon-VS_Trend_9X16_1"


def test_짝이_있으면_원본_이름으로_합친다():
    out = merge_version_suffix(pd.Series([BASE, f"{BASE}-v2"]))
    assert list(out) == [BASE, BASE]


def test_짝이_없으면_그대로_둔다():
    """합칠 상대가 없는데 이름만 바꾸면 **시트에 없던 소재명**이 화면에 생긴다.

    실측 2종이 이 경우다(`SingleImage_1X1_TITLE1-v2` — 쌍둥이는 규격이 `ALL`이라
    이름이 다르다).
    """
    lone = "11224_勇者之歌_IMG_Madup_SingleImage_1X1_TITLE1-v2"
    assert list(merge_version_suffix(pd.Series([lone]))) == [lone]


def test_확인받은_작품만_합친다():
    """같은 표기라는 이유만으로 전 작품에 적용하지 않는다.

    규리님(2026-09-29): *"11224 소재에 한해서 v2 소재를 병합해."*
    `8064`에도 `-v2`가 2종 있지만 확인을 못 받았고, 그쪽은 MOLOCO·Appier·TikTok에
    3~5월까지 걸쳐 있어 패턴이 다르다 — 합치면 소진액이 엉뚱한 줄로 간다.
    """
    other = "8064_外送夥伴即將抵達_VID_Webtoon-YW_Explainer_9X16_6"
    out = merge_version_suffix(pd.Series([other, f"{other}-v2", BASE, f"{BASE}-v2"]))
    assert list(out) == [other, f"{other}-v2", BASE, BASE]


def test_허용목록에_11224가_있다():
    assert "11224" in VERSION_SUFFIX_TITLES
    assert "8064" not in VERSION_SUFFIX_TITLES


def test_대소문자를_가리지_않는다():
    out = merge_version_suffix(pd.Series([BASE, f"{BASE}-V2"]))
    assert list(out) == [BASE, BASE]


def test_v3_이상도_같은_규칙():
    out = merge_version_suffix(pd.Series([BASE, f"{BASE}-v3", f"{BASE}-v10"]))
    assert list(out) == [BASE, BASE, BASE]


def test_밑줄_v2는_건드리지_않는다():
    """`_v2`는 꼬리표가 아니라 **구형 소재명의 토큰**이다(`..._39s_v2`).

    실측 5종 모두 짝이 없어 합칠 대상 자체가 없고, 토큰을 떼면 없던 이름이 생긴다.
    """
    base = "11224_勇者之歌_VID_SingleVideo_16x9_39s"
    old = f"{base}_v2"
    assert list(merge_version_suffix(pd.Series([base, old]))) == [base, old]


def test_중간에_있는_v2는_꼬리표가_아니다():
    name = f"{BASE}-v2-text"
    assert list(merge_version_suffix(pd.Series([name]))) == [name]


def test_합칠_것이_없으면_원본_그대로_돌려준다():
    names = pd.Series(["a", "b", "c"])
    assert list(merge_version_suffix(names)) == ["a", "b", "c"]


def test_빈_입력도_견딘다():
    assert list(merge_version_suffix(pd.Series([], dtype=object))) == []


def test_파서_버전이_올라가_있다():
    """파서를 고치면 캐시 파일 이름이 바뀌어야 한다 — 안 그러면 옛 파싱이 조용히 재사용된다."""
    assert sheet_loader.PARSER_VERSION >= "v5"
    assert sheet_loader.PARSER_VERSION in str(sheet_loader._cache_path("sheet"))
