"""차트용 데이터 준비 — 정렬 / 저볼륨 표시 / 가중 벤치마크 / 덤벨.

이게 없으면 **가장 눈에 띄는 막대가 노이즈**가 된다. 2026년 8월 실데이터에서
Visual·Meta는 CPI ₩29,373으로 압도적 1위였지만 소진 ₩558,087에 설치 19건이었다.
광고주 화면에서 그게 결론처럼 보이면 안 된다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from creative_data import (
    LOWER_IS_BETTER,
    add_derived_metrics,
    chart_frame,
    dumbbell_frame,
    metric_benchmark,
)


def table() -> pd.DataFrame:
    """규모 큰 두 행 + 노이즈 한 행. 노이즈의 CPI가 가장 나쁘다."""
    return add_derived_metrics(pd.DataFrame([
        {"creative_type": "Highlight", "media": "TikTok", "cost": 9000,
         "impression": 9000, "click": 900, "total install": 6,
         "D0 read": 5, "D0 coin": 0, "D7 coin": 0},
        {"creative_type": "Carousel", "media": "TikTok", "cost": 900,
         "impression": 1000, "click": 50, "total install": 1,
         "D0 read": 1, "D0 coin": 0, "D7 coin": 0},
        {"creative_type": "Visual", "media": "Meta", "cost": 100,
         "impression": 200, "click": 2, "total install": 0,
         "D0 read": 0, "D0 coin": 0, "D7 coin": 0},
    ]))


class TestMetricBenchmark:
    def test_ratio_is_weighted_not_an_average_of_rows(self):
        """행별 CPI를 산술평균하면 소진 1%짜리가 40%짜리와 같은 무게를 갖는다."""
        result = metric_benchmark(table(), "CPI")
        assert result == pytest.approx(10000 / 7)           # 합계 ÷ 합계
        assert result != pytest.approx(table()["CPI"].mean(skipna=True))

    def test_ctr_uses_click_over_impression(self):
        assert metric_benchmark(table(), "CTR") == pytest.approx(952 / 10200)

    def test_volume_metric_has_no_benchmark(self):
        """'소진액 평균보다 많이 썼다'는 결론으로 이어지지 않는다."""
        assert metric_benchmark(table(), "cost") is None

    def test_empty_table_and_zero_denominator_are_safe(self):
        assert metric_benchmark(table().iloc[0:0], "CPI") is None
        zero = table().assign(**{"total install": 0})
        assert metric_benchmark(zero, "CPI") is None


class TestChartFrame:
    def test_lower_is_better_metric_sorts_best_first(self):
        result = chart_frame(table(), "creative_type", "CPI")
        assert list(result["creative_type"]) == ["Carousel", "Highlight", "Visual"]

    def test_higher_is_better_metric_sorts_best_first(self):
        result = chart_frame(table(), "creative_type", "CTR")
        assert result.iloc[0]["creative_type"] == "Highlight"   # CTR 10%

    def test_metric_direction_table_is_explicit(self):
        assert "CPI" in LOWER_IS_BETTER and "CPC" in LOWER_IS_BETTER
        assert "CTR" not in LOWER_IS_BETTER

    def test_low_volume_rows_are_flagged_not_dropped(self):
        """버리면 합계가 안 맞고, 광고주가 표와 대조할 때 어긋난다."""
        result = chart_frame(table(), "creative_type", "CPI")
        assert len(result) == 3
        flags = dict(zip(result["creative_type"], result["_low_volume"]))
        assert flags["Visual"] is True or bool(flags["Visual"])   # 소진 1%
        assert not bool(flags["Highlight"])                       # 소진 90%

    def test_better_flag_follows_metric_direction(self):
        cpi = chart_frame(table(), "creative_type", "CPI")
        better = dict(zip(cpi["creative_type"], cpi["_better"]))
        assert bool(better["Carousel"])           # CPI 900 <= 평균 1,429
        assert not bool(better["Highlight"])      # CPI 1,500 > 평균 1,429

    def test_missing_values_sink_to_the_bottom(self):
        """설치 0이면 CPI가 NaN이다 — 맨 위에 오면 '최고 성과'로 읽힌다."""
        result = chart_frame(table(), "creative_type", "CPI")
        assert pd.isna(result.iloc[-1]["_rank_value"])

    def test_volume_metric_has_no_better_flag(self):
        result = chart_frame(table(), "creative_type", "cost")
        assert result["_better"].isna().all()

    def test_empty_or_unknown_inputs_are_safe(self):
        assert chart_frame(table().iloc[0:0], "creative_type", "CPI").empty
        assert chart_frame(table(), "no_such_axis", "CPI").empty
        assert chart_frame(table(), "creative_type", "no_such_metric").empty


class TestDumbbellFrame:
    def paired(self) -> pd.DataFrame:
        rows = table().to_dict("records")
        rows.append({**rows[0], "media": "Meta", "cost": 8000, "total install": 2,
                     "impression": 8000, "click": 80, "D0 read": 1,
                     "D0 coin": 0, "D7 coin": 0})
        return add_derived_metrics(pd.DataFrame(rows))

    def test_keeps_only_axis_values_present_in_both_media(self):
        """한쪽에만 있는 축값은 비교가 아니라 착시라서 뺀다."""
        result = dumbbell_frame(self.paired(), "creative_type", "CPI")
        assert list(result["creative_type"]) == ["Highlight"]

    def test_gap_is_absolute_and_sorts_widest_first(self):
        result = dumbbell_frame(self.paired(), "creative_type", "CPI")
        assert result.iloc[0]["gap"] == pytest.approx(abs(4000 - 1500))

    def test_needs_exactly_two_media(self):
        one = table()[table()["media"] == "TikTok"]
        assert dumbbell_frame(one, "creative_type", "CPI").empty

    def test_empty_input_is_safe(self):
        assert dumbbell_frame(table().iloc[0:0], "creative_type", "CPI").empty

    def test_explicit_benchmark_overrides_the_table_average(self):
        """실제 리포트의 기준은 표 안의 평균이 아니라 '그 달 그 매체 전체 성과'다.

        시트도 `TikTok 신규유형 총계` 바로 아래 `6월 틱톡 AOS 베너 소재 총 성과`를
        붙여 놓고 눈으로 대조한다 — 그 총계를 기준선으로 넘길 수 있어야 한다.
        """
        loose = chart_frame(table(), "creative_type", "CPI", benchmark=99999)
        assert dict(zip(loose["creative_type"], loose["_better"]))["Highlight"]
        strict = chart_frame(table(), "creative_type", "CPI", benchmark=1)
        assert not dict(zip(strict["creative_type"], strict["_better"]))["Highlight"]

    def test_explicit_benchmark_does_not_change_ordering(self):
        order = lambda b: list(chart_frame(table(), "creative_type", "CPI",
                                          benchmark=b)["creative_type"])
        assert order(None) == order(99999) == order(1)
