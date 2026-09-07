# -*- coding: utf-8 -*-
"""소재 식별(`ad_group`)과 성과 집계(`ad`)를 분리한다.

규리님: *"테이블 성과로 볼 때는 통합되면 안 돼. 하지만 소재 유형별 성과를 봐서
썸네일과 소재 개수를 확인할 땐 통합해야 해. A 소재를 메타에서는 ALL 사이즈로,
틱톡은 9X16으로 운영했으면 두 성과는 별도로 나와야 해. 하지만 소재 유형별 성과를
볼 땐 A 소재는 ALL이던 9X16이던 하나의 A 소재로 보여야 해."*

⚠ 한 번 `ad`를 덮어써서 합치도록 만들었다가 되돌렸다. 그렇게 하면 매체별로 다른
규격을 돌린 사실이 표에서 사라진다.
"""
import pandas as pd

from creative_data import (
    add_derived_metrics,
    ad_group_key,
    aggregate_by,
    attach_creative_attributes,
    representative_ads,
)

BASE = "10211_變成伯爵家的混混_IMG_Madup_SingleImage"


def row(ad, media, size_hint, cost):
    return {"ad": ad, "media": media, "cost": cost, "impression": 1000,
            "click": 100, "total install": 10, "D0 read": 5, "D0 coin": 1,
            "D7 coin": 0}


def frame():
    return add_derived_metrics(pd.DataFrame([
        row(f"{BASE}_ALL_TITLE2", "Meta", "ALL", 2734.0),
        row(f"{BASE}_1X1_TITLE2", "TikTok", "1X1", 5512.0),
    ]))


class TestIdentity:
    def test_dimension_token_is_dropped(self):
        assert (ad_group_key(f"{BASE}_ALL_TITLE2", "ALL")
                == ad_group_key(f"{BASE}_1X1_TITLE2", "1X1"))

    def test_other_tokens_still_separate_creatives(self):
        """USP·Extra Info가 다르면 다른 소재다 — 규격만 빼는 것이다."""
        assert (ad_group_key(f"{BASE}_1X1_TITLE2", "1X1")
                != ad_group_key(f"{BASE}_1X1_TITLE3", "1X1"))

    def test_unknown_size_keeps_the_name(self):
        assert ad_group_key("이름만있는소재", None) == "이름만있는소재"

    def test_column_is_attached(self):
        got = attach_creative_attributes(frame())
        assert got["ad_group"].nunique() == 1
        assert got["ad"].nunique() == 2


class TestPerformanceStaysSeparate:
    """성과 표는 `ad`로 집계한다 — 규격·매체가 다른 집행이 합산되면 안 된다."""

    def test_aggregating_by_ad_keeps_both_rows(self):
        got = aggregate_by(attach_creative_attributes(frame()), ["ad", "media"])
        assert len(got) == 2
        assert set(got["media"]) == {"Meta", "TikTok"}

    def test_ad_is_never_rewritten(self):
        got = attach_creative_attributes(frame())
        assert f"{BASE}_ALL_TITLE2" in set(got["ad"])
        assert f"{BASE}_1X1_TITLE2" in set(got["ad"])

    def test_grouping_by_ad_group_would_merge_them(self):
        """이 함수를 집계에 쓰면 안 되는 이유를 명시적으로 남긴다."""
        got = attach_creative_attributes(frame())
        merged = got.groupby("ad_group")["cost"].sum()
        assert len(merged) == 1
        assert merged.iloc[0] == 2734.0 + 5512.0


class TestRepresentativeForThumbnails:
    def test_one_row_per_group(self):
        got = representative_ads(attach_creative_attributes(frame()))
        assert len(got) == 1

    def test_all_is_not_chosen_as_the_face(self):
        """`ALL` 이름으로는 Drive에 파일이 없다(실측 8,577개 중 0개)."""
        got = representative_ads(attach_creative_attributes(frame()))
        assert got.iloc[0]["ad"] == f"{BASE}_1X1_TITLE2"

    def test_vertical_wins_over_square(self):
        d = add_derived_metrics(pd.DataFrame([
            row(f"{BASE}_1X1_TITLE2", "TikTok", "1X1", 9_000_000.0),
            row(f"{BASE}_9X16_TITLE2", "TikTok", "9X16", 1.0),
        ]))
        got = representative_ads(attach_creative_attributes(d))
        assert got.iloc[0]["ad"] == f"{BASE}_9X16_TITLE2"

    def test_spend_breaks_ties_among_unlisted_sizes(self):
        d = add_derived_metrics(pd.DataFrame([
            row(f"{BASE}_2X3_TITLE2", "TikTok", "2X3", 10.0),
            row(f"{BASE}_8X1_TITLE2", "TikTok", "8X1", 99.0),
        ]))
        got = representative_ads(attach_creative_attributes(d))
        assert got.iloc[0]["ad"] == f"{BASE}_8X1_TITLE2"

    def test_empty_is_safe(self):
        assert representative_ads(pd.DataFrame()).empty


def test_count_uses_ad_group_on_screen():
    """진입점은 import할 수 없으니 소스로 확인한다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    entry = next((root / n for n in ("creative_dashboard.py", "app.py")
                  if (root / n).exists()))
    source = entry.read_text(encoding="utf-8")
    assert '_count_key = "ad_group" if "ad_group" in scope_of_block.columns' in source
    assert "representative_ads(scope)" in source
