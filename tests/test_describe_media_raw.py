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


def test_기간은_그_달_실제_범위를_말한다():
    from creative_data import month_date_span
    frame = pd.DataFrame({"month": [8, 8, 7],
                          "date": ["2026-08-01", "2026-08-30", "2026-07-15"]})
    # 옛 시트는 8/30까지, 새 시트는 8/31까지였다 — 이 줄이 그 차이를 드러낸다.
    assert month_date_span(frame, 8) == "8/1~8/30"


def test_기간은_그_달_데이터가_없으면_빈_문자열():
    from creative_data import month_date_span
    frame = pd.DataFrame({"month": [7], "date": ["2026-07-01"]})
    assert month_date_span(frame, 8) == ""


def test_기간은_date_컬럼이_없어도_죽지_않는다():
    from creative_data import month_date_span
    assert month_date_span(pd.DataFrame({"month": [8]}), 8) == ""
