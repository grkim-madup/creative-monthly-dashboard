# -*- coding: utf-8 -*-
"""썸네일 카드의 소진액 = **소재 묶음 전체 합계**.

2026-09-29 규리님 지적: *"썸네일 소진액과 실제 테이블에서 보여지는 소진액에 차이가
있어."* 실측(9월 COMIC 블록): 카드에 ₩168,033이 찍혔는데 그 소재의 실제 소진은
**₩2,089,631**이었다. 카드 5장 합이 ₩499,790으로 블록 KPI ₩3,679,243의 **13.6%**.

원인: `representative_ads`는 묶음마다 **한 행만** 남기는 함수인데(70행 → 5행),
화면이 그 **뒤에** `groupby("ad")["cost"].sum()`을 해서 남은 한 행의 값만 더했다.
개수를 셀 때는 맞는 함수이고, **합계를 낼 때 쓰면 안 되는 함수**였다.
"""

from __future__ import annotations

import pandas as pd

from creative_data import ad_group_totals

A1 = "3510_작품_IMG_Madup_SingleImage_1X1_TITLE2-comic"
AALL = "3510_작품_IMG_Madup_SingleImage_ALL_TITLE2-comic"
B1 = "5923_다른작품_IMG_Madup_SingleImage_1X1_TITLE1-comic"


def frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """(소재명, 규격, 소진) → 화면이 넘기는 모양의 행 단위 프레임."""
    import creative_data as cd
    return pd.DataFrame([
        {"ad": ad, "size": size, "cost": cost,
         "ad_group": cd.ad_group_key(ad, size)}
        for ad, size, cost in rows
    ])


def test_행이_여러_개여도_전부_더한다():
    """날짜·매체·OS로 쪼개진 행을 하나도 빠뜨리면 안 된다."""
    df = frame([(A1, "1X1", 100.0), (A1, "1X1", 200.0), (A1, "1X1", 300.0)])
    assert ad_group_totals(df).to_dict() == {A1: 600.0}


def test_ALL과_실제_규격을_한_장으로_합친다():
    """카드 한 장 = 소재 묶음 하나. `ALL`과 `1X1`은 같은 묶음이다."""
    df = frame([(A1, "1X1", 1_867_847.0), (AALL, "ALL", 221_784.0)])
    totals = ad_group_totals(df)
    assert len(totals) == 1
    assert totals.iloc[0] == 2_089_631.0
    # 대표 이름은 `ALL`이 아니어야 한다 — 그 이름으로는 Drive에 파일이 없다.
    assert totals.index[0] == A1


def test_카드_합계가_표_합계와_같다():
    """이게 이 함수의 존재 이유다 — 블록 KPI와 카드 합이 어긋나면 안 된다."""
    df = frame([(A1, "1X1", 1_867_847.0), (AALL, "ALL", 221_784.0),
                (B1, "1X1", 179_519.0)])
    assert ad_group_totals(df).sum() == df["cost"].sum()


def test_소진_큰_순서로_돌려준다():
    df = frame([(B1, "1X1", 10.0), (A1, "1X1", 90.0)])
    assert list(ad_group_totals(df).index) == [A1, B1]


def test_묶음_컬럼이_없으면_소재명으로_합친다():
    """`ad_group`을 못 붙인 프레임에서도 **합계는 온전해야** 한다."""
    df = pd.DataFrame([{"ad": A1, "cost": 100.0}, {"ad": A1, "cost": 50.0},
                       {"ad": B1, "cost": 30.0}])
    assert ad_group_totals(df).to_dict() == {A1: 150.0, B1: 30.0}


def test_빈_입력과_없는_지표를_견딘다():
    assert ad_group_totals(pd.DataFrame()).empty
    assert ad_group_totals(None).empty
    assert ad_group_totals(frame([(A1, "1X1", 1.0)]), metric="없는지표").empty


def test_설치_같은_다른_지표도_된다():
    df = frame([(A1, "1X1", 1.0), (AALL, "ALL", 2.0)])
    df["total install"] = [7.0, 3.0]
    assert ad_group_totals(df, metric="total install").to_dict() == {A1: 10.0}
