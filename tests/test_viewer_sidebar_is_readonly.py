# -*- coding: utf-8 -*-
"""광고주(보기 전용)에게 사내 운영 컨트롤이 보이지 않는지.

이 화면은 광고주에게 그대로 공유하는 리포트다. 사이드바에 있던
`구글시트 링크` 입력창 · 재로딩 버튼 3개 · `구글 비용 마크업 배율`은
누르면 실제로 동작했다(쿼터를 쓰고, 마크업은 그 세션의 구글 숫자를 바꿨다).
2026-09-08에 전부 `editor_allowed` 뒤로 옮겼다.

진입점은 어떤 테스트도 import하지 않으니(import하면 화면을 그린다) AST로 본다.
문자열 검색이 아니라 **감싼 조건을 실제로 확인**한다 — 주석에 `editor_allowed`를
적어 두는 것만으로 통과하면 검사가 아니다.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRY = next(ROOT / name for name in ("creative_dashboard.py", "app.py")
             if (ROOT / name).exists())
TREE = ast.parse(ENTRY.read_text(encoding="utf-8"))

#: 편집 권한자만 볼 수 있어야 하는 위젯의 첫 인자(라벨).
EDITOR_ONLY_WIDGETS = [
    "구글시트 링크",
    "시트에서 다시 불러오기",
    "Dropbox에서 다시 불러오기",
    "소재 목록 새로고침",
    "구글 비용 마크업 배율",
]

WIDGET_FUNCS = {"button", "text_input", "number_input", "segmented_control"}


def _parents() -> dict[int, ast.AST]:
    table: dict[int, ast.AST] = {}
    for node in ast.walk(TREE):
        for child in ast.iter_child_nodes(node):
            table[id(child)] = node
    return table


PARENTS = _parents()


def _mentions_editor_allowed(node: ast.AST) -> bool:
    return any(isinstance(inner, ast.Name) and inner.id == "editor_allowed"
               for inner in ast.walk(node))


def _widget_calls() -> list[tuple[str, ast.Call]]:
    found = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in WIDGET_FUNCS):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        found.append((str(node.args[0].value), node))
    return found


def _is_gated(call: ast.Call) -> bool:
    """이 호출이 `editor_allowed`로 막혀 있는가.

    `if editor_allowed:` 로 감싼 경우와 `if editor_allowed and st.button(...)`처럼
    같은 식 안에서 단축 평가로 막은 경우를 모두 인정한다.
    """
    node: ast.AST | None = call
    while node is not None:
        parent = PARENTS.get(id(node))
        if isinstance(parent, ast.If) and node in parent.body:
            if _mentions_editor_allowed(parent.test):
                return True
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
            if any(_mentions_editor_allowed(value) for value in parent.values
                   if value is not node):
                return True
        node = parent
    return False


@pytest.mark.parametrize("label", EDITOR_ONLY_WIDGETS)
def test_widget_is_gated_on_edit_permission(label: str):
    calls = [call for found, call in _widget_calls() if found == label]
    assert calls, f"{label} 위젯을 찾지 못했습니다 — 라벨이 바뀌었으면 이 목록도 고칠 것"
    for call in calls:
        assert _is_gated(call), (
            f"{label} 위젯이 편집 권한 게이트 밖에 있습니다 — 광고주 화면에 보입니다")


def test_the_check_actually_catches_an_ungated_widget():
    """검사가 실제로 잡는지 스스로 확인한다(통과만 하는 검사를 막는다)."""
    module = ast.parse('import streamlit as st\nst.button("아무 버튼")\n')
    global PARENTS
    saved = PARENTS
    try:
        PARENTS = {id(child): node for node in ast.walk(module)
                   for child in ast.iter_child_nodes(node)}
        call = next(n for n in ast.walk(module) if isinstance(n, ast.Call))
        assert not _is_gated(call)
    finally:
        PARENTS = saved
