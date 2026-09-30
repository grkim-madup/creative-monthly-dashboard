# -*- coding: utf-8 -*-
"""우수·저조 선정 규칙 — **정렬 기준별 순위 합산 + 컷** (2026-10-01 재정립).

규리님: *"CPI, Coin CVR, CTR, 소진을 골고루 고려해서 뽑아야 해. 어느 하나가 너무
부족하면 Best가 안 되고, 너무 좋으면 Worst가 안 되도록."*

각 테스트는 9월 실데이터 시뮬레이션에서 실제로 문제가 된 장면을 축소 재현한다
(재현 도구 `tools/sim_pick_composite.py`).
"""
import pandas as pd

from creative_data import (
    PICK_CUT_RANKS,
    PICK_MIN_SPEND_SHARE,
    PICK_PROFILES,
    PICK_REL_GAP,
    PICK_SPEND_FLOOR_SHARE,
    PICK_TAIL_STEPS,
    pick_basis,
    pick_by_media,
    pick_profile,
)


def tiktok(rows: list[dict]) -> pd.DataFrame:
    """한 매체(TikTok) 표. 비율은 소수로 저장한다(CTR 0.15 = 15%)."""
    return pd.DataFrame([{"media": "TikTok", **r} for r in rows])


def names(df: pd.DataFrame, picks: dict) -> set:
    return {df.loc[i, "ad"] for i in picks}


# ----------------------------------------------------------- 정렬 기준 프로파일

def test_정렬_기준이_지표_순서를_정한다():
    """규리님: *"인스톨로 가면 CPI > Read CVR > CTR, PU로 가면 PU > CPI > CTR."*"""
    order = {key: [c for c, _, _ in value] for key, value in PICK_PROFILES.items()}
    assert order["total install"] == ["CPI", "D0 read CVR", "CTR"]
    assert order["D0 coin"] == ["D0 coin CVR", "CPI", "CTR"]
    assert order["D0 read"] == ["D0 read CVR", "CPI", "CTR"]
    assert order["cost"] == order["total install"]
    # 구글은 Coin CVR이 없어 인앱 CPA로 대체한다.
    assert order["in_app_action"] == ["인앱 CPA", "CPI", "CTR"]


def test_가중치는_2_1_반():
    for profile in PICK_PROFILES.values():
        assert [w for _, _, w in profile] == [2.0, 1.0, 0.5]


def test_모르는_정렬_기준은_인스톨과_같다():
    """피벗 순위표는 `rank_by`가 지표 이름(`CPI`)이거나 비어 있다."""
    assert pick_profile(None) == PICK_PROFILES["total install"]
    assert pick_profile("CPI") == PICK_PROFILES["total install"]


def test_상수():
    assert PICK_TAIL_STEPS == (0.30, 0.40, 0.50)
    assert PICK_REL_GAP == 0.10
    assert PICK_SPEND_FLOOR_SHARE == 0.20
    assert PICK_MIN_SPEND_SHARE == 0.02
    assert PICK_CUT_RANKS == 2


# 9월 AOS·인스톨 TikTok 10줄을 축소한 표. `cpi1`은 CPI가 압도적 1위인데 Read CVR이
# 꼴찌다(중앙값 대비 약 4% 낮음) — 실데이터 `10398`의 성질이다.
# `ctr_star`는 CPI 중간 · CTR 1위 — 실데이터 `5923`의 성질이다.
AOS_INSTALL = [
    {"ad": "cpi1", "cost": 2_870_000, "CPI": 1_039, "D0 read CVR": 0.4821, "CTR": 0.1577},
    {"ad": "good2", "cost": 3_020_000, "CPI": 1_424, "D0 read CVR": 0.5078, "CTR": 0.1758},
    {"ad": "mid3", "cost": 2_830_000, "CPI": 1_494, "D0 read CVR": 0.4966, "CTR": 0.1561},
    {"ad": "ctr_star", "cost": 2_770_000, "CPI": 1_532, "D0 read CVR": 0.4854, "CTR": 0.3798},
    {"ad": "mid5", "cost": 2_560_000, "CPI": 1_532, "D0 read CVR": 0.5352, "CTR": 0.2738},
    {"ad": "big_bad", "cost": 10_350_000, "CPI": 1_573, "D0 read CVR": 0.5026, "CTR": 0.1443},
    {"ad": "mid7", "cost": 3_940_000, "CPI": 1_578, "D0 read CVR": 0.5678, "CTR": 0.2662},
    {"ad": "bad8", "cost": 4_390_000, "CPI": 1_603, "D0 read CVR": 0.4927, "CTR": 0.1859},
    {"ad": "mid9", "cost": 3_770_000, "CPI": 1_643, "D0 read CVR": 0.5688, "CTR": 0.3430},
    {"ad": "cpi_worst", "cost": 4_760_000, "CPI": 1_690, "D0 read CVR": 0.5936, "CTR": 0.3544},
]


# -------------------------------------------------------------- 한 지표만 튀면

def test_CTR만_1위인_소재는_우수가_아니다():
    """9월 `5923` — CPI 중간인데 CTR 1위라 옛 규칙에서 `우수 · CTR`이었다."""
    df = tiktok(AOS_INSTALL)
    best, _ = pick_by_media(df, rank_metric="total install")
    assert "ctr_star" not in names(df, best)


def test_CPI_1위는_2순위가_조금_낮아도_우수다():
    """`10398` 회귀 — 순위 컷만 두었을 때 Read CVR 꼴찌(중앙값보다 4% 낮음)라 빠졌다.

    차이가 `PICK_REL_GAP`(10%)보다 작으면 컷에 걸리지 않아야 한다.
    """
    df = tiktok(AOS_INSTALL)
    best, _ = pick_by_media(df, rank_metric="total install")
    assert "cpi1" in names(df, best)


def test_CPI_1위는_Read_기준_표에서도_저조가_아니다():
    """컷을 아예 없애면 D0 Read 표에서 `10398`이 저조로 찍혔다 — 가중치만으로는 못 막는다."""
    df = tiktok(AOS_INSTALL)
    _, worst = pick_by_media(df, rank_metric="D0 read")
    assert "cpi1" not in names(df, worst)


def test_한_지표가_크게_나쁘면_점수가_좋아도_우수가_아니다():
    """1순위가 1등이어도 2순위가 중앙값보다 10% 넘게 나쁘고 하위 30%면 탈락."""
    rows = [
        {"ad": "lopsided", "cost": 5_000_000, "CPI": 1_000, "D0 read CVR": 0.30, "CTR": 0.2},
        *[{"ad": f"n{i}", "cost": 4_000_000, "CPI": 1_400 + 20 * i,
           "D0 read CVR": 0.50 + 0.01 * i, "CTR": 0.2} for i in range(6)],
    ]
    df = tiktok(rows)
    best, _ = pick_by_media(df, rank_metric="total install")
    assert "lopsided" not in names(df, best)


def test_한_지표가_크게_좋으면_저조가_아니다():
    """9월 AOS·D0 Coin의 Meta `8230_VoTrailer` — CPI는 Meta 1위, Coin CVR은 꼴찌."""
    rows = [
        {"ad": "cheap_nocoin", "cost": 5_000_000, "CPI": 2_600, "D0 coin CVR": 0.0057, "CTR": 0.008},
        *[{"ad": f"n{i}", "cost": 4_000_000, "CPI": 4_000 + 300 * i,
           "D0 coin CVR": 0.020 + 0.003 * i, "CTR": 0.008} for i in range(5)],
    ]
    df = pd.DataFrame([{"media": "Meta", **r} for r in rows])
    _, worst = pick_by_media(df, rank_metric="D0 coin")
    assert "cheap_nocoin" not in names(df, worst)


# ----------------------------------------------------------------- 사유 표시

def test_사유는_1_2순위_지표에서만():
    """3순위 CTR이 `선정` 컬럼에 찍히면 "CTR로 뽑았다"로 읽힌다(규리님 2026-10-01)."""
    df = tiktok(AOS_INSTALL)
    for rank in ("total install", "D0 read", "cost"):
        best, worst = pick_by_media(df, rank_metric=rank)
        reasons = set(best.values()) | set(worst.values())
        assert "CTR" not in reasons, rank
        assert reasons <= set(pick_basis(df, rank)), rank


def test_사유는_실제_컬럼_이름이다():
    """카드가 `df.loc[index, 값]` 으로 숫자를 꺼낸다 — 문구를 넣으면 화면이 죽는다."""
    df = tiktok(AOS_INSTALL)
    best, worst = pick_by_media(df, rank_metric="total install")
    for reason in list(best.values()) + list(worst.values()):
        assert reason in df.columns


def test_2순위가_없는_표에서_CTR이_2순위로_올라가지_않는다():
    """구글 인스톨 표에는 Read CVR이 없다. CTR이 올라가 컷·사유에 쓰이면 안 된다."""
    df = tiktok(AOS_INSTALL).drop(columns=["D0 read CVR"])
    assert pick_basis(df, "total install") == ["CPI"]
    best, worst = pick_by_media(df, rank_metric="total install")
    assert set(best.values()) | set(worst.values()) == {"CPI"}


# ---------------------------------------------------------------- 후보 자격

def test_소액_소재는_후보가_아니다():
    """9월 AOS·D0 Coin — 소진 ₩19만(표의 1.3%)짜리가 우수로 올라왔다."""
    rows = [
        {"ad": "tiny", "cost": 190_000, "CPI": 900, "D0 read CVR": 0.60, "CTR": 0.2},
        *[{"ad": f"n{i}", "cost": 3_000_000 + 100_000 * i, "CPI": 1_400 + 50 * i,
           "D0 read CVR": 0.50, "CTR": 0.2} for i in range(6)],
    ]
    df = tiktok(rows)
    best, worst = pick_by_media(df, rank_metric="total install")
    assert "tiny" not in names(df, best) | names(df, worst)


def test_매체_안_소진_하위_20퍼센트는_후보가_아니다():
    rows = [{"ad": f"n{i}", "cost": 1_000_000 * (i + 1), "CPI": 1_000 + 100 * i,
             "D0 read CVR": 0.5, "CTR": 0.2} for i in range(10)]
    df = tiktok(rows)
    best, worst = pick_by_media(df, rank_metric="total install")
    # 소진 하위 2줄(n0·n1)은 CPI가 가장 좋아도 후보가 아니다.
    assert not ({"n0", "n1"} & (names(df, best) | names(df, worst)))


def test_1순위_지표가_없는_줄은_후보가_아니다():
    """구글 인앱 액션 표에 설치 목적(ACi) 캠페인이 섞이면 인앱 CPA가 비어 있다.

    그 줄을 최악으로 치면 목적이 다른 캠페인이 저조로 찍혔다(9월 구글 iOS).
    """
    rows = [{"ad": f"aca{i}", "cost": 3_000_000 - 100_000 * i, "CPI": 3_000 + 100 * i,
             "인앱 CPA": 10_000 + 1_000 * i, "CTR": 0.005} for i in range(6)]
    rows += [{"ad": f"aci{i}", "cost": 2_000_000, "CPI": 3_500, "인앱 CPA": None,
              "CTR": 0.005} for i in range(3)]
    df = pd.DataFrame(rows)
    best, worst = pick_by_media(df, rank_metric="in_app_action")
    assert not any(n.startswith("aci") for n in names(df, best) | names(df, worst))


# ---------------------------------------------------------------- 폴백

def test_컷을_끝까지_풀지_않는다_덜_칠한다():
    """규리님 A안 — 규칙을 어기며 4줄을 채우느니 덜 칠한다.

    두 줄이 서로 한 지표씩 크게 좋고 나쁘면 누구도 우수·저조가 될 수 없다
    (9월 AOS·D0 Coin의 TikTok이 게이트 뒤 이 상태였다).
    """
    df = tiktok([
        {"ad": "a", "cost": 5_000_000, "CPI": 6_100, "D0 coin CVR": 0.0093, "CTR": 0.03},
        {"ad": "b", "cost": 2_500_000, "CPI": 3_800, "D0 coin CVR": 0.0046, "CTR": 0.008},
    ])
    best, worst = pick_by_media(df, rank_metric="D0 coin", min_rows=2)
    assert best == {} and worst == {}


def test_보통_표는_4줄을_칠한다():
    df = tiktok(AOS_INSTALL)
    best, worst = pick_by_media(df, rank_metric="total install")
    assert len(best) == 2 and len(worst) == 2
    assert not (set(best) & set(worst))


def test_동점이면_3순위가_가른다():
    """보조(3순위)의 역할은 동점 승자를 가르는 것이다(규리님 2026-09-30)."""
    rows = [{"ad": f"n{i}", "cost": 3_000_000, "CPI": 1_000 + 100 * i,
             "D0 read CVR": 0.5, "CTR": 0.2} for i in range(6)]
    rows[0]["ad"], rows[0]["CTR"] = "tie_low_ctr", 0.10
    rows.insert(1, {"ad": "tie_high_ctr", "cost": 3_000_000, "CPI": 1_000,
                    "D0 read CVR": 0.5, "CTR": 0.30})
    df = tiktok(rows)
    best, _ = pick_by_media(df, rank_metric="total install", slots=1)
    assert names(df, best) == {"tie_high_ctr"}
