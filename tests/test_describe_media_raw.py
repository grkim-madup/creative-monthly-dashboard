"""시트 링크 확인용 요약 문구 — 링크 대신 이 문구를 보고 판단하므로 정확해야 한다."""

import pandas as pd

from creative_data import describe_media_raw


def _frame(months: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"month": months})


def test_연속된_달은_범위로():
    assert describe_media_raw(_frame([2, 3, 4])) == "2~4월 Media_RAW · 3행"


def test_한_달만_있으면_범위로_쓰지_않는다():
    assert describe_media_raw(_frame([8, 8])) == "8월 Media_RAW · 2행"


def test_띄어_있는_달은_범위로_뭉개지_않는다():
    # `2~8월`로 쓰면 없는 4~7월이 있는 것처럼 읽힌다.
    assert describe_media_raw(_frame([2, 3, 8])) == "2·3·8월 Media_RAW · 3행"


def test_리포트_월을_주면_그_달_행수를_덧붙인다():
    text = describe_media_raw(_frame([7, 8, 8]), month=8)
    assert text == "7~8월 Media_RAW · 3행 (이 달 8월 2행)"


def test_그_달_데이터가_없으면_0행으로_말한다():
    assert "(이 달 9월 0행)" in describe_media_raw(_frame([7, 8]), month=9)


def test_빈_프레임():
    assert describe_media_raw(pd.DataFrame()) == "Media_RAW · 데이터 없음"


def test_월_컬럼이_전부_비었을_때():
    frame = pd.DataFrame({"month": [None, None]})
    assert describe_media_raw(frame) == "Media_RAW · 2행 (월 해석 실패)"
