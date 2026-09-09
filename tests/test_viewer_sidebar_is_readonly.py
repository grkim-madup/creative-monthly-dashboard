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


def _guards_permission(node: ast.AST) -> bool:
    """이 노드 안에서 편집 권한을 확인하는가 — `editor_allowed` 또는 `auth.can_edit()`."""
    if _mentions_editor_allowed(node):
        return True
    for inner in ast.walk(node):
        if (isinstance(inner, ast.Attribute) and inner.attr == "can_edit"
                and isinstance(inner.value, ast.Name) and inner.value.id == "auth"):
            return True
    return False


def _is_gated(call: ast.Call) -> bool:
    """이 호출이 편집 권한으로 막혀 있는가.

    인정하는 형태 셋:
      · `if editor_allowed:` 로 감싼 것
      · `if editor_allowed and st.button(...)` 처럼 같은 식 안 단축 평가
      · **권한을 스스로 확인하는 헬퍼 함수 안**에 있는 것(2026-09-09 추가)

    셋째가 왜 필요한가: 갱신 버튼을 `source_row()` 헬퍼로 묶으면서 위젯이 함수 안으로
    들어갔다. 호출부는 `if editor_allowed:`로 막혀 있지만 위젯의 **어휘적 조상**에는
    그 조건이 없다. 헬퍼가 자기 안에서 권한을 확인하면 호출부가 게이트를 빠뜨려도
    광고주에게 새지 않으므로, 그쪽이 오히려 더 안전하다.
    """
    node: ast.AST | None = call
    while node is not None:
        parent = PARENTS.get(id(node))
        if isinstance(parent, ast.If) and node in parent.body:
            if _guards_permission(parent.test):
                return True
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
            if any(_guards_permission(value) for value in parent.values
                   if value is not node):
                return True
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_guards_permission(stmt) for stmt in parent.body):
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


def test_원본_줄_버튼은_권한_확인_안에_있다():
    """갱신·백업 버튼은 `source_row()` 헬퍼 안에 있다(2026-09-09 개편).

    라벨이 변수(`icon`)라 라벨 목록으로는 잡히지 않으므로 **키**로 찾는다.
    헬퍼가 자기 안에서 `auth.can_edit()`을 확인하는지까지 본다 — 호출부가 게이트를
    빠뜨려도 광고주에게 새지 않아야 한다.
    """
    calls = [call for _label, call in _widget_calls_any()
             if any(kw.arg == "key" and isinstance(kw.value, ast.JoinedStr)
                    and "refresh_" in ast.unparse(kw.value) for kw in call.keywords)]
    assert calls, "원본 줄의 갱신 버튼을 찾지 못했습니다"
    for call in calls:
        assert _is_gated(call), "갱신 버튼이 편집 권한 확인 밖에 있습니다"


def _widget_calls_any() -> list[tuple[str, ast.Call]]:
    """`_widget_calls`와 같지만 **첫 인자가 상수가 아니어도** 모은다."""
    found = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in WIDGET_FUNCS:
            label = (str(node.args[0].value)
                     if node.args and isinstance(node.args[0], ast.Constant) else "")
            found.append((label, node))
    return found


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
