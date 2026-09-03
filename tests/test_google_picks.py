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


def test_pick_metrics_is_the_single_source():
    """표 색칠과 소재 카드가 **같은 함수**로 기준을 얻어야 한다.

    예전에는 카드 쪽만 `인앱 CPA`로 고정돼 있어서, 표는 CPI·CTR로 4줄을 칠하는데
    카드는 CPI 하나만 잡아 2개만 나왔다. 같은 화면에서 색칠과 카드가 다른 소재를
    가리키면 어느 쪽이 맞는지 알 수 없다.
    """
    import pathlib

    # ⚠ madup.app 배포판은 진입점 이름이 `app.py`다(포털이 그걸 요구한다).
    #    파일명을 하나만 박아 두면 그쪽에서 테스트가 깨져 push가 막힌다(실제로 막혔다).
    root = pathlib.Path(__file__).resolve().parent.parent
    entry = next((root / name for name in ("creative_dashboard.py", "app.py")
                  if (root / name).exists()), None)
    assert entry is not None, "진입점을 찾지 못했습니다"
    source = entry.read_text(encoding="utf-8")
    # 구글 경로에 지표 목록을 손으로 적어 둔 곳이 없어야 한다.
    assert '[("CPI", False), ("인앱 CPA", False)]' not in source
    # 표(`render_google_table`)와 카드(`render_google_material_cards`) 두 곳.
    # 표(`render_google_table`의 `view`)와 카드(`render_google_material_cards`
    # 의 `df`) 두 곳이 각각 이 함수로 기준을 얻는다.
    assert "google_pick_metrics(df)" in source
    assert "google_pick_metrics(view)" in source


def test_table_and_cards_pick_the_same_creatives():
    from creative_data import pick_best_worst

    top = table(10, cpa_rows=1)
    metrics = google_pick_metrics(top)
    table_best, table_worst = pick_best_worst(top, metrics)
    card_best, card_worst = pick_best_worst(top, google_pick_metrics(top))
    assert table_best == card_best
    assert table_worst == card_worst
    assert len(card_best) + len(card_worst) == 4
