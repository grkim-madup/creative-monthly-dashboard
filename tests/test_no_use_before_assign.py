# -*- coding: utf-8 -*-
"""함수 안에서 **할당 전에 읽는 지역 변수**를 정적으로 잡는다.

왜 필요한가: 진입점(`creative_dashboard.py`)은 **어떤 테스트도 import하지 않는다**
— import하면 화면을 그리기 시작해서 부를 수 없다. 그래서 런타임에만 드러나는
버그가 배포까지 간다. 이미 두 번 겪었다:
  · `0096e4f` — 들여쓰기가 깨져 라이브가 며칠 죽어 있었다(`compile()` 테스트로 막았다)
  · 2026-09-07 — `pivot_editor`가 `filters`를 만들기 **전에** 참조해서
    편집 화면이 통째로 `This app has encountered an error`가 됐다.
    `compile()`은 문법만 보므로 이건 통과했다.

이 검사는 그 두 번째 유형을 잡는다. 보수적으로 판단한다 — 애매하면 통과시킨다
(오탐이 나면 배포가 막혀서 더 나쁘다).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def python_files() -> list[pathlib.Path]:
    return sorted(
        p for p in ROOT.glob("*.py")
        if p.name not in {"conftest.py"}
    )


class _FunctionScan(ast.NodeVisitor):
    """한 함수 안에서 (이름, 처음 할당된 줄, 처음 읽힌 줄)을 모은다."""

    def __init__(self) -> None:
        self.first_store: dict[str, int] = {}
        self.first_load: dict[str, int] = {}
        #: 안쪽 함수·컴프리헨션은 실행 시점이 달라 줄 순서로 판단할 수 없다.
        self.skip = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.first_store.setdefault(node.id, node.lineno)
        elif isinstance(node.ctx, ast.Load):
            self.first_load.setdefault(node.id, node.lineno)

    # 안쪽 스코프는 따로 검사된다(바깥 흐름과 실행 순서가 다르다).
    def visit_FunctionDef(self, node):  # noqa: N802
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_comprehension_like(self, node):
        """컴프리헨션은 **첫 iterable만** 바깥 스코프에서 평가된다.

        실제 버그가 정확히 거기 있었다 —
        `[f for f in filters if f in CREATIVE_FIELDS]`의 `filters`가 그 자리에서
        읽힌다. 안쪽(`elt`·`ifs`·둘째 이후 `for`)은 실행 시점이 달라 보지 않는다.
        """
        if node.generators:
            self.visit(node.generators[0].iter)

    visit_ListComp = visit_comprehension_like
    visit_SetComp = visit_comprehension_like
    visit_DictComp = visit_comprehension_like
    visit_GeneratorExp = visit_comprehension_like


def suspicious(tree: ast.AST) -> list[tuple[str, str, int, int]]:
    """(함수명, 변수명, 읽은 줄, 할당된 줄) 목록."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in
                  [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
        if node.args.vararg:
            params.add(node.args.vararg.arg)
        if node.args.kwarg:
            params.add(node.args.kwarg.arg)

        scan = _FunctionScan()
        for child in node.body:
            scan.visit(child)

        # `global`/`nonlocal`로 선언한 이름은 바깥 것이므로 제외한다.
        declared = {name for sub in ast.walk(node)
                    if isinstance(sub, (ast.Global, ast.Nonlocal))
                    for name in sub.names}

        for name, store_line in scan.first_store.items():
            if name in params or name in declared:
                continue
            load_line = scan.first_load.get(name)
            # 루프·조건 안에서 되쓰는 것(`x = x + 1`, `for x in ...`)은 정상이므로,
            # **읽은 줄이 할당된 줄보다 앞일 때만** 잡는다.
            if load_line is not None and load_line < store_line:
                found.append((node.name, name, load_line, store_line))
    return found


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_no_local_read_before_assignment(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems = suspicious(tree)
    assert not problems, "\n".join(
        f"{path.name}:{load} — {func}() 안에서 `{name}`을 "
        f"{store}행에서 만들기 전에 읽는다"
        for func, name, load, store in problems
    )


def test_the_check_actually_catches_the_real_bug():
    """2026-09-07에 실제로 난 모양을 그대로 넣어 이 검사가 잡는지 확인한다.

    검사가 무엇도 잡지 못하면 통과만 하고 아무 일도 안 하는 테스트가 된다.
    """
    broken = ast.parse(
        "def pivot_editor(view, key):\n"
        "    with box:\n"
        "        picked = [f for f in filters if f]\n"
        "    filters = {'a': 1}\n"
        "    return filters, picked\n"
    )
    problems = suspicious(broken)
    assert any(name == "filters" for _f, name, _l, _s in problems)


def test_the_check_does_not_flag_normal_reassignment():
    fine = ast.parse(
        "def ok(rows):\n"
        "    total = 0\n"
        "    for row in rows:\n"
        "        total = total + row\n"
        "    return total\n"
    )
    assert not suspicious(fine)
