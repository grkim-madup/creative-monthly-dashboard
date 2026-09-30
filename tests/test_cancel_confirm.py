# -*- coding: utf-8 -*-
"""취소 확인 — 버튼이 한 화면에 **둘까지만** 보인다 (규리님 2026-10-01).

*"편집하다가 취소를 누르면 취소 확인 버튼이 하단에 추가되면서 너무 많은 버튼이
노출되는데, 이 부분 수정해."*

예전에는 `취소`·`완료`를 **비활성으로 남긴 채** `저장 안 하고 끝내기`·`계속 편집`을
아래에 더 그려서 넷이 됐다. 지금은 확인을 물을 때 그 자리를 **교체**한다.

진입점은 import하면 화면을 그리므로 부를 수 없다 — **소스를 AST로 읽어** 계약을 고정한다.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 배포 복사본에서는 진입점 이름이 `app.py`다 — 한쪽만 적으면 그 저장소에서 조용히 깨진다.
ENTRYPOINTS = ("creative_dashboard.py", "app.py")
ENTRY = next(ROOT / name for name in ENTRYPOINTS if (ROOT / name).exists())
TREE = ast.parse(ENTRY.read_text(encoding="utf-8"))


def function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} 이 사라졌다")


def labels(node: ast.AST) -> set[str]:
    """그 가지에서 `.button("라벨", …)` 로 그리는 라벨 전부."""
    out = set()
    for child in ast.walk(node):
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "button"
                and child.args
                and isinstance(child.args[0], ast.Constant)):
            out.add(child.args[0].value)
    return out


def ask_branch() -> ast.If:
    """`askcancel_` 를 보고 갈리는 분기."""
    for node in ast.walk(function("render_query_block")):
        if isinstance(node, ast.If) and "askcancel_" in ast.unparse(node.test):
            return node
    raise AssertionError("askcancel 분기를 찾지 못했다 — 확인창이 조건 없이 그려진다")


class TestBranch:
    def test_물어보는_동안_취소와_완료를_그리지_않는다(self):
        """**이 테스트가 규리님 지적의 본체다.**

        `disabled=` 로 남겨 두는 것으로는 부족하다 — 비활성 버튼도 자리를 차지하고
        시선을 가져간다.
        """
        branch = ask_branch()
        asked = set()
        for stmt in branch.body:
            asked |= labels(stmt)
        assert "취소" not in asked
        assert "완료" not in asked

    def test_평소에는_취소와_완료만_그린다(self):
        branch = ask_branch()
        assert branch.orelse, "확인을 안 물을 때의 가지가 없다"
        normal = set()
        for stmt in branch.orelse:
            normal |= labels(stmt)
        assert {"취소", "완료"} <= normal
        assert "저장 안 하고 끝내기" not in normal

    def test_확인창은_그_분기_안에서만_불린다(self):
        """밖에서 한 번 더 부르면 다시 넷이 된다."""
        branch = ask_branch()
        inside = ast.unparse(ast.Module(body=list(branch.body), type_ignores=[]))
        assert "cancel_confirm(" in inside
        assert ast.unparse(function("render_query_block")).count(
            "cancel_confirm(") == 1


class TestConfirmRow:
    def test_확인_버튼은_정확히_둘이다(self):
        assert labels(function("cancel_confirm")) == {
            "저장 안 하고 끝내기", "계속 편집"}

    def test_헤더와_폭이_맞는다(self):
        """폭 합과 마지막 칸이 다르면 확인창이 뜰 때 버튼이 좌우로 튄다."""
        def widths(fn: str, wanted_last: float | None = None):
            out = []
            for node in ast.walk(function(fn)):
                if (isinstance(node, ast.Call)
                        and ast.unparse(node.func).endswith("columns")
                        and node.args
                        and isinstance(node.args[0], ast.List)):
                    vals = [e.value for e in node.args[0].elts
                            if isinstance(e, ast.Constant)]
                    if len(vals) == 3:
                        out.append(vals)
            return out

        header = [w for w in widths("render_query_block") if w[0] == 5][0]
        confirm = widths("cancel_confirm")[0]
        assert round(sum(header), 6) == round(sum(confirm), 6)
        assert header[-1] == confirm[-1]
