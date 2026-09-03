# -*- coding: utf-8 -*-
"""판정·서술 — "계속 운영할 의미가 있나"에 답하는 부분.

여기서 틀리면 광고주에게 **틀린 액션 제안**이 간다. 아래 케이스는 전부 8월
실데이터에서 실제로 나온 모양이다.
"""
import pandas as pd
import pytest

import insight_draft as idf
from creative_data import (
    BACK_PRIMARY,
    BACK_SECONDARY,
    FRONT_PRIMARY,
    FRONT_SECONDARY,
    add_derived_metrics,
    contrast_by_media,
    contrast_rows,
)


def row(ad, media, cost, impression, click, install, read, coin=0):
    return {"ad": ad, "media": media, "cost": cost, "impression": impression,
            "click": click, "total install": install, "D0 read": read,
            "D0 coin": coin, "D7 coin": 0, "title_kr": "작품A"}


def frame(rows):
    return add_derived_metrics(pd.DataFrame(rows))


def card_of(subject, rest, media="Meta"):
    return {c["media"]: c for c in contrast_by_media(subject, rest)}[media]


def table(**deltas):
    """지표별 (delta, unit, better)를 그대로 심은 표. 판정 규칙만 좁혀 본다."""
    return pd.DataFrame([
        {"metric": metric, "delta": delta, "unit": unit, "better": better,
         "share": None, "subject": 1.0, "rest": 1.0}
        for metric, (delta, unit, better) in deltas.items()
    ])


class TestPrimaryMetricDecides:
    """돈 지표가 판정을 정한다(2026-09-03 규리님 결정).

    예전에는 두 지표 다수결이라 1:1이면 `혼재`가 됐고, 8월 329카드 중 판정이
    나오는 카드가 23.1%뿐이었다. 주 지표 우선으로 46.2%가 됐다.
    """

    def test_front_follows_cpi_not_ctr(self):
        state = idf.front_back_state(table(
            CPI=(0.40, "%", False), CTR=(5.0, "%p", True)))[0]
        assert state["state"] == -1 and state["used"] == "CPI"

    def test_opposite_secondary_is_disclosed(self):
        """숨기면 오독이 된다 — 반대라는 사실을 문구에 남긴다."""
        state = idf.front_back_state(table(
            CPI=(0.40, "%", False), CTR=(5.0, "%p", True)))[0]
        assert state["opposed"] == "CTR"
        assert "반대" in idf.side_phrase(state, "앞단")

    def test_back_follows_coin_not_read(self):
        state = idf.front_back_state(table(**{
            "D0 coin CVR": (5.0, "%p", True),
            "D0 read CVR": (-5.0, "%p", False)}))[1]
        assert state["state"] == 1 and state["used"] == "D0 coin CVR"

    def test_falls_back_to_secondary_and_says_so(self):
        state = idf.front_back_state(table(**{
            "D0 coin CVR": (None, "%p", None),
            "D0 read CVR": (-5.0, "%p", False)}))[1]
        assert state["state"] == -1 and state["fallback"] is True
        assert "D0 Read CVR 기준" in idf.side_phrase(state, "뒷단")

    def test_below_threshold_primary_yields_to_secondary(self):
        """CPI +4.6%는 문턱(5%) 미달이라 CTR이 판정한다 — 실측 MIX/TikTok."""
        state = idf.front_back_state(table(
            CPI=(0.046, "%", False), CTR=(3.16, "%p", True)))[0]
        assert state["state"] == 1 and state["used"] == "CTR"


class TestSampleGates:
    def test_zero_spend_card_gets_no_verdict(self):
        """실데이터 그대로 — 8월 `title_code=9257`/Meta, 소진 ₩0·설치 4건."""
        tiny = frame([row("t1", "Meta", 0, 0, 0, 4, 0, 0)])
        big = frame([row("r1", "Meta", 2000000, 10000000, 1000000, 10000, 10000, 5000)])
        judged = idf.operating_verdict(card_of(tiny, big))
        assert judged["verdict"] == ""
        assert judged["action_ok"] is False

    def test_action_is_blocked_on_a_small_sample(self):
        """판정은 되지만 확대·축소는 제안하지 않는다 — 설치 98건짜리가 그 경우다."""
        small = frame([row("s1", "Meta", 700000, 200000, 1400, 98, 42, 4)])
        big = frame([row("r1", "Meta", 100000000, 20000000, 260000, 19000, 11000, 560)])
        judged = idf.operating_verdict(card_of(small, big))
        assert judged["verdict"]              # 판정은 나온다
        assert judged["action_ok"] is False   # 액션은 막힌다

    def test_many_installs_pass_even_with_a_small_share(self):
        """설치가 많으면 비중이 작아도 판단할 수 있다(설치 300 예외)."""
        assert idf.INSTALLS_OVERRIDE_SHARE > idf.MIN_INSTALLS_FOR_ACTION
        assert idf.MIN_SHARE_FOR_ACTION == pytest.approx(0.01)


class TestNextStep:
    def test_lines_name_the_table_and_media(self):
        """안 붙이면 한 블록에서 `TikTok : 유지`와 `TikTok : 축소 검토`가 나란히 찍힌다."""
        good = frame([row("s1", "TikTok", 3000000, 1000000, 200000, 2000, 1000, 200)])
        rest = frame([row("r1", "TikTok", 90000000, 11000000, 1600000, 55000, 29000, 20)])
        cards = contrast_by_media(good, rest)
        lines = idf.next_step_lines([("EPN 소재", cards[0])])
        assert any("EPN 소재 · TikTok" in line for line in lines)

    def test_proposals_end_in_the_report_voice(self):
        """실제 리포트는 `>>` + `~제안` / `~검토`로 쓴다(`notes/next_step_7.json`)."""
        good = frame([row("s1", "TikTok", 3000000, 1000000, 200000, 2000, 1000, 200)])
        rest = frame([row("r1", "TikTok", 90000000, 11000000, 1600000, 55000, 29000, 20)])
        lines = idf.next_step_lines([("EPN", contrast_by_media(good, rest)[0])])
        proposals = [line for line in lines if line.startswith(">>")]
        assert proposals
        assert all(line.rstrip().endswith(("제안", "검토")) for line in proposals)

    def test_example_slot_is_left_empty(self):
        """`ex)`에 문구를 지어 넣으면 광고주에게 없는 사실이 간다."""
        good = frame([row("s1", "TikTok", 3000000, 1000000, 200000, 2000, 1000, 200)])
        rest = frame([row("r1", "TikTok", 90000000, 11000000, 1600000, 55000, 29000, 20)])
        lines = idf.next_step_lines([("EPN", contrast_by_media(good, rest)[0])])
        assert "- ex)" in lines

    def test_no_verdict_means_no_proposal(self):
        tiny = frame([row("t1", "Meta", 0, 0, 0, 4, 0, 0)])
        big = frame([row("r1", "Meta", 2000000, 10000000, 1000000, 10000, 10000, 5000)])
        assert idf.next_step_lines([("X", card_of(tiny, big))]) == []


class TestSwingCreatives:
    """소재군 평균을 혼자 끌고 가는 소재만 짚는다 — 나열하지 않는다."""

    def base(self, count):
        rows = [row(f"a{i}", "Meta", 1000000, 300000, 3000, 500, 250, 20)
                for i in range(count - 1)]
        # 마지막 하나가 CPI를 크게 흔든다.
        rows.append(row("swing", "Meta", 3000000, 300000, 3000, 3000, 1500, 120))
        return frame(rows)

    def test_needs_at_least_three_creatives(self):
        """규리님: "소재가 3개 이상 있는 경우엔 적어.\""""
        assert idf.swing_creatives(self.base(2)) == []
        assert idf.swing_creatives(self.base(3))

    def test_reports_at_most_two(self):
        found = idf.swing_creatives(self.base(8))
        assert len(found) <= 2

    def test_large_pool_has_no_swing(self):
        """소재 216개짜리에서는 한 소재가 평균을 못 흔든다(8월 Highlight 실측)."""
        flat = frame([row(f"a{i}", "Meta", 1000000, 300000, 3000, 500, 250, 20)
                      for i in range(40)])
        assert idf.swing_creatives(flat) == []

    def test_line_says_which_direction(self):
        lines = idf.swing_lines(self.base(5))
        assert lines and "제외 시" in lines[0]
        assert "유지되고 있음" in lines[0] or "눌려 있음" in lines[0]

    def test_no_creatives_means_no_line(self):
        assert idf.swing_lines(pd.DataFrame()) == []


class TestNumbersMatchTheTable:
    """초안의 델타 문자열이 표의 것과 **문자 단위로** 같아야 한다.

    예전에는 초안이 `compare()`로 값을 다시 계산해서 Meta CPI가 표 `+36.7%` /
    초안 `+36.5%`로 갈렸다. 광고주 문서에서 같은 항목이 두 값이 됐다.
    """

    def test_delta_text_reads_the_table(self):
        subject = frame([row("s1", "Meta", 751459, 226194, 1465, 98, 42, 4)])
        rest = frame([row("r1", "Meta", 109221053, 22081750, 279732, 19472, 11770, 574)])
        rows = contrast_rows(subject, rest)
        cpi = rows[rows["metric"] == "CPI"].iloc[0]
        assert idf.delta_text(cpi) == f"{cpi['delta']:+.1%}"

    def test_volume_shows_share_not_change(self):
        subject = frame([row("s1", "Meta", 751459, 226194, 1465, 98, 42, 4)])
        rest = frame([row("r1", "Meta", 109221053, 22081750, 279732, 19472, 11770, 574)])
        rows = contrast_rows(subject, rest)
        cost = rows[rows["metric"] == "cost"].iloc[0]
        assert idf.delta_text(cost).startswith("비중 ")


class TestOneNextStepHeader:
    def test_draft_lines_still_has_exactly_one_header(self):
        """`draft_lines`는 본문+꼬리를 합쳐 돌려주는 래퍼로 남는다(기존 계약)."""
        scope = frame([row("s1", "Meta", 1000000, 300000, 3000, 500, 250, 20)])
        lines = idf.draft_lines(scope, scope, 8)
        assert lines.count("추후 제작 인사이트") == 1

    def test_sections_split_body_and_tail(self):
        """뷰가 여러 개일 때 꼬리를 블록 끝에 한 번만 붙이기 위한 분리다."""
        scope = frame([row("s1", "Meta", 1000000, 300000, 3000, 500, 250, 20)])
        body, tail = idf.draft_sections(scope, scope, 8)
        assert "추후 제작 인사이트" not in body
        assert "추후 제작 인사이트" in tail


class TestParticle:
    def test_picks_i_or_ga(self):
        assert idf.subject_particle("CPI") == "가"
        assert idf.subject_particle("CTR") == "이"
        assert idf.subject_particle("소재군") == "이"
        assert idf.subject_particle("") == "이"


def test_metric_roles_are_money_first():
    """규칙이 조용히 뒤집히지 않게 못 박는다."""
    assert (FRONT_PRIMARY, FRONT_SECONDARY) == ("CPI", "CTR")
    assert (BACK_PRIMARY, BACK_SECONDARY) == ("D0 coin CVR", "D0 read CVR")


class TestBlockDocument:
    """주제 하나의 초안 **전체 모양**. 조립부가 모듈에 있어야 이걸 검증할 수 있다."""

    def small(self, ad, media="Meta"):
        return frame([row(ad, media, 3000000, 1000000, 20000, 2000, 1000, 200)])

    def big(self, media="Meta"):
        return frame([row("r1", media, 100000000, 20000000, 260000, 60000,
                          30000, 3000)])

    def test_contrast_document_has_one_next_step_header(self):
        """대조군 표가 둘이어도 `추후 제작 인사이트`는 한 번만 나온다."""
        sections = [
            {"kind": "contrast", "title": "EPN", "subject": self.small("s1"),
             "rest": self.big(), "values": None},
            {"kind": "contrast", "title": "6s", "subject": self.small("s2"),
             "rest": self.big(), "values": None},
        ]
        lines = idf.block_lines(sections, 8, pool=200000000.0)
        assert lines.count("추후 제작 인사이트") == 1

    def test_two_plain_views_do_not_double_the_header(self):
        """예전 `draft_lines`는 헤더를 자기 안에 갖고 있어 두 번 부르면 두 번 나왔다."""
        scope = self.small("s1")
        sections = [
            {"kind": "plain", "scope": scope, "whole": scope, "label": "A"},
            {"kind": "plain", "scope": scope, "whole": scope, "label": "B"},
        ]
        assert idf.block_lines(sections, 8).count("추후 제작 인사이트") == 2

    def test_plain_view_is_skipped_when_contrast_exists(self):
        """대조군이 서사를 만든다 — 합집합 초안을 덧붙이면 기준이 섞인다."""
        sections = [
            {"kind": "contrast", "title": "EPN", "subject": self.small("s1"),
             "rest": self.big(), "values": None},
            {"kind": "plain", "scope": self.small("s1"), "whole": self.big(),
             "label": "합집합"},
        ]
        lines = idf.block_lines(sections, 8, pool=200000000.0)
        assert not any("합집합" in line for line in lines)
        assert lines.count("추후 제작 인사이트") == 1

    def test_scale_line_names_its_denominator(self):
        """`집행 전체의 X%`라고 쓰면 광고주가 1번 표 총액과 대조하며 어긋난 숫자를 본다."""
        sections = [{"kind": "contrast", "title": "EPN", "subject": self.small("s1"),
                     "rest": self.big(), "values": None}]
        lines = idf.block_lines(sections, 8, pool=200000000.0)
        scale = next(line for line in lines if "규모" in line)
        assert "소재 태깅된 집행" in scale

    def test_a_failing_section_is_reported_not_swallowed(self):
        """조용히 빠지면 초안에 표 하나가 없어진 걸 아무도 모른다."""
        sections = [
            {"kind": "contrast", "title": "깨진 표", "subject": "not a frame",
             "rest": self.big(), "values": None},
            {"kind": "contrast", "title": "정상", "subject": self.small("s1"),
             "rest": self.big(), "values": None},
        ]
        lines = idf.block_lines(sections, 8, pool=200000000.0)
        assert any("초안을 만들지 못한 표 : 깨진 표" in line for line in lines)
        assert any("정상" in line for line in lines)

    def test_values_do_not_change_the_verdict(self):
        """사용자가 표에서 지표를 빼도 판정·제안이 바뀌면 안 된다.

        실측: D0 Coin CVR을 빼면 뒷단 판정이 31%, CPI를 빼면 앞단이 37% 뒤집힌다.
        """
        base = [{"kind": "contrast", "title": "EPN", "subject": self.small("s1"),
                 "rest": self.big(), "values": None}]
        fewer = [{**base[0], "values": ["cost", "CTR"]}]
        verdict_of = lambda lines: [l for l in lines if l.startswith(">>")]
        assert verdict_of(idf.block_lines(base, 8)) == \
               verdict_of(idf.block_lines(fewer, 8))


class TestGapDriver:
    """격차를 만든 소재를 되짚는다 — **여기서 결론이 뒤집힌다.**

    8월 EPN/Meta 실측: 소재군 D0 Read CVR이 기존보다 17.58%p 낮아 그대로 읽으면
    "EPN은 열람 전환을 못 만든다"가 된다. 그런데 소재 4개 중 하나를 빼면 기존을
    **넘어선다**. 유형의 문제가 아니라 그 1개의 문제다.
    """

    def pool(self):
        """3개는 기존과 비슷하고, 1개만 크게 나쁘다."""
        return frame([
            row("good1", "Meta", 1000000, 300000, 3000, 500, 300, 20),
            row("good2", "Meta", 1000000, 300000, 3000, 500, 300, 20),
            row("bad", "Meta", 3000000, 300000, 3000, 300, 10, 1),
        ])

    def bench(self):
        return frame([row("r1", "Meta", 50000000, 15000000, 150000, 25000,
                          15000, 1000)])

    def test_finds_the_creative_that_made_the_gap(self):
        found = idf.gap_driver(self.pool(), self.bench(), "CPI")
        assert found and found["ad"] == "bad"
        assert found["recovery"] >= idf.MIN_GAP_RECOVERY

    def test_says_whether_it_beats_the_benchmark_without_it(self):
        found = idf.gap_driver(self.pool(), self.bench(), "CPI")
        assert isinstance(found["beats"], bool)

    def test_no_driver_when_the_gap_is_spread_out(self):
        """모두가 조금씩 나쁘면 한 소재를 짚을 수 없다 — 그때는 말하지 않는다."""
        flat = frame([row(f"a{i}", "Meta", 2000000, 300000, 3000, 400, 100, 5)
                      for i in range(5)])
        assert idf.gap_driver(flat, self.bench(), "CPI") is None

    def test_empty_sides_are_safe(self):
        assert idf.gap_driver(pd.DataFrame(), self.bench(), "CPI") is None
        assert idf.gap_driver(self.pool(), pd.DataFrame(), "CPI") is None

    def test_driver_turns_into_a_concrete_proposal(self):
        """`표본 확보 후 재판단`(무응답) 대신 **그 소재를 빼고 재집행**을 제안한다."""
        cards = contrast_by_media(self.pool(), self.bench())
        driver = idf.gap_driver(self.pool(), self.bench(), "CPI")
        lines = idf.next_step_lines([("EPN", cards[0])],
                                    {("EPN", cards[0]["media"]): driver})
        proposal = next(line for line in lines if line.startswith(">>"))
        assert "bad" in proposal and "제외" in proposal


class TestProse:
    """숫자 나열이 아니라 **풀어쓴 문장**이어야 한다(규리님 지적)."""

    def table_of(self, **deltas):
        return table(**deltas)

    def test_front_reads_as_a_sentence(self):
        state = {"state": -1, "used": "CPI", "fallback": False, "opposed": None}
        text = idf.front_sentence(state, pd.DataFrame([
            {"metric": "CPI", "delta": 0.37, "unit": "%", "better": False,
             "subject": 7668.0, "rest": 5609.0, "share": None}]))
        assert "설치 단가" in text and "높음" in text and "₩7,668" in text

    def test_back_names_the_conversion_step(self):
        state = {"state": -1, "used": "D0 read CVR", "fallback": True,
                 "opposed": None}
        text = idf.back_sentence(state, pd.DataFrame([
            {"metric": "D0 read CVR", "delta": -17.58, "unit": "%p",
             "better": False, "subject": 0.4286, "rest": 0.6044, "share": None}]))
        assert "열람 전환" in text and "낮음" in text

    def test_combined_reading_explains_what_it_means(self):
        """"무슨 일이 있었나"에서 멈추지 않고 "그게 무엇을 뜻하나"를 쓴다."""
        assert idf.COMBINED_READING[(1, -1)]
        assert "유입" in idf.COMBINED_READING[(1, -1)]

    def test_creative_name_itself_is_the_link(self):
        """예전에는 뒤에 `소재 보기`를 따로 붙여 문장이 끊겼다."""
        html = idf.ad_link("9400_X", {"9400_X": "https://drive.example/x"})
        assert html.startswith("<a href=") and ">9400_X</a>" in html
        assert "소재 보기" not in html

    def test_plain_name_when_there_is_no_link(self):
        assert idf.ad_link("9400_X", {}) == "9400_X"


class TestSwingIsNotDoubled:
    def test_swing_lines_are_dropped_when_contrast_exists(self):
        """둘을 함께 찍으면 서로 다른 지표로 반대되는 얘기를 하는 것처럼 보인다."""
        subject = frame([
            row("a", "Meta", 1000000, 300000, 3000, 500, 300, 20),
            row("b", "Meta", 1000000, 300000, 3000, 500, 300, 20),
            row("c", "Meta", 3000000, 300000, 3000, 300, 10, 1),
        ])
        rest = frame([row("r1", "Meta", 50000000, 15000000, 150000, 25000,
                          15000, 1000)])
        sections = [
            {"kind": "contrast", "title": "EPN", "subject": subject,
             "rest": rest, "values": None},
            {"kind": "swing", "title": "EPN 소재단", "scope": subject},
        ]
        lines = idf.block_lines(sections, 8, pool=200000000.0)
        assert not any("제외 시 소재군" in line for line in lines)

    def test_swing_lines_survive_without_contrast(self):
        subject = frame([
            row("a", "Meta", 1000000, 300000, 3000, 500, 300, 20),
            row("b", "Meta", 1000000, 300000, 3000, 500, 300, 20),
            row("c", "Meta", 3000000, 300000, 3000, 3000, 1500, 120),
        ])
        sections = [{"kind": "swing", "title": "소재단", "scope": subject}]
        assert idf.block_lines(sections, 8)


class TestOneSidedVerdict:
    def test_a_clear_front_still_gets_a_proposal(self):
        """예전에는 뒷단 표본이 없으면 그 매체가 next step에서 통째로 빠졌다.

        실측: EPN/TikTok은 앞단 CPI가 18% 우수인데 아무 말도 없이 사라졌다.
        """
        subject = frame([row("s1", "TikTok", 500000, 200000, 30000, 400, 3, 0)])
        rest = frame([row("r1", "TikTok", 90000000, 11000000, 1600000, 55000,
                          29000, 20)])
        cards = contrast_by_media(subject, rest)
        judged = idf.operating_verdict(cards[0])
        assert judged["verdict"] == ""          # 한쪽이 판단 불가라 판정은 없다
        lines = idf.next_step_lines([("EPN", cards[0])])
        assert any(line.startswith(">>") for line in lines)
        assert any("TikTok" in line for line in lines)
