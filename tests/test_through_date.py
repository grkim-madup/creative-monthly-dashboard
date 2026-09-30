# -*- coding: utf-8 -*-
"""기간 예외(`through_date`) — **이 표만** 리포트 월을 넘겨 본다.

규리님(2026-09-30): *"모든 데이터는 9월 말일까지지만, 이 용사의 발라드 섹션만
예외로 10/1일자 데이터까지 포함시킬 예정이야."*

⚠ 이 기능의 위험은 **조용히 어긋나는 것**이다. 사이드바 기간 줄과 적합성 점검은
계속 리포트 월만 말하므로, 표가 더 보여주면 광고주가 총괄과 대조하다 어긋난 숫자를
본다. 그래서 기간을 표에 찍는 각주가 이 기능의 일부다.
"""
import ast
import pathlib

import pytest

from view_state import VIEW_DEFAULTS, view_with_defaults, view_from_widgets

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINTS = [n for n in ("creative_dashboard.py", "app.py") if (ROOT / n).exists()]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# ------------------------------------------------------------- 스키마

def test_기본값은_비어_있다():
    """비면 지금 동작 그대로여야 한다 — 레거시 뷰가 전부 여기 해당한다."""
    assert VIEW_DEFAULTS["through_date"] == ""
    assert view_with_defaults({})["through_date"] == ""


def test_저장된_값을_유지한다():
    assert view_with_defaults({"through_date": "2026-10-01"})["through_date"] == "2026-10-01"


def test_구글_표는_기간_예외를_못_쓴다():
    """⚠ 구글 애셋 데이터에는 **날짜 컬럼이 아예 없다**(리포트 헤더의 월만 있다).
    걸어도 지킬 방법이 없으므로 읽을 때 비운다."""
    view = view_with_defaults({"kind": "google", "through_date": "2026-10-01"})
    assert view["through_date"] == ""


# ------------------------------------------------------------- 저장 경로

def test_체크를_끄면_저장되지_않는다():
    """⚠ 날짜 위젯 값은 체크를 꺼도 세션에 남는다 — 그것만 읽으면 되살아난다."""
    session = {"pvthru_on_v1": False, "pvthru_v1": "2026-10-01"}
    out = view_from_widgets({"id": "v1", "through_date": "2026-10-01"}, "v1", session)
    assert out["through_date"] == ""


def test_체크가_켜져_있으면_날짜를_받는다():
    session = {"pvthru_on_v1": True, "pvthru_v1": "2026-10-01"}
    out = view_from_widgets({"id": "v1"}, "v1", session)
    assert out["through_date"] == "2026-10-01"


def test_세션에_없으면_저장값을_지킨다():
    """편집기를 안 연 표는 값이 그대로 남아야 한다."""
    out = view_from_widgets({"id": "v1", "through_date": "2026-10-01"}, "v1", {})
    assert out["through_date"] == "2026-10-01"


# --------------------------------------------- 화면 계약 (진입점은 import 못 한다)

@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_확장_프레임은_전월_프레임에서_만든다(name):
    """`all_months(_named)`는 사이드바 필터가 걸려 있고 월 필터만 없는 프레임이다."""
    node = next(n for n in ast.walk(ast.parse(read(name)))
                if isinstance(n, ast.FunctionDef) and n.name == "through_date_scope")
    body = ast.unparse(node)
    assert "all_months_named" in body and "all_months" in body


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_확장_프레임에도_수기_분류를_입힌다(name):
    """`all_months`에는 안 걸려 있다 — 안 입히면 같은 소재가 이 표에서만 다르게
    분류된다."""
    node = next(n for n in ast.walk(ast.parse(read(name)))
                if isinstance(n, ast.FunctionDef) and n.name == "through_date_scope")
    assert "manual_overrides.apply" in ast.unparse(node), name


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_기간을_표에_찍는다(name):
    """⚠ **광고주도 본다.** 사이드바 기간 줄은 계속 리포트 월만 말한다."""
    source = read(name)
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == "render_period_note")
    body = ast.unparse(node)
    assert "sec-legend" in body, f"{name}: 편집자 전용 스타일로 그리면 광고주가 못 본다"
    assert "can_edit" not in body and "editor_allowed" not in body, name
    # 표를 그린 뒤 실제로 불러야 한다.
    view = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == "render_view")
    assert "render_period_note(" in ast.unparse(view), name


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_기간이_비면_각주를_안_그린다(name):
    """평소 표에 군더더기를 남기지 않는다."""
    node = next(n for n in ast.walk(ast.parse(read(name)))
                if isinstance(n, ast.FunctionDef) and n.name == "render_period_note")
    body = ast.unparse(node)
    assert "if not through" in body or "if not through_date" in body, name


# --------------------------------------------- 고정(freeze)에서 안 사라지게

def _frame():
    import pandas as pd
    return pd.DataFrame({
        "month": [9.0, 9.0, 10.0, 10.0, 8.0],
        "date": ["2026-09-19", "2026-09-30", "2026-10-01", "2026-10-02", "2026-08-31"],
        "cost": [100.0, 200.0, 300.0, 400.0, 500.0],
    })


def test_기간_예외가_없으면_그_달만_얼린다():
    import media_snapshot
    rows = media_snapshot.rows_for(_frame(), 9)
    assert list(rows["date"]) == ["2026-09-19", "2026-09-30"]


def test_기간_예외를_주면_그_날짜까지_함께_얼린다():
    """⚠ 이게 없으면 9월을 고정하는 순간 10/1까지 보던 표가 **조용히** 줄어든다."""
    import media_snapshot
    rows = media_snapshot.rows_for(_frame(), 9, "2026-10-01")
    assert list(rows["date"]) == ["2026-09-19", "2026-09-30", "2026-10-01"]
    assert rows["cost"].sum() == 600.0


def test_예외_날짜를_넘는_행은_안_들어간다():
    import media_snapshot
    rows = media_snapshot.rows_for(_frame(), 9, "2026-10-01")
    assert "2026-10-02" not in list(rows["date"])


def test_리포트_월보다_앞선_달은_안_들어간다():
    """예외는 '월을 넘겨 더 본다'는 뜻이다 — 8월을 끌어오면 안 된다."""
    import media_snapshot
    rows = media_snapshot.rows_for(_frame(), 9, "2026-10-01")
    assert "2026-08-31" not in list(rows["date"])


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_고정이_기간_예외를_넘긴다(name):
    source = read(name)
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == "freeze_month")
    assert "through_date" in ast.unparse(node), (
        f"{name}: 고정이 기간 예외를 모르면 그 표만 줄어든다")
