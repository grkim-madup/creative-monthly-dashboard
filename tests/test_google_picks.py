# -*- coding: utf-8 -*-
"""구글 표의 우수·저조 선정 — **항상 각 2개씩** 나와야 한다.

예전에는 두 번째 지표가 `인앱 CPA`로 고정돼 있었다. 그런데 **설치 목적(ACi)
캠페인은 인앱 액션을 아예 잡지 않는다**(구조적으로 0건). 그래서 그 슬롯이 놀고
색칠이 3개만 나왔다 — 실측(7월) AOS·인스톨 기준 TOP10에서 인앱 CPA를 쓸 수 있는
소재가 1개뿐이었다.
"""
import pandas as pd

from creative_data import (
    GOOGLE_PICK_PRIMARY,
    google_pick_metrics,
    pick_best_worst,
)


def table(rows: int, cpa_rows: int = 0) -> pd.DataFrame:
    """구글 표 흉내. `cpa_rows`개에만 인앱 CPA가 있다."""
    return pd.DataFrame([
        {"asset": f"a{i}", "media": "Google", "cost": 1_000_000 - i * 10_000,
         "CPI": 1000 + i * 100, "CTR": 0.01 + i * 0.001,
         "인앱 CPA": (5000 + i * 100) if i < cpa_rows else None}
        for i in range(rows)
    ])


def test_cpi_is_always_the_primary():
    assert GOOGLE_PICK_PRIMARY == ("CPI", False)
    assert google_pick_metrics(table(10))[0] == ("CPI", False)


def test_falls_back_to_ctr_when_cpa_is_mostly_empty():
    """설치 목적 표가 이 경우다 — 인앱 액션이 0건이라 CPA를 못 쓴다."""
    metrics = google_pick_metrics(table(10, cpa_rows=1))
    assert [m for m, _ in metrics] == ["CPI", "CTR"]


def test_uses_cpa_when_it_covers_most_rows():
    """액션 목적 표는 CPA가 더 의미 있는 기준이다."""
    metrics = google_pick_metrics(table(10, cpa_rows=7))
    assert [m for m, _ in metrics] == ["CPI", "인앱 CPA"]


def test_half_coverage_is_the_line():
    assert [m for m, _ in google_pick_metrics(table(10, cpa_rows=5))][1] == "인앱 CPA"
    assert [m for m, _ in google_pick_metrics(table(10, cpa_rows=4))][1] == "CTR"


def test_always_picks_two_and_two():
    """색칠이 3개만 나오면 광고주가 "왜 하나가 없나"를 묻는다."""
    for cpa_rows in (0, 1, 4, 5, 7, 10):
        top = table(10, cpa_rows=cpa_rows)
        best, worst = pick_best_worst(top, google_pick_metrics(top))
        assert len(best) == 2, cpa_rows
        assert len(worst) == 2, cpa_rows


def test_picks_are_four_distinct_creatives():
    top = table(10, cpa_rows=1)
    best, worst = pick_best_worst(top, google_pick_metrics(top))
    assert len(set(best) | set(worst)) == 4


def test_empty_table_is_safe():
    assert google_pick_metrics(pd.DataFrame()) == [GOOGLE_PICK_PRIMARY]


def test_tiny_table_does_not_pick_from_two_values():
    """값이 2개뿐인 지표로 뽑으면 그 둘이 자동으로 best/worst가 되어 의미가 없다."""
    metrics = google_pick_metrics(table(10, cpa_rows=2))
    assert [m for m, _ in metrics] == ["CPI", "CTR"]
