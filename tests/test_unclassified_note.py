# -*- coding: utf-8 -*-
"""`미분류` 각주는 **광고주도 본다.**

규리님(2026-09-30): *"테이블 하단에 미분류가 왜 발생했는지 각주를 달아놔."*

표에 `미분류` 줄이 그대로 나가는데 설명이 없으면 "분류를 안 한 것"으로 읽힌다.
9월 실측으로는 **89.6%가 믹스·테마 캠페인**이라 원리적으로 작품 단위가 없는 집행이다.

⚠ 이 각주를 `if editing:` 이나 `auth.can_edit()` 안에 넣으면 안 된다 — 그 순간
광고주 화면에서만 사라지고, 정작 설명이 필요한 사람이 못 본다.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTE = "render_unclassified_note"


#: 진입점 이름만 파라미터로 쓴다 — 소스를 파라미터에 실으면 pytest가 테스트 id에
#: 파일 전체를 박아 환경변수 길이 한도(32,767자)를 넘긴다(실제로 터졌다).
ENTRYPOINTS = [n for n in ("creative_dashboard.py", "app.py") if (ROOT / n).exists()]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_각주_함수가_있고_권한을_보지_않는다(name):
    source = read(name)
    tree = ast.parse(source)
    node = _function(tree, NOTE)
    assert node is not None, f"{name}: {NOTE} 를 찾지 못했습니다"
    body = ast.unparse(node)
    assert "can_edit" not in body, f"{name}: 각주가 편집 권한에 묶여 있습니다"
    assert "editor_allowed" not in body, f"{name}: 각주가 보기 모드에서 사라집니다"


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_표를_그린_뒤_편집_블록_밖에서_부른다(name):
    source = read(name)
    tree = ast.parse(source)
    view = _function(tree, "render_view")
    assert view is not None, f"{name}: render_view 를 찾지 못했습니다"

    # `if editing:` 같은 조건 안에 들어가 있으면 안 된다.
    for node in ast.walk(view):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "editing" not in test and "editor_allowed" not in test:
            continue
        assert NOTE not in ast.unparse(node), (
            f"{name}: 각주가 `{test}` 안에 있습니다 — 광고주 화면에서 사라집니다"
        )

    calls = [n for n in ast.walk(view)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == NOTE]
    assert calls, f"{name}: render_view 가 {NOTE} 를 부르지 않습니다"


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_장르_컬럼을_두_이름으로_찾는다(name):
    """순위표는 필드 이름(`genre_group`), 일반 표는 라벨(`장르`)로 컬럼을 들고 온다.

    한쪽만 보면 **장르 프리셋 표(항상 순위표다)에서 각주가 조용히 안 뜬다** — 예전
    편집자 경고가 정확히 그래서 한 번도 뜨지 않았다. `genre_column_of`가 둘 다 본다.
    """
    source = read(name)
    node = _function(ast.parse(source), "genre_column_of")
    assert node is not None, f"{name}: genre_column_of 를 찾지 못했습니다"
    body = ast.unparse(node)
    assert "GENRE_COLUMN" in body and "field_label" in body, (
        f"{name}: 필드 이름과 라벨 중 한쪽만 봅니다"
    )
    target = _function(ast.parse(source), NOTE)
    assert "genre_column_of" in ast.unparse(target), (
        f"{name}: {NOTE} 가 컬럼 탐색을 따로 하고 있습니다 — 두 벌이 되면 갈립니다"
    )
