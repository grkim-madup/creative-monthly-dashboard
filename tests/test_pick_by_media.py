# -*- coding: utf-8 -*-
"""우수·저조를 **매체 안에서만** 고른다 (규리님 2026-09-30).

*"모든 worst/best 컬러링 규칙이 다시 들어가야 할 것 같아. 각 매체별 특성이 강해서."*

9월 실측: 2번 섹션 네 표 중 셋이 사실상 한 매체 표였다(AOS·인스톨 TikTok 10 / Meta 0,
iOS·인스톨 Meta 9 / TikTok 1, iOS·D0Coin Meta 10 / TikTok 0). 한 표에서 CPI를 견주면
소진이 큰 매체가 슬롯을 다 가져간다.
"""
import pandas as pd
import pytest

from creative_data import (
    PICK_MIN_ROWS_PER_MEDIA,
    pick_by_media,
)


def whole_table(df: pd.DataFrame):
    """매체 구분 없이 표 전체를 한 묶음으로 본 결과(옛 동작 비교용)."""
    return pick_by_media(df.drop(columns=["media"]))


def frame(rows: list[dict]) -> pd.DataFrame:
    """`ad · media · cost · CPI · CTR` 만 있는 최소 표."""
    return pd.DataFrame(rows)


def media_of(df: pd.DataFrame, picks: dict) -> set:
    return {df.loc[index, "media"] for index in picks}


# 한 매체가 두 지표 모두에서 통째로 앞서는 표. **9월 실데이터의 실제 성질이다** —
# AOS에서 TikTok CPI는 1,039~1,690인데 Meta는 3,080~4,127로 구간이 아예 겹치지 않는다.
# 이러면 표 전체로 견줄 때 한 매체가 우수 슬롯을, 다른 매체가 저조 슬롯을 통째로 가져간다.
MIXED = [
    {"ad": "tt_a", "media": "TikTok", "cost": 10_000_000, "CPI": 1_700, "CTR": 40.0},
    {"ad": "tt_b", "media": "TikTok", "cost": 8_000_000, "CPI": 1_500, "CTR": 52.0},
    {"ad": "tt_c", "media": "TikTok", "cost": 6_000_000, "CPI": 1_600, "CTR": 44.0},
    {"ad": "tt_d", "media": "TikTok", "cost": 4_000_000, "CPI": 1_400, "CTR": 48.0},
    {"ad": "mt_a", "media": "Meta", "cost": 9_000_000, "CPI": 4_100, "CTR": 38.0},
    {"ad": "mt_b", "media": "Meta", "cost": 7_000_000, "CPI": 3_600, "CTR": 50.0},
    {"ad": "mt_c", "media": "Meta", "cost": 5_000_000, "CPI": 3_900, "CTR": 42.0},
    {"ad": "mt_d", "media": "Meta", "cost": 3_000_000, "CPI": 3_100, "CTR": 46.0},
]


# --------------------------------------------------------- 매체별로 갈리는가

def test_두_매체가_모두_칠해진다():
    """지금 규칙은 **한 매체가 우수를, 다른 매체가 저조를** 통째로 가져간다."""
    df = frame(MIXED)

    old_best, old_worst = whole_table(df)
    new_best, new_worst = pick_by_media(df)

    # 옛 규칙: "TikTok은 다 우수, Meta는 다 저조" — 소재가 아니라 매체를 칠한 셈이다.
    assert media_of(df, old_best) == {"TikTok"}
    assert media_of(df, old_worst) == {"Meta"}

    # 새 규칙: 두 매체가 각각 우수 하나 · 저조 하나를 갖는다.
    assert media_of(df, new_best) == {"TikTok", "Meta"}
    assert media_of(df, new_worst) == {"TikTok", "Meta"}


def test_매체_안에서만_견준다():
    """Meta의 우수·저조는 **Meta 안에서** 정해진다.

    2026-09-30부터 **소진액이 지표 순위를 뒤집지 않으므로** CPI 최저가 그대로 우수다.
    """
    df = frame(MIXED)
    best, worst = pick_by_media(df)

    meta_best = [i for i in best if df.loc[i, "media"] == "Meta"
                 and best[i] == "CPI"]
    meta_worst = [i for i in worst if df.loc[i, "media"] == "Meta"
                  and worst[i] == "CPI"]
    assert df.loc[meta_best[0], "ad"] == "mt_d"   # CPI 3,100 — Meta 안에서 최저
    assert df.loc[meta_worst[0], "ad"] == "mt_a"  # CPI 4,100 — Meta 안에서 최고


# ------------------------------------------- 칠하는 줄 수가 늘어나지 않는가

def test_칠하는_줄이_늘어나지_않는다():
    """**이 테스트가 설계의 핵심 계약이다.**

    매체마다 2지표씩 주면 칠하는 줄이 4 → 8로 두 배가 된다(실측). 10줄 표의 80%가
    칠해지면 색이 강조가 아니라 배경이다. 유효 매체 수로 지표 예산을 나눠야 한다.
    """
    df = frame(MIXED)
    new = pick_by_media(df)
    assert len(new[0]) + len(new[1]) <= 4


def test_우수와_저조가_겹치지_않는다():
    df = frame(MIXED)
    best, worst = pick_by_media(df)
    assert not (set(best) & set(worst))


# --------------------------------------------------- 줄 수가 적은 매체 제외

def test_줄이_적은_매체는_선정에서_빠진다():
    """9월 `iOS · 인스톨`의 TikTok이 **1줄**이었다.

    그 한 줄을 매체별로 뽑으면 자동으로 우수(이자 저조)가 된다 —
    "TikTok에서 가장 좋은 소재"라고 쓸 수 없는 것을 그렇게 쓰는 셈이다.
    """
    rows = [r for r in MIXED if r["media"] == "Meta"]
    rows.append({"ad": "tt_lonely", "media": "TikTok",
                 "cost": 2_000_000, "CPI": 900, "CTR": 5.0})
    df = frame(rows)

    best, worst = pick_by_media(df)
    assert media_of(df, best) == {"Meta"}
    assert media_of(df, worst) == {"Meta"}
    # CPI 900으로 표 전체 최저인데도 우수가 아니다 — 줄 수가 모자라서다.
    assert not any(df.loc[i, "ad"] == "tt_lonely" for i in {**best, **worst})


def test_문턱은_상수로_조절된다():
    rows = [r for r in MIXED if r["media"] == "Meta"]
    rows += [r for r in MIXED if r["media"] == "TikTok"][:2]   # TikTok 2줄
    df = frame(rows)

    assert PICK_MIN_ROWS_PER_MEDIA == 3
    assert media_of(df, pick_by_media(df)[0]) == {"Meta"}
    assert media_of(df, pick_by_media(df, min_rows=2)[0]) == {"TikTok", "Meta"}


# ------------------------------------------------------------- 폴백 경로

def test_매체_컬럼이_없으면_표_전체가_한_묶음이다():
    """구글 애셋 표와 매체 축이 없는 피벗 표가 여기 해당한다."""
    df = frame(MIXED).drop(columns=["media"])
    best, worst = pick_by_media(df)
    assert best and worst


def test_유효_매체가_하나도_없으면_표_전체에서_뽑는다():
    """전부 3줄 미만 매체뿐이어도 표를 빈 채로 두지 않는다."""
    df = frame([
        {"ad": "a", "media": "TikTok", "cost": 3_000_000, "CPI": 1_500, "CTR": 2.0},
        {"ad": "b", "media": "TikTok", "cost": 2_000_000, "CPI": 1_700, "CTR": 1.5},
        {"ad": "c", "media": "Meta", "cost": 1_000_000, "CPI": 4_000, "CTR": 1.1},
    ])
    assert pick_by_media(df) == whole_table(df)


def test_매체가_하나뿐이면_표_전체와_같다():
    """구글 표(매체 하나)는 매체 구분 유무로 결과가 달라지면 안 된다."""
    df = frame([r for r in MIXED if r["media"] == "Meta"])
    assert pick_by_media(df) == whole_table(df)


def test_최소_줄_수는_게이트_전에_센다():
    """9월 AOS·D0 Coin의 TikTok은 4줄인데 2% 게이트로 2줄이 남았다. 게이트 **뒤**로
    세면 TikTok이 통째로 선정에서 빠졌다."""
    rows = [r for r in MIXED if r["media"] == "Meta"]
    rows += [
        {"ad": "tt_big1", "media": "TikTok", "cost": 6_000_000, "CPI": 1_400, "CTR": 50.0},
        {"ad": "tt_big2", "media": "TikTok", "cost": 5_000_000, "CPI": 1_900, "CTR": 40.0},
        {"ad": "tt_tiny1", "media": "TikTok", "cost": 100_000, "CPI": 1_500, "CTR": 45.0},
        {"ad": "tt_tiny2", "media": "TikTok", "cost": 90_000, "CPI": 1_600, "CTR": 44.0},
    ]
    df = frame(rows)
    best, worst = pick_by_media(df)
    assert "TikTok" in media_of(df, best) | media_of(df, worst)


def test_빈_표는_조용히_빈_결과():
    assert pick_by_media(pd.DataFrame()) == ({}, {})
    assert pick_by_media(None) == ({}, {})


def test_사유가_실제_컬럼_이름이다():
    """소비하는 쪽이 `df.loc[index, 값]` 으로 쓴다 — 문구를 넣으면 화면이 죽는다
    (2026-09-08 배포판 사고)."""
    df = frame(MIXED)
    best, worst = pick_by_media(df)
    for reason in list(best.values()) + list(worst.values()):
        assert reason in df.columns
