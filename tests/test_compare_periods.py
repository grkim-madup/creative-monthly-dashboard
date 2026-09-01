"""기간 비교 뷰 — 두 기간을 나란히 놓고 증감을 붙인 표.

⚠ 이 표의 유일한 위험 지점은 **증감 단위**다. 비율(CTR·CVR)은 `%p`, 금액·건수는 `%`인데
한 규칙으로 뭉개면 광고주에게 틀린 숫자가 그대로 간다(49%→53%을 "+8.2%"로 쓰면
8.2%p 오른 것으로 읽는다). 그래서 여기서 고정한다.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from creative_data import (
    COMPARE_DEFAULT_METRICS,
    RATIO_METRICS,
    add_derived_metrics,
    compare_periods,
    delta_unit,
)

BEFORE = {"label": "방영 전", "months": [3, 4]}
AFTER = {"label": "방영 후", "months": [5, 6]}


def frame() -> pd.DataFrame:
    """3~4월: 노출 1000 / 클릭 100(CTR 10%) / 설치 10 / 소진 1000
       5~6월: 노출 1000 / 클릭 200(CTR 20%) / 설치 20 / 소진 1500"""
    rows = [
        {"month": 3, "cost": 400, "impression": 400, "click": 40, "total install": 4,
         "D0 read": 2, "D0 coin": 0, "D7 coin": 0},
        {"month": 4, "cost": 600, "impression": 600, "click": 60, "total install": 6,
         "D0 read": 3, "D0 coin": 0, "D7 coin": 0},
        {"month": 5, "cost": 700, "impression": 500, "click": 100, "total install": 10,
         "D0 read": 6, "D0 coin": 1, "D7 coin": 0},
        {"month": 6, "cost": 800, "impression": 500, "click": 100, "total install": 10,
         "D0 read": 6, "D0 coin": 1, "D7 coin": 0},
    ]
    return add_derived_metrics(pd.DataFrame(rows))


def row(table: pd.DataFrame, label: str) -> pd.Series:
    return table[table["지표"] == label].iloc[0]


class TestDeltaUnit:
    def test_ratio_metrics_use_percentage_points(self):
        for metric in ("CTR", "D0 read CVR", "D0 coin CVR", "D7 coin CVR"):
            assert delta_unit(metric) == "%p"

    def test_money_and_count_metrics_use_percent(self):
        for metric in ("cost", "impression", "click", "total install", "CPI", "CPC",
                       "D0 read", "D0 coin"):
            assert delta_unit(metric) == "%"

    def test_every_default_metric_has_a_unit(self):
        for metric in COMPARE_DEFAULT_METRICS:
            assert delta_unit(metric) in ("%", "%p")

    def test_ratio_set_matches_the_percent_columns_the_tables_format(self):
        """비율 목록이 표 포맷과 어긋나면 한쪽만 고쳐진 채로 배포된다."""
        assert RATIO_METRICS == {"CTR", "D0 read CVR", "D0 coin CVR", "D7 coin CVR"}


class TestComparePeriods:
    def test_accumulates_each_period(self):
        table = compare_periods(frame(), [BEFORE, AFTER])
        assert row(table, "소진액")["방영 전"] == 1000
        assert row(table, "소진액")["방영 후"] == 1500

    def test_money_delta_is_a_relative_change_fraction(self):
        """1000 → 1500 은 +50%. `relative_change`와 같은 스케일(0.5)이어야 한다."""
        assert row(table_of(), "소진액")["증감"] == pytest.approx(0.5)

    def test_ratio_delta_is_a_point_difference_not_a_ratio(self):
        """CTR 10% → 20% 는 **+10%p**다. 상대 변화율(+100%)로 쓰면 안 된다."""
        ctr = row(table_of(), "CTR")
        assert ctr["방영 전"] == pytest.approx(0.10)
        assert ctr["방영 후"] == pytest.approx(0.20)
        assert ctr["증감"] == pytest.approx(10.0)
        assert ctr["단위"] == "%p"

    def test_ratios_are_recomputed_from_the_period_total_not_averaged(self):
        """월별 비율을 평균내면 안 된다 — 기간 합계에서 다시 계산해야 한다."""
        assert row(table_of(), "CTR")["방영 전"] == pytest.approx(100 / 1000)

    def test_missing_period_is_nan_not_zero(self):
        """데이터가 없는 기간을 0으로 채우면 '집행 안 함'과 구분이 사라지고 -100%가 찍힌다."""
        table = compare_periods(
            frame(), [{"label": "없는 기간", "months": [11]}, AFTER])
        assert math.isnan(row(table, "소진액")["없는 기간"])
        assert math.isnan(row(table, "소진액")["증감"])

    def test_empty_month_list_is_treated_as_no_data(self):
        table = compare_periods(frame(), [{"label": "비움", "months": []}, AFTER])
        assert math.isnan(row(table, "소진액")["비움"])

    def test_duplicate_labels_are_disambiguated(self):
        """같은 라벨을 두 번 쓰면 열이 하나로 뭉개진다 — 사람이 붙이는 값이라 실제로 일어난다."""
        table = compare_periods(
            frame(), [{"label": "같음", "months": [3]}, {"label": "같음", "months": [5]}])
        assert "같음 (A)" in table.columns and "같음 (B)" in table.columns

    def test_requires_exactly_two_periods(self):
        with pytest.raises(ValueError):
            compare_periods(frame(), [BEFORE])
        with pytest.raises(ValueError):
            compare_periods(frame(), [BEFORE, AFTER, BEFORE])

    def test_custom_metric_list_controls_rows_and_order(self):
        table = compare_periods(frame(), [BEFORE, AFTER], metrics=["CPI", "cost"])
        assert list(table["지표"]) == ["CPI", "소진액"]

    def test_row_order_follows_the_default_metric_list(self):
        table = compare_periods(frame(), [BEFORE, AFTER])
        assert list(table["지표"])[:3] == ["소진액", "노출", "클릭"]


def table_of() -> pd.DataFrame:
    return compare_periods(frame(), [BEFORE, AFTER])
