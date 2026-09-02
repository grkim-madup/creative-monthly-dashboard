"""대조군 비교 — 동일 조건에서 그 소재군을 제외한 나머지와 견준다.

규리님 요구: "각 매체별로 이 소재가 효율이 좋았냐 안 좋았냐. 그 기준은 동일 조건에서
그걸 제외한 다른 소재들의 평균."
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from creative_data import (
    CONTRAST_METRICS,
    LOWER_IS_BETTER,
    VOLUME_METRICS,
    add_derived_metrics,
    contrast_by_media,
    contrast_rows,
    contrast_verdict,
)


def rows(ad, media, cost, impression, click, install, read, coin=0):
    return {"ad": ad, "media": media, "cost": cost, "impression": impression,
            "click": click, "total install": install, "D0 read": read,
            "D0 coin": coin, "D7 coin": 0}


def subject() -> pd.DataFrame:
    """작은 대상 — CTR 20%, CPI 100, D0 Read CVR 50%."""
    return add_derived_metrics(pd.DataFrame([
        rows("s1", "TikTok", 100, 1000, 200, 1, 0),
        rows("s2", "Meta", 100, 1000, 200, 1, 1),
    ]))


def rest() -> pd.DataFrame:
    """큰 대조군 — CTR 10%, CPI 200, D0 Read CVR 100%."""
    return add_derived_metrics(pd.DataFrame([
        rows("r1", "TikTok", 10000, 100000, 10000, 50, 50),
        rows("r2", "Meta", 10000, 100000, 10000, 50, 50),
    ]))


def by_metric(table: pd.DataFrame) -> dict:
    return {r["metric"]: r for _, r in table.iterrows()}


class TestVolumeMetrics:
    """볼륨 지표에 판정을 붙이면 결론이 통째로 틀린다."""

    def test_volume_and_efficiency_do_not_overlap(self):
        assert "CPI" not in VOLUME_METRICS and "CTR" not in VOLUME_METRICS
        assert "cost" in VOLUME_METRICS and "total install" in VOLUME_METRICS

    def test_volume_has_no_delta_and_no_verdict(self):
        """대상이 소진 1%면 노출·설치는 당연히 −99%다 — 그게 '저조'로 읽히면 안 된다."""
        table = by_metric(contrast_rows(subject(), rest()))
        for metric in ("cost", "impression", "click", "total install"):
            assert table[metric]["delta"] is None or math.isnan(table[metric]["delta"])
            assert table[metric]["better"] is None

    def test_volume_reports_share_instead(self):
        table = by_metric(contrast_rows(subject(), rest()))
        assert table["cost"]["share"] == pytest.approx(200 / 20200)

    def test_efficiency_has_no_share(self):
        table = by_metric(contrast_rows(subject(), rest()))
        assert table["CPI"]["share"] is None or math.isnan(table["CPI"]["share"])


class TestDelta:
    def test_ratio_metric_uses_percentage_points(self):
        row = by_metric(contrast_rows(subject(), rest()))["CTR"]
        assert row["unit"] == "%p"
        assert row["delta"] == pytest.approx(10.0)      # 20% - 10%

    def test_money_metric_uses_relative_change(self):
        row = by_metric(contrast_rows(subject(), rest()))["CPI"]
        assert row["unit"] == "%"
        assert row["delta"] == pytest.approx(-0.5)      # 100 vs 200

    def test_lower_is_better_flips_the_verdict(self):
        table = by_metric(contrast_rows(subject(), rest()))
        assert table["CPI"]["better"] is True           # CPI가 낮으니 좋다
        assert table["CTR"]["better"] is True
        assert table["D0 read CVR"]["better"] is False  # 50% vs 100%
        assert "CPI" in LOWER_IS_BETTER

    def test_ratios_come_from_the_totals_not_row_averages(self):
        """행별 비율을 평균내면 소진 1%짜리가 40%짜리와 같은 무게를 갖는다."""
        row = by_metric(contrast_rows(subject(), rest()))["CTR"]
        assert row["subject"] == pytest.approx(400 / 2000)

    def test_empty_rest_gives_no_delta(self):
        table = by_metric(contrast_rows(subject(), rest().iloc[0:0]))
        assert table["CPI"]["delta"] is None
        assert table["CPI"]["better"] is None

    def test_empty_subject_is_safe(self):
        table = contrast_rows(subject().iloc[0:0], rest())
        assert len(table) == len(CONTRAST_METRICS)


class TestByMedia:
    def test_one_table_per_media_in_the_subject(self):
        cards = contrast_by_media(subject(), rest())
        assert [c["media"] for c in cards] == ["Meta", "TikTok"] or \
               [c["media"] for c in cards] == ["TikTok", "Meta"]
        assert len(cards) == 2

    def test_each_media_is_compared_against_its_own_rest(self):
        """매체 격차가 소재 차이를 덮지 않게 매체별로 견준다."""
        cards = {c["media"]: c for c in contrast_by_media(subject(), rest())}
        row = by_metric(cards["TikTok"]["table"])["CPI"]
        assert row["rest"] == pytest.approx(200)        # TikTok 쪽 대조군만

    def test_media_absent_from_the_subject_is_not_drawn(self):
        """비교할 것이 없는 표를 그리면 '안 썼다'가 '성과 0'으로 읽힌다."""
        only_meta = subject()[subject()["media"] == "Meta"]
        assert [c["media"] for c in contrast_by_media(only_meta, rest())] == ["Meta"]

    def test_carries_sample_size_and_share(self):
        """표본이 작다는 사실이 숨으면 광고주가 과한 판단을 한다."""
        card = contrast_by_media(subject(), rest())[0]
        assert card["ads"] == 1
        assert 0 < card["share"] < 0.02

    def test_no_media_column_gives_nothing(self):
        thin = subject().drop(columns=["media"])
        assert contrast_by_media(thin, rest()) == []


class TestVerdict:
    def test_splits_front_and_back(self):
        """실제 리포트가 늘 '앞단 우수하나 뒷단 저조'로 쓴다."""
        card = contrast_by_media(subject(), rest())[0]
        assert "앞단" in card["verdict"] and "뒷단" in card["verdict"]

    def test_empty_table_says_nothing(self):
        assert contrast_verdict(pd.DataFrame()) == ""
