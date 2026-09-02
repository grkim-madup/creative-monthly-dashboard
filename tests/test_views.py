"""4번 「신규 소재 유형별 성과」 — 축별 집계와 블록의 `views` 승격.

여기 있는 것들은 예전에 **진입점(`creative_dashboard.py`) 안에 인라인으로 있어서 어떤
테스트도 건드리지 못하던 것**이다. 숫자가 광고주에게 그대로 가는데 검증이 없었다.
"""
from __future__ import annotations

import pandas as pd
import pytest

import blocks as report_blocks
from creative_data import add_derived_metrics, aggregate_by_axis, explode_extra_info


def frame() -> pd.DataFrame:
    return add_derived_metrics(pd.DataFrame([
        {"ad": "a1", "media": "TikTok", "creative_type": "Highlight",
         "extra_info": "text-thumb", "cost": 300, "impression": 1000,
         "click": 100, "total install": 10, "D0 read": 4, "D0 coin": 1, "D7 coin": 1},
        {"ad": "a2", "media": "Meta", "creative_type": "Highlight",
         "extra_info": "text", "cost": 200, "impression": 500,
         "click": 25, "total install": 5, "D0 read": 2, "D0 coin": 0, "D7 coin": 0},
        {"ad": "a3", "media": "TikTok", "creative_type": None,
         "extra_info": "", "cost": 100, "impression": 400,
         "click": 20, "total install": 2, "D0 read": 1, "D0 coin": 0, "D7 coin": 0},
    ]))


class TestAggregateByAxis:
    def test_sums_within_axis_and_media(self):
        result = aggregate_by_axis(frame(), "creative_type")
        row = result[(result["creative_type"] == "Highlight")
                     & (result["media"] == "TikTok")].iloc[0]
        assert row["cost"] == 300
        # 비율은 평균이 아니라 합계에서 다시 계산해야 한다.
        assert row["CTR"] == pytest.approx(0.1)
        assert row["CPI"] == pytest.approx(30.0)

    def test_missing_axis_value_becomes_unclassified(self):
        """결측을 버리면 합계가 조용히 안 맞는다 — 광고주에게 가는 숫자다."""
        result = aggregate_by_axis(frame(), "creative_type")
        assert "미분류" in set(result["creative_type"])
        assert result["cost"].sum() == 600

    def test_min_cost_filters_rows(self):
        result = aggregate_by_axis(frame(), "creative_type", min_cost=250)
        assert list(result["cost"]) == [300]

    def test_values_filter(self):
        result = aggregate_by_axis(frame(), "creative_type", values=["미분류"])
        assert set(result["creative_type"]) == {"미분류"}

    def test_without_media_split(self):
        result = aggregate_by_axis(frame(), "creative_type", by_media=False)
        row = result[result["creative_type"] == "Highlight"].iloc[0]
        assert row["cost"] == 500

    def test_extra_info_must_be_exploded_by_caller(self):
        """태그 축은 부르는 쪽이 펼쳐서 넣는다. 합계가 전체보다 커지는 게 정상."""
        result = aggregate_by_axis(explode_extra_info(frame()), "extra_info_tag",
                                   by_media=False)
        tags = dict(zip(result["extra_info_tag"], result["cost"]))
        assert tags["text"] == 500      # a1(text-thumb) + a2(text)
        assert tags["thumb"] == 300
        assert sum(tags.values()) > 600  # 태그 간 비교용이지 구성비가 아니다

    def test_empty_or_unknown_axis_is_safe(self):
        assert aggregate_by_axis(frame(), "no_such_column").empty
        assert aggregate_by_axis(frame().iloc[0:0], "creative_type").empty


class TestPromoteViews:
    """예전 블록(조건 하나 = 표 하나)을 읽을 때만 새 형식으로 올린다."""

    def legacy(self, **extra) -> dict:
        block = {"id": "ab12cd", "type": "creative_query", "title": "TEXT형",
                 "conditions": {"extra_info_tag": ["text"]}, "show_table": True,
                 "comment": "<p>본문</p>"}
        block.update(extra)
        return block

    def test_condition_becomes_a_list_view(self):
        promoted = report_blocks.promote_views(self.legacy())
        assert len(promoted["views"]) == 1
        view = promoted["views"][0]
        assert view["kind"] == "list"
        assert view["conditions"] == {"extra_info_tag": ["text"]}

    def test_table_off_means_no_views(self):
        promoted = report_blocks.promote_views(self.legacy(show_table=False))
        assert promoted["views"] == []

    def test_original_conditions_are_not_removed(self):
        """되돌리려면 코드만 되돌리면 되게, 저장된 원본은 건드리지 않는다."""
        promoted = report_blocks.promote_views(self.legacy())
        assert promoted["conditions"] == {"extra_info_tag": ["text"]}

    def test_promotion_does_not_share_the_conditions_object(self):
        block = self.legacy()
        promoted = report_blocks.promote_views(block)
        promoted["views"][0]["conditions"]["extra_info_tag"].append("kr")
        assert block["conditions"]["extra_info_tag"] == ["text"]

    def test_already_new_format_is_left_alone(self):
        block = {"id": "x", "type": "creative_query",
                 "views": [{"id": "v1", "kind": "aggregate"}]}
        assert report_blocks.promote_views(dict(block))["views"] == block["views"]

    def test_note_blocks_are_untouched(self):
        block = {"id": "n1", "type": "note", "comment": ""}
        assert "views" not in report_blocks.promote_views(dict(block))


class TestBlockSchema:
    def test_new_block_starts_with_no_views(self):
        data = report_blocks.empty_blocks()
        block_id = report_blocks.add_block(
            data, report_blocks.SLOT_ANALYSIS, "creative_query", "주제")
        block = report_blocks.find_block(data, report_blocks.SLOT_ANALYSIS, block_id)
        assert block["views"] == []
        assert block["insight"] == ""

    def test_views_and_insight_survive_update_block(self):
        """`BLOCK_DEFAULTS`에 없는 키는 `update_block`이 조용히 버린다 — 그 회귀를 막는다."""
        data = report_blocks.empty_blocks()
        block_id = report_blocks.add_block(
            data, report_blocks.SLOT_ANALYSIS, "creative_query")
        views = [{"id": "v1", "kind": "aggregate", "axis": "format"}]
        report_blocks.update_block(
            data, report_blocks.SLOT_ANALYSIS, block_id,
            views=views, insight="<p>다음 달</p>")
        block = report_blocks.find_block(data, report_blocks.SLOT_ANALYSIS, block_id)
        assert block["views"] == views
        assert block["insight"] == "<p>다음 달</p>"

    def test_two_blocks_do_not_share_the_views_list(self):
        """`BLOCK_DEFAULTS`를 얕은 복사하면 모든 블록이 같은 리스트를 공유한다(`a76aaa2`)."""
        data = report_blocks.empty_blocks()
        first = report_blocks.add_block(data, report_blocks.SLOT_ANALYSIS, "creative_query")
        second = report_blocks.add_block(data, report_blocks.SLOT_ANALYSIS, "creative_query")
        report_blocks.find_block(data, report_blocks.SLOT_ANALYSIS, first)["views"].append({})
        assert report_blocks.find_block(
            data, report_blocks.SLOT_ANALYSIS, second)["views"] == []


class TestMergedNote:
    """텍스트 칸 두 개를 '인사이트' 하나로 합쳤다 — 기존 내용을 버리지 않는지 본다.

    코멘트 유실은 이 프로젝트에서 복구 경로가 없는 실패다(`3ece147`).
    """

    def merged(self, block: dict) -> str:
        # 진입점은 import할 수 없으므로(화면을 그린다) 같은 규약을 여기서 재현한다.
        from next_step import to_preview_html
        return "".join(to_preview_html(block.get(f) or "")
                       for f in ("comment", "insight")
                       if (block.get(f) or "").strip())

    def test_keeps_both_fields(self):
        body = self.merged({"comment": "<p>분석</p>", "insight": "<p>다음 달</p>"})
        assert "분석" in body and "다음 달" in body

    def test_plain_text_and_html_can_be_mixed(self):
        """한쪽은 Quill HTML, 다른 쪽은 예전 text_area의 순수 텍스트일 수 있다.

        먼저 이어 붙이면 HTML 여부 판별이 깨져 줄바꿈이 통째로 사라진다.
        """
        body = self.merged({"comment": "<p>에이치티엠엘</p>", "insight": "첫 줄\n둘째 줄"})
        assert "<br" in body and "에이치티엠엘" in body

    def test_empty_fields_produce_nothing(self):
        assert self.merged({"comment": "", "insight": "   "}) == ""


class TestNoteBlockPivot:
    """NEXT STEP 노트 블록도 피벗 표를 가질 수 있다 — 붙여넣기와 나란히."""

    def test_note_defaults_include_views(self):
        data = report_blocks.empty_blocks()
        block_id = report_blocks.add_block(data, report_blocks.SLOT_NEXT_STEP, "note")
        block = report_blocks.find_block(data, report_blocks.SLOT_NEXT_STEP, block_id)
        assert block["views"] == []
        assert block["tables"] == []          # 붙여넣기 표는 그대로 남는다

    def test_views_survive_update_block(self):
        """`BLOCK_DEFAULTS`에 없는 키는 조용히 버려진다 — 그 회귀를 막는다."""
        data = report_blocks.empty_blocks()
        block_id = report_blocks.add_block(data, report_blocks.SLOT_NEXT_STEP, "note")
        views = [{"id": "v1", "kind": "pivot", "rows": [{"field": "ad"}]}]
        report_blocks.update_block(data, report_blocks.SLOT_NEXT_STEP, block_id,
                                   views=views, tables=["a\tb"])
        block = report_blocks.find_block(data, report_blocks.SLOT_NEXT_STEP, block_id)
        assert block["views"] == views
        assert block["tables"] == ["a\tb"]

    def test_note_blocks_do_not_share_the_views_list(self):
        data = report_blocks.empty_blocks()
        first = report_blocks.add_block(data, report_blocks.SLOT_NEXT_STEP, "note")
        second = report_blocks.add_block(data, report_blocks.SLOT_NEXT_STEP, "note")
        report_blocks.find_block(
            data, report_blocks.SLOT_NEXT_STEP, first)["views"].append({})
        assert report_blocks.find_block(
            data, report_blocks.SLOT_NEXT_STEP, second)["views"] == []

    def test_promote_views_leaves_note_blocks_alone(self):
        """노트 블록은 예전 `conditions` 개념이 없다 — 승격 대상이 아니다."""
        block = {"id": "n1", "type": "note", "comment": "", "tables": []}
        assert "views" not in report_blocks.promote_views(dict(block))
