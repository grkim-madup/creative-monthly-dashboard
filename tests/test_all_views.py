# -*- coding: utf-8 -*-
"""`blocks.all_views` — 월 고정이 조용히 실패하던 자리 (2026-10-02).

규리님이 `지금 고정하기`를 눌러 발견했다:
`고정 실패: 'BlocksState' object has no attribute 'values'`

`load_state`는 **`dict`가 아니라 `BlocksState`**를 돌려주는데 진입점이
`(state or {}).values()` 로 dict처럼 다뤘다. **2026-09-30부터 계속 깨져 있었고**
아무도 몰랐다 — 그 순회가 **진입점 안에 있어서 어떤 테스트도 부르지 못했기 때문**이다.

그래서 로직을 `blocks.py`로 옮겼다. 이 파일이 그 계약을 고정한다.
"""
import blocks


def state(data):
    return blocks.BlocksState(data=data)


VIEWS = {
    "analysis": [
        {"id": "b1", "views": [{"id": "v1", "through_date": "2026-10-01"},
                               {"id": "v2", "from_date": "2026-06-01"}]},
        {"id": "b2", "views": []},
    ],
    "next_step": [{"id": "b3", "views": [{"id": "v3"}]}],
}


class TestBlocksState:
    def test_BlocksState를_받는다(self):
        """**이 테스트가 사고의 본체다.** dict처럼 다루면 AttributeError가 난다."""
        got = blocks.all_views(state(VIEWS))
        assert [v["id"] for v in got] == ["v1", "v2", "v3"]

    def test_dict도_받는다(self):
        """옛 호출부가 남아 있어도 깨지지 않아야 한다."""
        assert len(blocks.all_views(VIEWS)) == 3


class TestEmpty:
    def test_빈_상태(self):
        assert blocks.all_views(state({})) == []

    def test_None(self):
        assert blocks.all_views(None) == []

    def test_읽기_실패_상태(self):
        """`status == "error"`여도 터지지 않는다 — 고정을 막을 이유는 아니다."""
        bad = blocks.BlocksState(data={}, status="error", reason="quota")
        assert blocks.all_views(bad) == []


class TestJunk:
    def test_블록이_dict가_아니면_건너뛴다(self):
        assert blocks.all_views(state({"analysis": ["쓰레기", None]})) == []

    def test_뷰가_dict가_아니면_건너뛴다(self):
        data = {"analysis": [{"id": "b", "views": ["쓰레기", {"id": "ok"}]}]}
        assert [v["id"] for v in blocks.all_views(state(data))] == ["ok"]

    def test_views가_없으면_건너뛴다(self):
        assert blocks.all_views(state({"analysis": [{"id": "b"}]})) == []
