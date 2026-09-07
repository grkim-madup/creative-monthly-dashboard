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
    MEANINGFUL_CHANGE,
    MEANINGFUL_RATIO_POINTS,
    VOLUME_METRICS,
    add_derived_metrics,
    contrast_by_media,
    contrast_rows,
    contrast_verdict,
    front_back_state,
    side_state,
)


def rows(ad, media, cost, impression, click, install, read, coin=0):
    return {"ad": ad, "media": media, "cost": cost, "impression": impression,
            "click": click, "total install": install, "D0 read": read,
            "D0 coin": coin, "D7 coin": 0}


def subject() -> pd.DataFrame:
    """대상 — CTR 20%, CPI 100, D0 Read CVR 50%, D0 Coin CVR 25%.

    ⚠ 표본이 **게이트 위**여야 한다(설치 30건 · 노출 1,000회 · 열람 30건 ·
    코인 10건). 예전 픽스처는 설치 1건이었는데, 그 표본으로 `CPI 우수`를
    검증하는 건 실데이터에서 우리가 고친 바로 그 오류를 테스트가 요구하는 셈이다.
    """
    return add_derived_metrics(pd.DataFrame([
        rows("s1", "TikTok", 20000, 100000, 20000, 200, 100, 50),
        rows("s2", "Meta", 20000, 100000, 20000, 200, 100, 50),
    ]))


def rest() -> pd.DataFrame:
    """대조군 — CTR 10%, CPI 200, D0 Read CVR 100%, D0 Coin CVR 50%."""
    return add_derived_metrics(pd.DataFrame([
        rows("r1", "TikTok", 2000000, 10000000, 1000000, 10000, 10000, 5000),
        rows("r2", "Meta", 2000000, 10000000, 1000000, 10000, 10000, 5000),
    ]))


def tiny() -> pd.DataFrame:
    """표본 게이트에 걸리는 대상 — 소진 ₩0 · 노출 0 · 설치 4건.

    실데이터에서 그대로 나온 모양이다(8월 `title_code=9257`/Meta).
    """
    return add_derived_metrics(pd.DataFrame([
        rows("t1", "Meta", 0, 0, 0, 4, 0, 0),
    ]))


def by_metric(table: pd.DataFrame) -> dict:
    return {r["metric"]: r for _, r in table.iterrows()}


def by_metric_frame(table: pd.DataFrame) -> pd.DataFrame:
    """`front_back_state`는 표를 그대로 받는다 — 이름만 맞춰 두는 헬퍼."""
    return table


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
        assert table["cost"]["share"] == pytest.approx(40000 / 4040000)

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
        assert row["subject"] == pytest.approx(40000 / 200000)

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


class TestSampleGates:
    """표본이 없어서 계산만 되는 지표는 판정 재료에서 빠져야 한다.

    이 게이트가 없을 때 실데이터에서 벌어진 일: 소진 ₩0·설치 4건 카드가
    `CPI = 0/4 = ₩0`이 되고, CPI는 낮을수록 좋으니 **-100%로 "우수"**가 됐다.
    CTR은 노출 0이라 NaN으로 빠져 **CPI 한 표만으로** `앞단 우수`가 찍혔다.
    """

    def test_zero_spend_does_not_make_cpi_good(self):
        table = by_metric(contrast_rows(tiny(), rest()))
        assert table["CPI"]["better"] is None

    def test_zero_impression_does_not_judge_ctr(self):
        table = by_metric(contrast_rows(tiny(), rest()))
        assert table["CTR"]["better"] is None

    def test_tiny_sample_gets_no_verdict_instead_of_a_wrong_one(self):
        card = contrast_by_media(tiny(), rest())[0]
        assert card["verdict"] == "표본이 부족해 판단 불가"

    def test_values_are_still_shown(self):
        """판정만 막는다 — 값을 숨기면 왜 판정이 없는지 알 수 없다."""
        table = by_metric(contrast_rows(tiny(), rest()))
        assert table["total install"]["subject"] == 4

    def test_conversion_rates_are_judged_when_installs_suffice(self):
        """전환율은 **건수 문턱을 두지 않는다**(2026-09-07 규리님 결정).

        예전에는 코인 10건 미만이면 판정에서 뺐다. 그러면 `+0.02%p`처럼 좋아진
        값까지 색이 빠져서 정보가 사라졌다 — "Coin CVR이 오르면 좋은 것,
        내려가면 나쁜 것"이 확실한 지표다.

        분모인 **설치**가 충분하면 코인이 1건이어도 판정에 쓴다.
        """
        few = add_derived_metrics(pd.DataFrame([
            rows("c1", "Meta", 20000, 100000, 20000, 200, 100, 1),
        ]))
        table = by_metric(contrast_rows(few, rest()))
        assert table["D0 coin CVR"]["better"] is not None
        assert table["D0 read CVR"]["better"] is not None

    def test_conversion_rates_are_blocked_when_installs_are_thin(self):
        """분모가 얇으면 CVR은 노이즈다 — CPI에 같은 문턱을 거는 것과 같은 이유.

        이 문턱이 없으면 **코인 0건이 곧 `뒷단 저조`**가 된다. 실측으로 그런 카드
        31개의 설치 중위값이 19건이었다(기준 전환율 3%면 기대 코인 0.6건).
        """
        thin = add_derived_metrics(pd.DataFrame([
            rows("t1", "Meta", 20000, 100000, 20000, 10, 5, 0),
        ]))
        table = by_metric(contrast_rows(thin, rest()))
        assert table["D0 coin CVR"]["better"] is None
        assert table["D0 read CVR"]["better"] is None


class TestVerdict:
    def test_splits_front_and_back(self):
        """실제 리포트가 늘 '앞단 우수하나 뒷단 저조'로 쓴다."""
        card = contrast_by_media(subject(), rest())[0]
        assert "앞단" in card["verdict"] and "뒷단" in card["verdict"]

    def test_empty_table_says_nothing(self):
        assert contrast_verdict(pd.DataFrame()) == ""

    def test_money_metric_decides_the_front_end(self):
        """CPI가 주 지표다 — CTR이 반대여도 뒤집히지 않는다(규리님 결정).

        예전에는 두 지표 다수결이라 1:1이면 `혼재`가 됐다. 실측 MIX/Meta는
        **CPI -31.1%**인데 CTR -0.44%p 때문에 `앞단 혼재`로 찍혀, 광고주가
        정반대로 읽을 수 있었다.
        """
        front, _back = front_back_state(by_metric_frame(
            contrast_rows(subject(), rest())))
        assert front["used"] == "CPI"
        assert front["state"] == 1                  # CPI 100 vs 200
        assert front["opposed"] is None             # CTR도 같은 방향이다

    def test_secondary_cannot_flip_the_primary(self):
        """CTR은 좋고 CPI는 나쁠 때 — 판정은 CPI를 따르고, 반대 사실은 남는다."""
        table = pd.DataFrame([
            {"metric": "CPI", "delta": 0.40, "unit": "%", "better": False},
            {"metric": "CTR", "delta": 5.0, "unit": "%p", "better": True},
        ])
        front = side_state(table, "CPI", "CTR")
        assert front["state"] == -1
        assert front["opposed"] == "CTR"

    def test_falls_back_to_the_secondary_when_the_primary_is_unusable(self):
        table = pd.DataFrame([
            {"metric": "CPI", "delta": None, "unit": "%", "better": None},
            {"metric": "CTR", "delta": 5.0, "unit": "%p", "better": True},
        ])
        front = side_state(table, "CPI", "CTR")
        assert front["state"] == 1 and front["fallback"] is True
        assert front["used"] == "CTR"

    def test_no_difference_is_not_the_same_as_cannot_judge(self):
        """둘을 뭉개면 오독이 된다.

        실측: `format=VID`/TikTok은 설치 30,688건·열람 15,662건으로 표본이
        충분한데 CTR -0.95%p / CPI -0.6%가 문턱 미달일 뿐이었다. 그걸
        `판단 불가`로 찍으면 "표본이 없다"는 뜻으로 읽힌다.
        """
        small = pd.DataFrame([
            {"metric": "CPI", "delta": 0.01, "unit": "%", "better": False},
            {"metric": "CTR", "delta": 0.1, "unit": "%p", "better": True},
        ])
        assert side_state(small, "CPI", "CTR")["state"] == 0

        missing = pd.DataFrame([
            {"metric": "CPI", "delta": None, "unit": "%", "better": None},
            {"metric": "CTR", "delta": None, "unit": "%p", "better": None},
        ])
        assert side_state(missing, "CPI", "CTR")["state"] is None

    def test_threshold_is_shared_with_the_draft(self):
        """판정과 근거가 다른 문턱을 쓰면, 판정은 `저조`인데 근거 줄이 없는 문단이 나온다."""
        import insight_draft

        assert insight_draft.MEANINGFUL_RATIO_POINTS is MEANINGFUL_RATIO_POINTS
        assert insight_draft.MEANINGFUL_CHANGE is MEANINGFUL_CHANGE


class TestContrastGroups:
    """행에 걸린 집행 조건까지 대조군을 나눈다(2026-09-07 규리님 요청).

    iOS와 AOS는 CPI가 3배 이상 벌어진다(8월 실측 메타 iOS ₩7,562 / AOS ₩3,531).
    한 덩어리로 묶으면 소재 차이가 그 격차에 묻힌다.
    """

    def both_os(self):
        from creative_data import add_derived_metrics

        return add_derived_metrics(pd.DataFrame([
            {**rows("s1", "TikTok", 20000, 100000, 20000, 200, 100, 50), "os": "AOS"},
            {**rows("s2", "TikTok", 20000, 100000, 5000, 50, 20, 5), "os": "iOS"},
        ]))

    def rest_both_os(self):
        from creative_data import add_derived_metrics

        return add_derived_metrics(pd.DataFrame([
            {**rows("r1", "TikTok", 2000000, 10000000, 1000000, 10000, 5000, 2000),
             "os": "AOS"},
            {**rows("r2", "TikTok", 2000000, 10000000, 200000, 1000, 400, 100),
             "os": "iOS"},
        ]))

    def test_media_only_by_default(self):
        from creative_data import contrast_groups

        assert contrast_groups([{"field": "media"}]) == ["media"]
        assert contrast_groups([{"field": "creative_type"}]) == ["media"]
        assert contrast_groups([]) == ["media"]

    def test_os_in_rows_adds_the_axis(self):
        from creative_data import contrast_groups

        assert contrast_groups(
            [{"field": "media"}, {"field": "os"}, {"field": "usp"}]) == ["media", "os"]

    def test_creative_attributes_are_never_axes(self):
        """소재 속성으로 나누면 대상 정의와 섞여 "무엇을 비교하나"가 흐려진다."""
        from creative_data import contrast_groups

        assert contrast_groups([{"field": "usp"}, {"field": "format"}]) == ["media"]

    def test_cards_split_by_os(self):
        cards = contrast_by_media(self.both_os(), self.rest_both_os(),
                                  by=["media", "os"])
        assert sorted(c["media"] for c in cards) == ["TikTok · AOS", "TikTok · iOS"]

    def test_each_card_keeps_its_axis_values(self):
        """이름을 `·`로 다시 쪼개면 값에 `·`가 들어 있을 때 깨진다 — keys를 쓴다."""
        cards = contrast_by_media(self.both_os(), self.rest_both_os(),
                                  by=["media", "os"])
        for card in cards:
            assert card["keys"]["media"] == "TikTok"
            assert card["keys"]["os"] in ("AOS", "iOS")

    def test_each_card_is_compared_against_its_own_os(self):
        cards = {c["keys"]["os"]: c for c in
                 contrast_by_media(self.both_os(), self.rest_both_os(),
                                   by=["media", "os"])}
        aos = by_metric(cards["AOS"]["table"])["CPI"]
        ios = by_metric(cards["iOS"]["table"])["CPI"]
        assert aos["rest"] == pytest.approx(200)      # AOS 대조군만
        assert ios["rest"] == pytest.approx(2000)     # iOS 대조군만

    def test_missing_axis_column_falls_back(self):
        """구글처럼 OS가 없는 프레임에서도 죽지 않는다."""
        thin = self.both_os().drop(columns=["os"])
        cards = contrast_by_media(thin, self.rest_both_os(), by=["media", "os"])
        assert [c["media"] for c in cards] == ["TikTok"]


class TestColourFollowsDirection:
    """색은 **델타 방향**으로 칠한다 — 판정 재료 여부(`better`)를 쓰지 않는다.

    두 번 틀렸다:
      · `if better else` 로 판단해서 `None`을 falsy로 읽고 **좋아진 값을 빨강**으로
        칠했다(8월 MIX / TikTok·AOS의 D0 Coin CVR `+0.02%p`).
      · 그걸 고치면서 `None`인 칸을 **흑백**으로 뺐다. 그러자 규리님이
        "Coin 성과 차이는 왜 흑백으로 빼? 오르면 좋은 것, 내려가면 나쁜 것"이라
        지적했다 — 오르내림 자체는 표본과 무관한 사실이다.

    이 표의 색은 광고주가 그대로 결론으로 읽는다. 방향이 반대로 칠리면 그 자체가
    틀린 보고다.
    """

    def test_screen_paints_by_delta_not_by_verdict(self):
        """진입점은 import할 수 없으니 소스로 확인한다."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        entry = next((root / n for n in ("creative_dashboard.py", "app.py")
                      if (root / n).exists()))
        source = entry.read_text(encoding="utf-8")
        assert 'improved = ((line["delta"] < 0) if metric in LOWER_IS_BETTER' in source
        # 판정 재료로 색을 고르던 옛 코드가 남아 있으면 안 된다.
        assert 'if line["better"] else' not in source

    def test_direction_rule_is_shared(self):
        """방향 판단은 `LOWER_IS_BETTER` 한 곳에서만 한다."""
        assert "CPI" in LOWER_IS_BETTER and "CPM" in LOWER_IS_BETTER
        assert "D0 coin CVR" not in LOWER_IS_BETTER
