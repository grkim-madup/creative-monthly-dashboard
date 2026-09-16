"""묶음별 순위표의 **우수·저조 줄 선정**.

이 규칙에는 테스트가 하나도 없었다 — 진입점(`render_ranked_table`) 안에 있어서
import할 수 없었기 때문이다(`spend_pool`·`pick_best_worst`를 `creative_data.py`로
옮긴 것과 같은 이유). 광고주가 보는 화면에서 "무엇이 우수인가"를 정하는 자리라
여기서 못 박는다.
"""

from __future__ import annotations

import pandas as pd

from creative_data import (
    RANK_PAINT_SHARE,
    RANK_SPEND_QUANTILE,
    rank_picks,
    rank_slots,
)


def frame(rows: list[dict]) -> pd.DataFrame:
    """장르 표 한 묶음. 실제 `pivot_frame` 출력과 같은 컬럼 이름을 쓴다."""
    base = {"genre_group": "", "cost": 0.0, "impression": 0, "total install": 0,
            "CTR": 0.0, "CPI": 0.0, "D0 read CVR": 0.0, "D0 coin CVR": 0.0}
    return pd.DataFrame([{**base, **r} for r in rows])


def genres(picked: dict, table: pd.DataFrame) -> set[str]:
    return {table.loc[i, "genre_group"] for i in picked}


# ------------------------------------------------------------------ 슬롯 수

def test_묶음이_작으면_칠하지_않는다():
    """3줄에서 2줄을 칠하면 안 칠한 한 줄이 오히려 눈에 띈다."""
    assert rank_slots(0) == 0
    assert rank_slots(3) == 0
    assert rank_slots(4) == 0


def test_다섯_줄부터_한_쌍():
    assert rank_slots(5) == 1
    assert rank_slots(9) == 1


def test_열_줄부터_두_쌍():
    assert rank_slots(10) == 2
    assert rank_slots(40) == 2      # 상한은 2쌍 — 2번 섹션과 같은 밀도


def test_칠하는_비율이_2번_섹션을_넘지_않는다():
    """2번 섹션은 10줄에 4줄을 칠한다. 그 밀도를 넘으면 색이 배경이 된다."""
    assert RANK_PAINT_SHARE == 0.40
    for n in range(2, 60):
        assert rank_slots(n) * 2 <= max(n * RANK_PAINT_SHARE, 0) + 1e-9


# ------------------------------------------------------- 소진 볼륨을 본다

def test_소액_집행이_우수로_뽑히지_않는다():
    """실측 8월 `Meta·AOS` — 소진 ₩15,895·설치 7건짜리가 우수로 칠해졌다.

    CPI만 보면 그 줄이 1등이지만, 광고주에게 "이 장르가 가장 좋다"로 나간다.
    """
    table = frame([
        {"genre_group": "대형", "cost": 11_175_710, "total install": 3_880,
         "CPI": 2_880, "CTR": 0.004, "impression": 1_000_000},
        {"genre_group": "중형", "cost": 10_609_390, "total install": 3_086,
         "CPI": 3_438, "CTR": 0.003, "impression": 900_000},
        {"genre_group": "소액", "cost": 15_895, "total install": 7,
         "CPI": 2_271, "CTR": 0.005, "impression": 1_000},
        {"genre_group": "보통1", "cost": 7_267_113, "total install": 1_194,
         "CPI": 6_086, "CTR": 0.003, "impression": 700_000},
        {"genre_group": "보통2", "cost": 862_590, "total install": 176,
         "CPI": 4_901, "CTR": 0.003, "impression": 90_000},
    ])
    best, _worst = rank_picks(table, "genre_group", "CPI")
    assert "소액" not in genres(best, table)
    assert genres(best, table) == {"대형"}


def test_집행하지_않은_줄은_아예_빠진다():
    """소진 ₩0·설치 6건이면 CPI가 0으로 찍혀 1등이 된다(실측 사고)."""
    table = frame([
        {"genre_group": "미집행", "cost": 0, "total install": 6, "CPI": 0},
        {"genre_group": "A", "cost": 5_000_000, "total install": 2_000, "CPI": 2_500},
        {"genre_group": "B", "cost": 4_000_000, "total install": 1_000, "CPI": 4_000},
        {"genre_group": "C", "cost": 3_000_000, "total install": 600, "CPI": 5_000},
        {"genre_group": "D", "cost": 2_000_000, "total install": 300, "CPI": 6_600},
        {"genre_group": "E", "cost": 1_000_000, "total install": 120, "CPI": 8_300},
    ])
    best, worst = rank_picks(table, "genre_group", "CPI")
    assert "미집행" not in genres(best, table) | genres(worst, table)


def test_미분류는_순위에_넣지_않는다():
    """분류가 안 된 것이지 하나의 분류가 아니다."""
    table = frame([
        {"genre_group": "미분류", "cost": 9_000_000, "total install": 9_000, "CPI": 1_000},
        {"genre_group": "A", "cost": 5_000_000, "total install": 2_000, "CPI": 2_500},
        {"genre_group": "B", "cost": 4_000_000, "total install": 1_000, "CPI": 4_000},
        {"genre_group": "C", "cost": 3_000_000, "total install": 600, "CPI": 5_000},
        {"genre_group": "D", "cost": 2_000_000, "total install": 300, "CPI": 6_600},
    ])
    best, worst = rank_picks(table, "genre_group", "CPI")
    assert "미분류" not in genres(best, table) | genres(worst, table)


def test_우수와_저조가_겹치지_않는다():
    table = frame([
        {"genre_group": chr(65 + i), "cost": 10_000_000 - i * 500_000,
         "total install": 3_000 - i * 100, "CPI": 2_000 + i * 400,
         "CTR": 0.02 + i * 0.01, "impression": 500_000}
        for i in range(12)
    ])
    best, worst = rank_picks(table, "genre_group", "CPI")
    assert set(best) and set(worst)
    assert not (set(best) & set(worst))


def test_소진_컬럼이_없으면_지표로만_한_쌍():
    """값 목록에서 소진액을 빼도 표가 색을 완전히 잃지는 않는다."""
    table = frame([{"genre_group": g, "CPI": cpi, "total install": 100}
                   for g, cpi in [("A", 1_000), ("B", 2_000), ("C", 3_000),
                                  ("D", 4_000), ("E", 5_000)]]).drop(columns=["cost"])
    best, worst = rank_picks(table, "genre_group", "CPI")
    assert genres(best, table) == {"A"} and genres(worst, table) == {"E"}


def test_빈_표는_조용히_빈_결과():
    empty, _ = rank_picks(frame([]), "genre_group", "CPI")
    assert empty == {}
    assert rank_picks(None, "genre_group", "CPI") == ({}, {})


def test_소진_중위값_아래는_색칠_후보가_아니다():
    """피벗 묶음에는 최소 소진액 전처리가 없다 — 여기서 그 전제를 복원한다.

    실측 8월 `TikTok·iOS`: 이 문턱이 없으면 우수가 소진 ₩169,099짜리로 뽑혔다.
    """
    assert RANK_SPEND_QUANTILE == 0.5
    table = frame([
        {"genre_group": "큰거", "cost": 10_000_000, "total install": 2_000,
         "CPI": 5_000, "impression": 900_000},
        {"genre_group": "중간", "cost": 5_000_000, "total install": 800,
         "CPI": 6_250, "impression": 500_000},
        {"genre_group": "중간2", "cost": 4_000_000, "total install": 500,
         "CPI": 8_000, "impression": 400_000},
        {"genre_group": "작은거", "cost": 120_000, "total install": 40,
         "CPI": 3_000, "impression": 9_000},
        {"genre_group": "작은거2", "cost": 90_000, "total install": 25,
         "CPI": 3_600, "impression": 7_000},
    ])
    best, worst = rank_picks(table, "genre_group", "CPI")
    picked = genres(best, table) | genres(worst, table)
    assert not (picked & {"작은거", "작은거2"}), picked
    # CPI가 가장 낮은 것은 `작은거`(₩3,000)지만, 소진이 중위값 아래라 후보가 아니다.
    assert genres(best, table) == {"큰거"}


def test_표에서_줄을_숨기지는_않는다():
    """색칠 후보만 좁힌다 — 집계·행 수는 건드리지 않는다."""
    table = frame([
        {"genre_group": f"G{i}", "cost": 1_000_000 * (i + 1),
         "total install": 100 * (i + 1), "CPI": 2_000 + i * 300,
         "impression": 100_000}
        for i in range(6)
    ])
    before = table.copy()
    rank_picks(table, "genre_group", "CPI")
    pd.testing.assert_frame_equal(table, before)
