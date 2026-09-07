# -*- coding: utf-8 -*-
"""함수가 **어디에도 정의되지 않은 이름**을 읽는지 잡는다.

린터를 설치하지 않는다 — 이 PC는 시스템 파이썬을 옆 프로젝트(ASA 대시보드)와
공유해서, 패키지를 넣으면 그쪽에 영향이 간다. 그래서 필요한 검사만 AST로 한다.

**왜 필요한가**: `test_no_use_before_assign.py`는 *같은 함수 안*에서 할당 전에 읽는
경우만 잡는다. 실제로 2026-09-08에 한 함수의 지역 변수(`frozen_meta`)를 **다른
함수에서** 읽는 코드를 썼는데, 문법도 맞고 그 테스트도 통과했다. 진입점은 어떤
테스트도 import하지 못하므로(import하면 화면을 그린다) 이런 건 정적으로만 잡힌다.
"""
import ast
import builtins
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 검사 대상. 진입점이 가장 위험하다(테스트가 import하지 못한다).
TARGETS = ("creative_dashboard.py", "app.py", "ui.py", "blocks.py",
           "insight_draft.py", "creative_data.py", "media_snapshot.py",
           "app_settings.py", "manual_picks.py")

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE = FUNC + (ast.ClassDef,)


def _args(node) -> set[str]:
    a = node.args
    names = {arg.arg for arg in a.posonlyargs + a.args + a.kwonlyargs}
    for extra in (a.vararg, a.kwarg):
        if extra:
            names.add(extra.arg)
    return names


def _bound_here(body) -> set[str]:
    """이 스코프에서 **직접** 묶이는 이름. 중첩 함수·클래스 본문에는 안 들어간다.

    안 들어가는 게 핵심이다 — 통째로 훑으면 다른 함수의 지역 변수까지 "정의됨"으로
    세어 버려서, 정작 잡으려던 결함(다른 함수의 지역 변수를 읽는 것)을 놓친다.
    """
    names: set[str] = set()
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, SCOPE):
            names.add(node.name)                  # 이름만 — 본문은 건너뛴다
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0]
                         for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        stack.extend(ast.iter_child_nodes(node))
    return names


def _reads(node) -> list[ast.Name]:
    """이 스코프에서 직접 읽는 이름(중첩 함수·람다 본문 제외)."""
    found: list[ast.Name] = []
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, SCOPE) or isinstance(child, ast.Lambda):
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            found.append(child)
        stack.extend(ast.iter_child_nodes(child))
    return found


def undefined_in(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_names = _bound_here(tree.body) | BUILTINS
    problems: list[str] = []

    def visit(node, enclosing: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FUNC):
                known = enclosing | _args(child) | _bound_here(child.body)
                for name in _reads(child):
                    if name.id not in known:
                        problems.append(f"{path.name}:{name.lineno} "
                                        f"{child.name}() 안의 '{name.id}'")
                visit(child, known)
            elif isinstance(child, ast.ClassDef):
                visit(child, enclosing | _bound_here(child.body))
            else:
                visit(child, enclosing)

    visit(tree, module_names)
    return problems


def test_정의되지_않은_이름을_읽는_곳이_없다():
    problems: list[str] = []
    for name in TARGETS:
        path = ROOT / name
        if path.exists():
            problems += undefined_in(path)
    assert not problems, "정의되지 않은 이름:\n  " + "\n  ".join(problems)


def test_이_검사가_실제로_잡는다(tmp_path):
    """검사가 통과하는 게 '문제 없음'인지 '검사가 안 도는지' 구분한다."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def a():\n    only_here = 1\n    return only_here\n"
        "def b():\n    return only_here\n", encoding="utf-8")
    found = undefined_in(bad)
    assert any("only_here" in problem and "b()" in problem for problem in found)
