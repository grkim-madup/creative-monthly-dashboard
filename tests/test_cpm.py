# -*- coding: utf-8 -*-
"""CPM — 1,000 노출당 비용.

⚠ 다른 단가(CPC·CPI)와 달리 **배수가 붙는다.** 나눈 뒤 1,000을 곱하는 것을
빠뜨리면 값이 1/1000로 나오는데, 광고주 눈에는 그냥 "CPM이 ₩7"로 보여서
틀린 줄 모른다.
"""
import pandas as pd
import pytest

from creative_data import (
    LOWER_IS_BETTER,
    METRIC_COLUMNS,
    add_derived_metrics,
    aggregate_by,
)


def frame(rows):
    return add_derived_metrics(pd.DataFrame(rows))


def row(media, cost, impression, click):
    return {"ad": f"a-{media}-{cost}", "media": media, "cost": cost,
            "impression": impression, "click": click, "total install": 10,
            "D0 read": 5, "D0 coin": 1, "D7 coin": 1}


def test_cpm_is_per_thousand_impressions():
    got = frame([row("Meta", 10000, 1000, 10)])
    assert got["CPM"].iloc[0] == pytest.approx(10000)   # 10,000 / 1,000 × 1000


def test_matches_hand_calculation_on_real_shape():
    """8월 틱톡 AOS 실측 모양 — 소진 ÷ 노출 × 1000."""
    got = frame([row("TikTok", 89_337_489, 12_489_000, 1_625_832)])
    expected = 89_337_489 / 12_489_000 * 1000
    assert got["CPM"].iloc[0] == pytest.approx(expected)


def test_zero_impression_is_nan_not_infinity():
    got = frame([row("Meta", 10000, 0, 0)])
    assert pd.isna(got["CPM"].iloc[0])


def test_recomputed_from_sums_not_averaged():
    """비율·단가는 절대 행별 평균을 내지 않는다 — 합계에서 다시 계산한다."""
    got = aggregate_by(frame([
        row("Meta", 1000, 1000, 10),        # CPM 1,000
        row("Meta", 9000, 9000, 90),        # CPM 1,000
    ]), ["media"])
    assert got["CPM"].iloc[0] == pytest.approx(10000 / 10000 * 1000)


def test_selectable_as_a_table_metric():
    """표의 `값` 칸에서 고를 수 있어야 한다(규리님 요청)."""
    assert "CPM" in METRIC_COLUMNS
    assert "CPC" in METRIC_COLUMNS


def test_lower_is_better():
    """빠뜨리면 단가가 올라간 것을 `우수`로 읽는다."""
    assert "CPM" in LOWER_IS_BETTER


def test_money_format_is_registered():
    """₩ 없이 소수점으로 찍히면 노출 단가가 비율처럼 보인다.

    진입점은 import할 수 없으니(화면을 그린다) 소스로 확인한다.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    entry = next((root / n for n in ("creative_dashboard.py", "app.py")
                  if (root / n).exists()))
    source = entry.read_text(encoding="utf-8")
    assert '"CPM", "CPC", "CPI"' in source     # MONEY_COLUMNS에 들어 있다
