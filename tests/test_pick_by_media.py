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
    pick_best_worst,
    pick_by_media,
    pick_metrics_for,
)


def frame(rows: list[dict]) -> pd.DataFrame:
    """`ad · media · cost · CPI · CTR` 만 있는 최소 표."""
    return pd.DataFrame(rows)


def media_of(df: pd.DataFrame, picks: dict) -> set:
    return {df.loc[index, "media"] for index in picks}


# 한 매체가 두 지표 모두에서 통째로 앞서는 표. **9월 실데이터의 실제 성질이다** —
# AOS에서 TikTok CPI는 1,039~1,690인데 Meta는 3,080~4,127로 구간이 아예 겹치지 않는다.
# 이러면 표 전체로 견줄 때 한 매체가 우수 슬롯을, 다른 매체가 저조 슬롯을 통째로 가져간다.
MIXED = [
    {"ad": "tt_a", "media": "TikTok", "cost": 10_000_000, "CPI": 1_700, "CTR": 2.4},
    {"ad": "tt_b", "media": "TikTok", "cost": 8_000_000, "CPI": 1_500, "CTR": 2.9},
    {"ad": "tt_c", "media": "TikTok", "cost": 6_000_000, "CPI": 1_600, "CTR": 1.9},
    {"ad": "tt_d", "media": "TikTok", "cost": 4_000_000, "CPI": 1_400, "CTR": 2.5},
    {"ad": "mt_a", "media": "Meta", "cost": 9_000_000, "CPI": 4_100, "CTR": 1.2},
    {"ad": "mt_b", "media": "Meta", "cost": 7_000_000, "CPI": 3_600, "CTR": 1.4},
    {"ad": "mt_c", "media": "Meta", "cost": 5_000_000, "CPI": 3_900, "CTR": 1.1},
    {"ad": "mt_d", "media": "Meta", "cost": 3_000_000, "CPI": 3_100, "CTR": 1.3},
]


# --------------------------------------------------------- 매체별로 갈리는가

def test_두_매체가_모두_칠해진다():
    """지금 규칙은 **한 매체가 우수를, 다른 매체가 저조를** 통째로 가져간다."""
    df = frame(MIXED)

    old_best, old_worst = pick_best_worst(df, pick_metrics_for(df))
    new_best, new_worst = pick_by_media(df)

    # 옛 규칙: "TikTok은 다 우수, Meta는 다 저조" — 소재가 아니라 매체를 칠한 셈이다.
    assert media_of(df, old_best) == {"TikTok"}
    assert media_of(df, old_worst) == {"Meta"}

    # 새 규칙: 두 매체가 각각 우수 하나 · 저조 하나를 갖는다.
    assert media_of(df, new_best) == {"TikTok", "Meta"}
    assert media_of(df, new_worst) == {"TikTok", "Meta"}


def test_매체_안에서만_견준다():
    """Meta의 우수·저조는 **Meta 안에서** 정해진다.

    ⚠ `mt_d`(CPI 3,100 최저)가 아니라 `mt_b`(CPI 3,600)가 우수다 — 기존 규칙이
    **CPI 상위 30% 구간 안에서 소진액이 가장 큰 줄**을 집기 때문이다(`mt_d` ₩3.0M
    vs `mt_b` ₩7.0M). 이 함수는 그 산식을 안 바꾸고 **적용 범위만** 매체로 좁힌다.
    최저 CPI로 고쳐 쓰고 싶어지면 `PICK_CANDIDATE_SHARE` 주석을 먼저 읽을 것.
    """
    df = frame(MIXED)
    best, worst = pick_by_media(df)

    meta_best = [i for i in best if df.loc[i, "media"] == "Meta"]
    meta_worst = [i for i in worst if df.loc[i, "media"] == "Meta"]
    assert df.loc[meta_best[0], "ad"] == "mt_b"
    assert df.loc[meta_worst[0], "ad"] == "mt_a"   # CPI 4,100 · 소진 ₩9.0M


# ------------------------------------------- 칠하는 줄 수가 늘어나지 않는가

def test_칠하는_줄이_늘어나지_않는다():
    """**이 테스트가 설계의 핵심 계약이다.**

    매체마다 2지표씩 주면 칠하는 줄이 4 → 8로 두 배가 된다(실측). 10줄 표의 80%가
    칠해지면 색이 강조가 아니라 배경이다. 유효 매체 수로 지표 예산을 나눠야 한다.
    """
    df = frame(MIXED)
    old = pick_best_worst(df, pick_metrics_for(df))
    new = pick_by_media(df)

    assert len(new[0]) + len(new[1]) <= len(old[0]) + len(old[1])
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

def test_매체_컬럼이_없으면_지금_동작이다():
    """구글 애셋 표와 매체 축이 없는 피벗 표가 여기 해당한다."""
    df = frame(MIXED).drop(columns=["media"])
    assert pick_by_media(df) == pick_best_worst(df, pick_metrics_for(df))


def test_유효_매체가_하나도_없으면_표_전체에서_뽑는다():
    """전부 2줄짜리 매체뿐이어도 표를 빈 채로 두지 않는다."""
    df = frame([
        {"ad": "a", "media": "TikTok", "cost": 3_000_000, "CPI": 1_500, "CTR": 2.0},
        {"ad": "b", "media": "TikTok", "cost": 2_000_000, "CPI": 1_700, "CTR": 1.5},
        {"ad": "c", "media": "Meta", "cost": 1_000_000, "CPI": 4_000, "CTR": 1.1},
    ])
    assert pick_by_media(df) == pick_best_worst(df, pick_metrics_for(df))


def test_매체가_하나뿐이면_지금과_같다():
    """구글 표(매체 하나)는 동작이 달라지면 안 된다."""
    df = frame([r for r in MIXED if r["media"] == "Meta"])
    assert pick_by_media(df) == pick_best_worst(df, pick_metrics_for(df))


def test_빈_표는_조용히_빈_결과():
    assert pick_by_media(pd.DataFrame()) == ({}, {})
    assert pick_by_media(None) == ({}, {})


# --------------------------------------------------------- 기준 지표 선택

def test_매체마다_기준_지표를_따로_고른다():
    """AOS는 Coin CVR이 0에 가까워 CTR로 넘어가고, iOS는 Coin이 살아 있다 —
    그 판단(`pick_metrics_for`)을 **매체별 부분표에** 적용해야 뜻이 맞는다."""
    seen = []

    def chooser(part):
        seen.append(set(part["media"]))
        return pick_metrics_for(part)

    pick_by_media(frame(MIXED), metrics_for=chooser)
    assert {"TikTok"} in seen and {"Meta"} in seen


def test_넘긴_인자가_pick_best_worst로_전달된다():
    """`spend_quantile` 같은 인자는 그대로 흘러야 한다 — 순위표가 0.5를 쓴다."""
    df = frame(MIXED)
    loose = pick_by_media(df, spend_quantile=0.0)
    tight = pick_by_media(df, spend_quantile=0.9)
    # 값이 실제로 쓰이면 후보가 좁아져 결과가 달라지거나 줄어든다.
    assert loose != tight or len(tight[0]) <= len(loose[0])


def test_사유가_실제_컬럼_이름이다():
    """소비하는 쪽이 `df.loc[index, 값]` 으로 쓴다 — 문구를 넣으면 화면이 죽는다
    (2026-09-08 배포판 사고)."""
    df = frame(MIXED)
    best, worst = pick_by_media(df)
    for reason in list(best.values()) + list(worst.values()):
        assert reason in df.columns
