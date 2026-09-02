"""피벗 — 행(묶는 기준) / 값(지표) / 필터(범위).

구글 시트 피벗 편집기와 같은 모델이다. 예전에는 이 셋이 `분석 축` · `표시할 컬럼` ·
`조건`으로 흩어져 있어서 하나를 만지면 다른 쪽과 역할이 겹쳐 보였다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from creative_data import (
    DEFAULT_PIVOT_ROWS,
    PIVOT_ROW_FIELDS,
    add_derived_metrics,
    normalize_rows,
    pivot_frame,
)


def frame() -> pd.DataFrame:
    """소재 2개 × 매체 2곳. a1은 태그가 둘(text·thumb), a2는 하나(text)."""
    return add_derived_metrics(pd.DataFrame([
        {"ad": "a1", "media": "TikTok", "format": "VID", "creative_type": "Highlight",
         "extra_info": "text-thumb", "cost": 300, "impression": 1000, "click": 100,
         "total install": 3, "D0 read": 2, "D0 coin": 0, "D7 coin": 0},
        {"ad": "a1", "media": "Meta", "format": "VID", "creative_type": "Highlight",
         "extra_info": "text-thumb", "cost": 700, "impression": 2000, "click": 40,
         "total install": 1, "D0 read": 1, "D0 coin": 0, "D7 coin": 0},
        {"ad": "a2", "media": "TikTok", "format": "IMG", "creative_type": "Carousel",
         "extra_info": "text", "cost": 100, "impression": 500, "click": 25,
         "total install": 1, "D0 read": 1, "D0 coin": 0, "D7 coin": 0},
    ]))


class TestNormalizeRows:
    def test_plain_strings_are_accepted(self):
        assert normalize_rows(["ad", "media"]) == [
            {"field": "ad", "values": []}, {"field": "media", "values": []}]

    def test_duplicate_fields_are_dropped(self):
        """같은 축으로 두 번 묶을 수는 없다."""
        assert [r["field"] for r in normalize_rows(["ad", "ad"])] == ["ad"]

    def test_unknown_fields_are_dropped(self):
        assert normalize_rows(["ad", "cost", "no_such"]) == [{"field": "ad", "values": []}]

    def test_order_is_preserved(self):
        assert [r["field"] for r in normalize_rows(["media", "ad"])] == ["media", "ad"]

    def test_values_are_kept_as_strings(self):
        assert normalize_rows([{"field": "media", "values": ["Meta"]}])[0]["values"] == ["Meta"]

    def test_metric_fields_are_not_row_fields(self):
        """지표를 행에 넣으면 집계가 무의미해진다."""
        assert "cost" not in PIVOT_ROW_FIELDS and "CPI" not in PIVOT_ROW_FIELDS


class TestRows:
    def test_rows_are_the_group_by(self):
        table = pivot_frame(frame(), ["ad", "media"], ["cost"])
        assert len(table) == 3

    def test_dropping_a_row_field_reaggregates(self):
        """가리기가 아니라 다시 계산 — 이게 이 모델의 핵심이다."""
        table = pivot_frame(frame(), ["ad"], ["cost", "CPI"])
        assert len(table) == 2
        a1 = table[table["ad"] == "a1"].iloc[0]
        assert a1["cost"] == 1000
        assert a1["CPI"] == pytest.approx(250)      # 1000 / 4, 행별 평균이 아니다

    def test_ad_in_rows_makes_it_a_creative_list(self):
        assert "ad" in pivot_frame(frame(), ["ad"], ["cost"]).columns

    def test_ad_out_of_rows_makes_it_an_aggregate(self):
        table = pivot_frame(frame(), ["format"], ["cost"])
        assert "ad" not in table.columns
        assert set(table["format"]) == {"VID", "IMG"}

    def test_empty_rows_fall_back_to_the_default(self):
        """행이 비면 표가 한 줄(전체 합계)이 되어 무엇을 보는지 알 수 없다."""
        assert pivot_frame(frame(), [], ["cost"]).columns.tolist()[:2] == DEFAULT_PIVOT_ROWS

    def test_row_values_narrow_the_rows(self):
        table = pivot_frame(frame(), [{"field": "format", "values": ["VID"]}], ["cost"])
        assert list(table["format"]) == ["VID"]

    def test_missing_row_values_become_unclassified_not_dropped(self):
        data = frame().assign(creative_type=[None, None, "Carousel"])
        table = pivot_frame(data, ["creative_type"], ["cost"])
        assert "미분류" in set(table["creative_type"])
        assert table["cost"].sum() == 1100


class TestFilters:
    def test_plain_filter_applies_directly(self):
        table = pivot_frame(frame(), ["ad"], ["cost"], filters={"media": ["TikTok"]})
        assert table["cost"].sum() == 400

    def test_tag_filter_is_resolved_through_the_exploded_frame(self):
        """태그는 펼치기 전 컬럼이 아니다 — 건너뛰면 필터가 통째로 무시된다.

        실측(2026-09-02): 소진 99만이어야 하는 표가 2억으로 나왔다.
        """
        table = pivot_frame(frame(), ["ad"], ["cost"],
                            filters={"extra_info_tag": ["thumb"]})
        assert list(table["ad"]) == ["a1"]          # a2는 thumb 태그가 없다
        assert table["cost"].sum() == 1000          # 매체 두 곳 합계

    def test_tag_filter_does_not_double_count(self):
        """펼친 상태로 집계하면 태그가 둘인 소재가 두 번 세진다."""
        table = pivot_frame(frame(), ["ad"], ["cost"],
                            filters={"extra_info_tag": ["text"]})
        assert table["cost"].sum() == 1100          # 1000 + 100, 2100 이 아니다

    def test_empty_filter_values_are_ignored(self):
        assert pivot_frame(frame(), ["ad"], ["cost"], filters={"media": []})[
            "cost"].sum() == 1100

    def test_filter_that_matches_nothing_returns_an_empty_frame(self):
        assert pivot_frame(frame(), ["ad"], ["cost"],
                           filters={"media": ["없는매체"]}).empty

    def test_filters_run_before_aggregation(self):
        """부분집합에서 비율을 다시 계산해야 한다 — 전체에서 계산한 뒤 걸러내면 틀린다."""
        table = pivot_frame(frame(), ["ad"], ["CPI"], filters={"media": ["Meta"]})
        assert table.iloc[0]["CPI"] == pytest.approx(700)       # 700 / 1


class TestTagRows:
    def test_tag_as_a_row_explodes(self):
        table = pivot_frame(frame(), ["extra_info_tag"], ["cost"])
        assert set(table["extra_info_tag"]) == {"text", "thumb"}

    def test_tag_totals_exceed_the_whole_by_design(self):
        table = pivot_frame(frame(), ["extra_info_tag"], ["cost"])
        assert table["cost"].sum() > 1100       # 태그 간 비교용이지 구성비가 아니다


class TestValues:
    def test_only_chosen_metrics_are_kept(self):
        table = pivot_frame(frame(), ["ad"], ["cost", "CPI"])
        assert list(table.columns) == ["ad", "cost", "CPI"]

    def test_metric_order_follows_the_canonical_list(self):
        """고른 순서를 쓰면 표마다 컬럼 순서가 달라져 비교할 때 눈이 헤맨다."""
        table = pivot_frame(frame(), ["ad"], ["CPI", "cost"])
        assert list(table.columns) == ["ad", "cost", "CPI"]

    def test_empty_values_fall_back_to_the_default_set(self):
        assert "cost" in pivot_frame(frame(), ["ad"], []).columns

    def test_unknown_metric_is_ignored(self):
        table = pivot_frame(frame(), ["ad"], ["cost", "no_such"])
        assert list(table.columns) == ["ad", "cost"]


class TestMinCost:
    def test_min_cost_filters_after_aggregation(self):
        table = pivot_frame(frame(), ["ad"], ["cost"], min_cost=500)
        assert list(table["ad"]) == ["a1"]          # a2 는 합계 100

    def test_empty_input_is_safe(self):
        assert pivot_frame(frame().iloc[0:0], ["ad"], ["cost"]).empty
