# -*- coding: utf-8 -*-
"""구글 표(`kind == "google"`)가 **메타·틱톡 프레임에 닿지 않는지** 고정한다.

계획서(`jaunty-dancing-ember.md`)가 *"이 작업 최대의 조용한 실패 지점"* 으로 지목한
자리다: 화면 곳곳이 `kind != "compare"`로 갈라져 있어서, **새 종류를 넣는 순간 구글
뷰가 자동으로 피벗 취급되어** `filtered_scope(named_overview, {"title_kr": …})`로
흘러간다. 구글은 소재명 파싱 축이 전부 빈 값이라 가짜 `미분류` 버킷이 생긴다
(커밋 `883600f`가 그 사고다).

그래서 판정을 **허용목록**(`== "pivot"`)으로 뒤집었고, 이 파일이 그 상태를 지킨다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import view_state

ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def entrypoints():
    found = [(n, pathlib.Path(n).read_text(encoding="utf-8"))
             for n in ENTRYPOINTS if pathlib.Path(n).exists()]
    if not found:
        pytest.skip("진입점을 찾지 못했습니다")
    return found


# ------------------------------------------------------- 허용목록

def test_부정_조건으로_종류를_가르지_않는다():
    """`!= "compare"` 하나가 남아 있으면 새 종류가 조용히 피벗으로 떨어진다.

    이 검사 하나가 그 계열 버그 전체를 막는다 — 다음에 종류를 또 늘려도 같다.
    """
    for name, source in entrypoints():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            text = ast.unparse(node)
            if '"compare"' in text or "'compare'" in text:
                assert "!=" not in text, (
                    f"{name}: 부정 조건으로 종류를 가른다 — `== \"pivot\"`을 쓸 것: {text}")


def test_알_수_없는_종류는_표를_그리지_않는다():
    """옛 배포판이 새 종류를 만나면 그 달 메타·틱톡 전체 표를 경고 없이 그린다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_view")
        body = ast.unparse(fn)
        assert 'kind\'] != \'pivot\'' in body or 'kind"] != "pivot"' in body, name
        assert "최신 버전에서만" in body, f"{name}: 알 수 없는 종류 안내가 없다"


def test_구글_분기가_메타_집계보다_먼저다():
    """`pivot_frame(named_overview, …)`에 닿기 전에 갈라져야 한다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_view")
        body = ast.unparse(fn)
        google_at = body.find("render_google_view")
        pivot_at = body.find("pivot_frame(named_overview")
        assert google_at > 0, f"{name}: 구글 분기가 없다"
        assert pivot_at < 0 or google_at < pivot_at, (
            f"{name}: 구글 분기가 메타 집계보다 뒤에 있다")


# ------------------------------------------------------- 프레임 격리

def test_구글_뷰는_메타_프레임을_건드리지_않는다():
    """`render_google_view` 안에서 `named_overview` 계열을 부르지 않는다.

    ⚠ **문자열이 아니라 이름 노드로 본다.** 문자열로 찾으면 docstring·주석에 적힌
      설명("`named_overview`를 건드리지 않는다")까지 걸린다 — 실제로 그렇게 실패했다.
    """
    BANNED = {"named_overview", "pivot_frame", "filtered_scope",
              "explode_extra_info", "aggregate_by"}
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_google_view")
        used = {node.id for node in ast.walk(fn) if isinstance(node, ast.Name)}
        used |= {node.attr for node in ast.walk(fn) if isinstance(node, ast.Attribute)}
        hit = used & BANNED
        assert not hit, f"{name}: 구글 표가 {', '.join(sorted(hit))}를 쓴다"


def test_두_프레임을_합치지_않는다():
    """`pd.concat`으로 구글과 메타를 섞으면 CPI가 33% 낮게 보인다."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if "concat" not in ast.unparse(node.func):
                continue
            text = ast.unparse(node)
            mixes = ("named_overview" in text and
                     ("google_all" in text or "google_pivot" in text))
            assert not mixes, f"{name}: 구글과 메타 프레임을 합친다 — {text[:80]}"


# ------------------------------------------------------- 저장 형식

def test_구글_설정은_별도_키에_담는다():
    """`rows`/`values`/`filters`를 재사용하면 구글 축이 메타 프레임을 읽는 코드에
    닿는다 — 키를 나누면 그 사고가 **구조적으로** 불가능해진다."""
    for key in ("g_rows", "g_values", "g_filters", "g_creative_only"):
        assert key in view_state.VIEW_DEFAULTS, key


def test_구글_뷰는_메타_전용_기능을_끈다():
    """대조군·썸네일·소재 추가는 구글에서 원리적으로 성립하지 않는다."""
    got = view_state.view_with_defaults({
        "kind": "google", "contrast": True, "thumbs": True,
        "include_ads": ["어떤소재"], "contrast_field": "media",
    })
    assert got["contrast"] is False and got["thumbs"] is False
    assert got["include_ads"] == [] and got["contrast_field"] == ""


def test_피벗_뷰는_그대로_둔다():
    """구글 정규화가 메타 표의 기능을 끄면 안 된다."""
    got = view_state.view_with_defaults({
        "kind": "pivot", "contrast": True, "thumbs": True, "include_ads": ["소재"],
    })
    assert got["contrast"] is True and got["thumbs"] is True
    assert got["include_ads"] == ["소재"]


def test_구글_설정이_위젯에서_저장된다():
    """저장 경로가 `g_*`를 안 읽으면 설정이 화면에만 있고 저장되지 않는다."""
    session = {
        "vkind_k": "google", "gvrows_k": ["title_kr", "os"],
        "gvvals_k": ["cost", "CPI"], "gvfilters_k": ["os"],
        "gvfval_k_os": ["AOS"], "gvonly_k": False,
    }
    got = view_state.view_from_widgets({"id": "v1"}, "k", session)
    assert got["kind"] == "google"
    assert got["g_rows"] == [{"field": "title_kr"}, {"field": "os"}]
    assert got["g_values"] == ["cost", "CPI"]
    assert got["g_filters"] == {"os": ["AOS"]}
    assert got["g_creative_only"] is False


def test_값이_빈_필터는_저장하지_않는다():
    """화면(빈 멀티셀렉트)과 저장이 어긋나지 않게 — 피벗과 같은 규칙."""
    session = {"vkind_k": "google", "gvfilters_k": ["os"], "gvfval_k_os": []}
    assert view_state.view_from_widgets({"id": "v1"}, "k", session)["g_filters"] == {}


def test_위젯_키가_피벗과_겹치지_않는다():
    """키를 재사용하면 한 블록에서 표 종류를 바꿀 때 메타 축이 구글 표에 남는다."""
    session = {"vkind_k": "google", "pvrows_k": ["creative_type"],
               "pvvals_k": ["D0 coin"]}
    got = view_state.view_from_widgets({"id": "v1"}, "k", session)
    assert got["g_rows"] == [], "피벗 행이 구글 행으로 샜다"
    assert got["g_values"] == [], "피벗 값이 구글 값으로 샜다"


# ------------------------------------------------------- 각주

def test_배분_각주가_편집_모드_밖이다():
    """광고주도 봐야 하는 문구다 — `editing` 안에 감싸면 광고주 화면에서 사라진다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_google_view")
        note_at = ast.unparse(fn).find("GOOGLE_ALLOCATION_NOTE")
        assert note_at > 0, f"{name}: 배분 각주가 없다"
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and "editing" in ast.unparse(node.test):
                assert "GOOGLE_ALLOCATION_NOTE" not in ast.unparse(node), (
                    f"{name}: 배분 각주가 편집 모드 안에 있다")
