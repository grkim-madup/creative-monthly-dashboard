# -*- coding: utf-8 -*-
"""기간 예외에 **시작일**을 넣는다 (규리님 2026-10-02).

*"장르별 성과 쪽도 기간을 6월~9월까지 넓게 보고 싶은데. 기간 예외 토글에서 기간
설정할 수 있게 해줘."*

종료일만 있던 동안에는 시작이 **리포트 월 1일로 고정**이라 `2026-06-01`을 넣으면
`9/1 ~ 6/1` 이라는 거꾸로 된 구간이 되어 **표가 통째로 비었다**(규리님 화면에서
`조건에 맞는 소재가 없습니다`로 확인).
"""
import ast
import pathlib

import pandas as pd
import pytest

import media_snapshot
import view_state

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINTS = [n for n in ("creative_dashboard.py", "app.py") if (ROOT / n).exists()]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class TestSchema:
    def test_기본값은_빈_값이다(self):
        """비면 **지금까지의 동작 그대로**여야 한다 — 레거시 뷰 보호."""
        assert view_state.VIEW_DEFAULTS["from_date"] == ""

    def test_레거시_뷰도_필드를_갖는다(self):
        view = view_state.view_with_defaults({"kind": "pivot", "id": "x"})
        assert view["from_date"] == ""

    def test_구글_뷰에서는_비운다(self):
        """구글 애셋 데이터에는 날짜 컬럼이 아예 없어 걸어도 지킬 방법이 없다."""
        view = view_state.view_with_defaults(
            {"kind": "google", "id": "g", "from_date": "2026-06-01",
             "through_date": "2026-10-01"})
        assert view["from_date"] == ""
        assert view["through_date"] == ""


class TestWidgetRoundTrip:
    def test_체크를_끄면_둘_다_비운다(self):
        """날짜 위젯 값은 체크를 꺼도 세션에 남는다 — 그것만 읽으면 되살아난다."""
        view = view_state.view_with_defaults(
            {"kind": "pivot", "id": "v", "from_date": "2026-06-01",
             "through_date": "2026-09-30"})
        session = {"pvthru_on_v": False,
                   "pvfrom_v": "2026-06-01", "pvthru_v": "2026-09-30"}
        out = view_state.view_from_widgets(view, "v", session)
        assert out["from_date"] == ""
        assert out["through_date"] == ""

    def test_켜면_두_날짜가_저장된다(self):
        view = view_state.view_with_defaults({"kind": "pivot", "id": "v"})
        session = {"pvthru_on_v": True,
                   "pvfrom_v": "2026-06-01", "pvthru_v": "2026-09-30"}
        out = view_state.view_from_widgets(view, "v", session)
        assert out["from_date"] == "2026-06-01"
        assert out["through_date"] == "2026-09-30"


def frame():
    return pd.DataFrame({
        "month": [6.0, 7.0, 9.0, 9.0, 10.0],
        "date": ["2026-06-15", "2026-07-10", "2026-09-05", "2026-09-30",
                 "2026-10-01"],
        "cost": [1.0, 2.0, 3.0, 4.0, 5.0],
    })


class TestFreeze:
    """⚠ **고정이 구간을 모르면 그 표만 조용히 줄어든다.**"""

    def test_앞쪽_달도_함께_얼린다(self):
        rows = media_snapshot.rows_for(frame(), 9, from_date="2026-06-01")
        assert sorted(rows["month"]) == [6.0, 7.0, 9.0, 9.0]

    def test_뒤쪽은_그대로_동작한다(self):
        rows = media_snapshot.rows_for(frame(), 9, through_date="2026-10-01")
        assert sorted(rows["month"]) == [9.0, 9.0, 10.0]

    def test_양쪽을_같이_줄_수_있다(self):
        rows = media_snapshot.rows_for(frame(), 9, through_date="2026-10-01",
                                       from_date="2026-07-01")
        assert sorted(rows["month"]) == [7.0, 9.0, 9.0, 10.0]

    def test_안_주면_그_달만(self):
        rows = media_snapshot.rows_for(frame(), 9)
        assert sorted(rows["month"]) == [9.0, 9.0]


class TestEntrypoint:
    @pytest.mark.parametrize("name", ENTRYPOINTS)
    def test_고정이_시작일을_모은다(self, name):
        """`freeze_period`가 **가장 이른 시작일**까지 모아 스냅샷에 넘겨야 한다."""
        body = source(name)
        assert "def freeze_period(" in body
        node = next(n for n in ast.walk(ast.parse(body))
                    if isinstance(n, ast.FunctionDef) and n.name == "freeze_period")
        assert "from_date" in ast.unparse(node)

    @pytest.mark.parametrize("name", ENTRYPOINTS)
    def test_스냅샷에_시작일을_넘긴다(self, name):
        """모아 놓고 안 넘기면 아무 소용이 없다 — 실제로 인자로 가는지 본다."""
        call = next(
            n for n in ast.walk(ast.parse(source(name)))
            if isinstance(n, ast.Call)
            and ast.unparse(n.func).endswith("media_snapshot.save"))
        assert "from_date" in {kw.arg for kw in call.keywords}, name

    @pytest.mark.parametrize("name", ENTRYPOINTS)
    def test_구간_판정은_한_곳이다(self, name):
        """자르는 쪽·찍는 쪽이 각자 계산하면 조용히 갈린다."""
        body = source(name)
        assert "def period_bounds(" in body
        for fn in ("through_date_scope", "render_period_note"):
            node = next(n for n in ast.walk(ast.parse(body))
                        if isinstance(n, ast.FunctionDef) and n.name == fn)
            assert "period_bounds(" in ast.unparse(node), f"{name}:{fn}"
