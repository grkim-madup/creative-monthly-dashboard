"""인사이트 초안 — 계산으로만 만든다. 지어낸 문장이 광고주에게 가지 않게 고정한다."""
from __future__ import annotations

import pandas as pd
import pytest

from creative_data import add_derived_metrics
from insight_draft import (
    MEANINGFUL_CHANGE,
    MEANINGFUL_RATIO_POINTS,
    axis_spread,
    compare,
    draft_html,
    draft_lines,
    media_verdicts,
    notable_creatives,
    topic_particle,
)


def frame(rows) -> pd.DataFrame:
    return add_derived_metrics(pd.DataFrame(rows))


def row(ad, media, cost, impression, click, install, read=0, title="작품A"):
    return {"ad": ad, "media": media, "title_kr": title, "cost": cost,
            "impression": impression, "click": click, "total install": install,
            "D0 read": read, "D0 coin": 0, "D7 coin": 0}


class TestParticle:
    def test_consonant_ending_takes_eun(self):
        assert topic_particle("EPN형") == "은"          # 형 = 받침 있음

    def test_vowel_ending_takes_neun(self):
        assert topic_particle("소재") == "는"

    def test_empty_is_safe(self):
        assert topic_particle("") == "는"


class TestCompare:
    def test_ratio_metric_uses_percentage_points(self):
        result = compare("CTR", 0.20, 0.10)
        assert result["unit"] == "%p"
        assert result["delta"] == pytest.approx(10.0)
        assert result["shown"] == "+10.00%p"

    def test_money_metric_uses_relative_change(self):
        result = compare("CPI", 1500, 1000)
        assert result["unit"] == "%"
        assert result["delta"] == pytest.approx(0.5)

    def test_lower_is_better_flips_the_verdict(self):
        """CPI가 올라간 것은 '나빠진' 것이다 — 방향을 뒤집지 않으면 결론이 반대가 된다."""
        assert compare("CPI", 1500, 1000)["better"] is False
        assert compare("CPI", 800, 1000)["better"] is True
        assert compare("CTR", 0.2, 0.1)["better"] is True

    def test_small_differences_are_not_meaningful(self):
        """0.3%p 차이를 '우수'로 쓰면 광고주가 제작 방향을 잘못 잡는다."""
        assert not compare("CTR", 0.1003, 0.10)["meaningful"]
        # 부동소수 오차로 경계값이 아슬아슬해지지 않게 여유를 둔다
        assert compare("CTR", 0.12, 0.10)["meaningful"]      # +2%p
        assert not compare("CPI", 1000 * (1 + MEANINGFUL_CHANGE / 2), 1000)["meaningful"]

    def test_missing_or_zero_benchmark_is_none(self):
        assert compare("CPI", 1000, None) is None
        assert compare("CPI", None, 1000) is None
        assert compare("CPI", 1000, 0) is None


class TestMediaVerdicts:
    def scope_and_whole(self):
        scope = frame([row("a1", "TikTok", 100, 1000, 200, 1),
                       row("a2", "Meta", 100, 1000, 5, 1)])
        whole = frame([row("b1", "TikTok", 100, 1000, 100, 1),
                       row("b2", "Meta", 100, 1000, 100, 1)])
        return scope, whole

    def test_each_media_is_compared_against_its_own_benchmark(self):
        """매체 격차가 소재 차이를 덮지 않도록 매체별로 견준다."""
        scope, whole = self.scope_and_whole()
        verdicts = {v["media"]: v for v in media_verdicts(scope, whole)}
        assert any(r["metric"] == "CTR" for r in verdicts["TikTok"]["good"])
        assert any(r["metric"] == "CTR" for r in verdicts["Meta"]["bad"])

    def test_no_media_column_gives_nothing(self):
        scope = frame([row("a1", "TikTok", 100, 1000, 10, 1)]).drop(columns=["media"])
        assert media_verdicts(scope, scope) == []


class TestAxisSpread:
    def test_reports_the_gap_between_best_and_worst(self):
        scope = frame([row("a1", "TikTok", 1000, 1000, 10, 10, title="싼작품"),
                       row("a2", "TikTok", 1000, 1000, 10, 2, title="비싼작품")])
        spread = axis_spread(scope, "title_kr")
        assert spread["best_name"] == "싼작품"          # CPI 100
        assert spread["worst_name"] == "비싼작품"        # CPI 500
        assert spread["times"] == pytest.approx(5.0)

    def test_tiny_spend_values_are_excluded(self):
        """소진 1%짜리 극단값을 '5배 차이'의 근거로 쓰면 결론이 뒤집힌다."""
        scope = frame([row("a1", "TikTok", 10000, 1000, 10, 10, title="본류"),
                       row("a2", "TikTok", 10, 10, 1, 1, title="노이즈")])
        assert axis_spread(scope, "title_kr") is None   # 비교 대상이 하나만 남는다

    def test_single_value_has_no_spread(self):
        scope = frame([row("a1", "TikTok", 100, 100, 10, 1)])
        assert axis_spread(scope, "title_kr") is None

    def test_unknown_field_is_safe(self):
        scope = frame([row("a1", "TikTok", 100, 100, 10, 1)])
        assert axis_spread(scope, "no_such") is None


class TestNotableCreatives:
    def test_small_spend_creatives_are_not_promoted(self):
        """설치 1건짜리를 '가장 효율 좋은 소재'로 올리면 광고주가 그걸 더 만들자고 한다."""
        scope = frame([row("big", "TikTok", 10000, 1000, 10, 5),
                       row("tiny", "TikTok", 10, 10, 1, 10)])
        names = [item["ad"] for item in notable_creatives(scope)]
        assert names == ["big"]

    def test_best_metric_first(self):
        scope = frame([row("cheap", "TikTok", 5000, 1000, 10, 10),
                       row("pricey", "TikTok", 5000, 1000, 10, 2)])
        assert notable_creatives(scope)[0]["ad"] == "cheap"


class TestDraft:
    def scope_and_whole(self):
        scope = frame([row("a1", "TikTok", 100, 1000, 200, 1),
                       row("a2", "Meta", 100, 1000, 5, 1)])
        whole = frame([row("b1", "TikTok", 100, 1000, 100, 1),
                       row("b2", "Meta", 100, 1000, 100, 1)])
        return scope, whole

    def test_follows_the_report_grammar(self):
        scope, whole = self.scope_and_whole()
        lines = draft_lines(scope, whole, 8, label="EPN형")
        assert lines[0].startswith("- ")
        assert any(line.startswith("   ㄴ ") for line in lines)
        assert "추후 제작 인사이트" in lines

    def test_leaves_interpretation_to_a_person(self):
        """왜 잘됐는지는 숫자에 없다 — 지어내지 않고 '확인 필요'로 넘긴다."""
        scope, whole = self.scope_and_whole()
        assert any("확인 필요" in line for line in draft_lines(scope, whole, 8))

    def test_empty_scope_says_so_instead_of_inventing(self):
        scope, whole = self.scope_and_whole()
        lines = draft_lines(scope.iloc[0:0], whole, 8)
        assert len(lines) == 1 and "없어" in lines[0]

    def test_drive_link_is_attached_only_to_mentioned_creatives(self):
        scope = frame([row("big", "TikTok", 10000, 1000, 100, 5),
                       row("other", "Meta", 10000, 1000, 100, 5)])
        lines = draft_lines(scope, scope, 8,
                            links={"big": "https://drive/x", "unused": "https://drive/y"})
        text = "\n".join(lines)
        assert "https://drive/x" in text
        assert "https://drive/y" not in text

    def test_html_wraps_each_line_and_keeps_blank_lines(self):
        scope, whole = self.scope_and_whole()
        html = draft_html(scope, whole, 8)
        assert html.startswith("<p>")
        assert "<p><br></p>" in html          # 빈 줄이 살아 있어야 문단이 갈린다
