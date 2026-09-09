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

    # **모듈 최상위도 검사한다.** 예전에는 함수 안만 봤다 — 2026-09-09에 진입점
    # 최상위에서 import하지 않은 `store`를 불러 화면이 통째로 죽었는데도 이 검사가
    # 통과했다. 진입점은 코드의 절반이 최상위에 있어서 사각지대가 컸다.
    # 람다 인자·컴프리헨션 변수는 자기만의 스코프라 최상위 이름이 아니다. 이 검사의
    # 목적은 **빠진 import·오타**를 잡는 것이고, 그런 이름이 람다 인자로 쓰일 일은
    # 없으므로 알려진 것으로 취급한다(과하게 허용해도 목적을 잃지 않는다).
    local_scoped = module_names | _lambda_and_comprehension_names(tree)
    for name in _module_level_reads(tree):
        if name.id not in local_scoped:
            problems.append(f"{path.name}:{name.lineno} 최상위의 '{name.id}'")
    return problems


def _lambda_and_comprehension_names(tree: ast.Module) -> set[str]:
    """람다 인자와 컴프리헨션 for 변수 이름."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Lambda):
            names |= _args(node)
        elif isinstance(node, (ast.ListComp, ast.SetComp,
                               ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                for sub in ast.walk(gen.target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
    return names


def _module_level_reads(tree: ast.Module) -> list[ast.Name]:
    """함수·클래스 **밖**에서 읽는 이름. 그 안쪽은 `visit`이 따로 본다."""
    found: list[ast.Name] = []

    def walk(node) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (*FUNC, ast.ClassDef)):
                continue        # 함수/클래스 안은 여기서 보지 않는다
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                found.append(child)
            walk(child)

    walk(tree)
    return found


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


def test_최상위_검사가_실제로_잡는다(tmp_path):
    """이 검사가 잡는지 스스로 확인한다.

    2026-09-09에 진입점 최상위에서 import하지 않은 `store`를 불러 화면이 통째로
    죽었는데도 이 파일이 통과했다 — 함수 안만 봤기 때문이다. 검사를 넓힌 뒤,
    **넓힌 것이 실제로 작동하는지**까지 고정한다(안 그러면 또 조용히 통과한다).
    """
    bad = tmp_path / "bad.py"
    bad.write_text("import json\nvalue = store.now()\n", encoding="utf-8")
    problems = undefined_in(bad)
    assert any("store" in p for p in problems), problems

    good = tmp_path / "good.py"
    good.write_text("import store\nvalue = store.now()\n", encoding="utf-8")
    assert undefined_in(good) == []


def test_람다와_컴프리헨션은_오탐이_아니다():
    """실제로 오탐이 났던 형태 — `sorted(xs, key=lambda x: -x['n'])`."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "ok.py"
        path.write_text(
            "rows = [1, 2]\n"
            "top = sorted(rows, key=lambda x: -x)[:2]\n"
            "labels = [str(o) for o in rows]\n",
            encoding="utf-8")
        assert undefined_in(path) == []
