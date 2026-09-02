"""표 컬럼 커스터마이즈 — 차원을 빼면 **가려지는 게 아니라 다시 계산된다**.

"매체 컬럼을 안 쓴다고 하면 단순 가리기만 되는 게 아니라 피벗처럼 컬럼에 맞게 계산이
바뀌어야 한다"는 요구에서 나왔다. 그래서 컬럼 선택이 곧 `GROUP BY`다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from creative_data import (
    DIMENSION_COLUMNS,
    DISPLAY_COLUMNS,
    METRIC_COLUMNS,
    SELECTABLE_COLUMNS,
    add_derived_metrics,
    aggregate_by,
    grouping_keys,
    pick_columns,
)


def raw() -> pd.DataFrame:
    """소재 하나가 매체 두 곳에 있다 — 매체를 빼면 합쳐져야 한다."""
    return add_derived_metrics(pd.DataFrame([
        {"ad": "a1", "media": "TikTok", "os": "AOS", "cost": 300,
         "impression": 1000, "click": 100, "total install": 3,
         "D0 read": 2, "D0 coin": 0, "D7 coin": 0},
        {"ad": "a1", "media": "Meta", "os": "AOS", "cost": 700,
         "impression": 2000, "click": 40, "total install": 1,
         "D0 read": 1, "D0 coin": 0, "D7 coin": 0},
    ]))


class TestVocabulary:
    def test_dimensions_and_metrics_do_not_overlap(self):
        assert not set(DIMENSION_COLUMNS) & set(METRIC_COLUMNS)

    def test_selectable_is_the_union_in_order(self):
        assert SELECTABLE_COLUMNS == DIMENSION_COLUMNS + METRIC_COLUMNS

    def test_media_is_a_dimension_not_a_metric(self):
        """매체가 지표로 분류되면 빼도 숫자가 안 바뀐다 — 요구사항이 깨진다."""
        assert "media" in DIMENSION_COLUMNS


class TestGroupingKeys:
    def test_chosen_dimensions_become_the_group_by(self):
        keys = grouping_keys(["ad", "media", "cost"], ["ad"], raw().columns)
        assert keys == ["ad", "media"]

    def test_dropping_a_dimension_drops_it_from_the_group_by(self):
        keys = grouping_keys(["ad", "cost"], ["ad"], raw().columns)
        assert keys == ["ad"]

    def test_metrics_never_become_keys(self):
        keys = grouping_keys(["ad", "cost", "CPI", "CTR"], ["ad"], raw().columns)
        assert keys == ["ad"]

    def test_always_key_is_restored_when_removed(self):
        assert "ad" in grouping_keys(["media"], ["ad"], raw().columns)

    def test_always_key_comes_first(self):
        keys = grouping_keys(["media", "os"], ["ad"], raw().columns)
        assert keys[0] == "ad"

    def test_key_absent_from_the_data_is_not_invented(self):
        thin = raw()[["ad", "cost"]]
        assert grouping_keys(["ad", "media"], ["ad"], thin.columns) == ["ad"]

    def test_empty_choice_falls_back_to_the_default_set(self):
        assert grouping_keys([], ["ad"], raw().columns) == ["ad", "media"]


class TestReaggregation:
    """실제로 숫자가 다시 계산되는지 — 이게 이 기능의 핵심이다."""

    def aggregated(self, chosen: list[str]) -> pd.DataFrame:
        keys = grouping_keys(chosen, ["ad"], raw().columns)
        return aggregate_by(raw(), keys)

    def test_with_media_the_creative_is_split_into_rows(self):
        assert len(self.aggregated(["ad", "media", "CPI"])) == 2

    def test_without_media_the_creative_collapses_to_one_row(self):
        assert len(self.aggregated(["ad", "CPI"])) == 1

    def test_ratios_are_recomputed_from_the_combined_totals(self):
        """행별 CPI를 평균내면 안 된다 — 합계에서 다시 계산해야 한다."""
        combined = self.aggregated(["ad", "CPI"]).iloc[0]
        assert combined["cost"] == 1000
        assert combined["total install"] == 4
        assert combined["CPI"] == pytest.approx(250)          # 1000 / 4
        split = self.aggregated(["ad", "media", "CPI"])
        assert split["CPI"].mean() != pytest.approx(250)      # 100 과 700 의 평균 = 400


class TestPickColumns:
    def test_no_choice_falls_back_to_the_default_set(self):
        data = aggregate_by(raw(), ["ad", "media"])
        assert pick_columns(data, None) == [
            c for c in SELECTABLE_COLUMNS if c in DISPLAY_COLUMNS and c in data.columns]

    def test_empty_choice_also_falls_back(self):
        """빈 목록을 '컬럼 0개'로 해석하면 표가 통째로 사라진다."""
        data = aggregate_by(raw(), ["ad", "media"])
        assert pick_columns(data, []) == pick_columns(data, None)

    def test_order_follows_the_canonical_list_not_the_click_order(self):
        data = aggregate_by(raw(), ["ad", "media"])
        assert pick_columns(data, ["CPI", "ad", "cost"]) == ["ad", "cost", "CPI"]

    def test_a_dropped_dimension_is_absent_from_the_frame_so_it_cannot_show(self):
        """가리기가 아니라 다시 계산 — 프레임에 컬럼 자체가 없다."""
        data = aggregate_by(raw(), ["ad"])
        assert "media" not in pick_columns(data, ["ad", "media", "cost"])

    def test_always_column_is_restored_when_the_user_removes_it(self):
        data = aggregate_by(raw(), ["ad", "media"])
        assert "ad" in pick_columns(data, ["CPI"], always=["ad"])

    def test_always_column_comes_first(self):
        data = aggregate_by(raw(), ["ad", "media"])
        assert pick_columns(data, ["CPI"], always=["media"])[0] == "media"

    def test_no_duplicates_even_if_chosen_twice(self):
        data = aggregate_by(raw(), ["ad", "media"])
        result = pick_columns(data, ["CPI", "CPI", "ad"], always=["ad"])
        assert len(result) == len(set(result))


class TestRowValueBoundary:
    """표에서 행(묶는 기준)과 값(지표)의 경계를 어디에 세우는가.

    `report_table`이 `value_start` 컬럼에만 굵은 경계선을 세운다. 그 자리를 고르는
    규칙(= 헤더 순서상 행이 아닌 첫 컬럼)을 여기서 고정한다.
    """

    def boundary(self, headers: list[str], dims: set[str]) -> str | None:
        # `render_table`이 쓰는 것과 같은 규칙. 진입점은 import할 수 없어 재현한다.
        present = {c for c in dims if c in headers}
        return next((c for c in headers if c not in present), None) if present else None

    def test_boundary_is_the_first_non_row_column(self):
        assert self.boundary(["소재명", "매체", "소진액", "CPI"],
                             {"소재명", "매체"}) == "소진액"

    def test_one_row_column(self):
        assert self.boundary(["매체", "소진액"], {"매체"}) == "소진액"

    def test_no_row_columns_means_no_boundary(self):
        """행 컬럼이 없으면 경계도 없다 — 없는 선을 그으면 표가 어긋나 보인다."""
        assert self.boundary(["소진액", "CPI"], set()) is None

    def test_row_column_absent_from_headers_is_ignored(self):
        """행에서 뺀 구분은 프레임에 컬럼이 없다 — 그걸로 경계를 잡으면 안 된다."""
        assert self.boundary(["소재명", "소진액"], {"소재명", "매체"}) == "소진액"

    def test_all_columns_are_row_columns(self):
        assert self.boundary(["소재명", "매체"], {"소재명", "매체"}) is None
