# -*- coding: utf-8 -*-
"""편집자 도구는 **보기 모드에서 숨는다.**

규리님(2026-09-08): *"이 데이터 적합성 점검은 보기 모드에서는 보이면 안 돼."*

⚠ `auth.can_edit()`(= `editor_allowed`)는 **권한**이고 보기 모드 여부가 아니다.
규리님은 편집 권한이 있으므로 그것만 보면 보기 모드에서도 패널이 그려지고,
그 화면을 광고주에게 그대로 공유한다.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 보기 모드에서 숨어야 하는 편집자 전용 블록. 값은 그 블록을 찾을 표식이다.
EDITOR_ONLY = {
    "데이터 적합성 점검": "recon_panel",
}


def entrypoints():
    for name in ("creative_dashboard.py", "app.py"):
        path = ROOT / name
        if path.exists():
            yield name, path.read_text(encoding="utf-8")


@pytest.mark.parametrize("label,marker", sorted(EDITOR_ONLY.items()))
def test_보기_모드에서_숨는다(label, marker):
    checked = 0
    for name, source in entrypoints():
        assert marker in source, f"{name}: {label} 블록을 찾지 못했습니다"
        # 그 블록을 감싼 조건을 AST로 실제 확인한다 — 주석에 적어 두는 것만으로는
        # 통과하지 않는다.
        tree = ast.parse(source)
        guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = ast.unparse(node.test)
            if "editor_allowed" not in test:
                continue
            body = ast.unparse(node.body)
            if marker not in body:
                continue
            guarded = "edit_mode" in test
            if guarded:
                break
        assert guarded, (
            f"{name}: {label} 이 `editor_allowed`만으로 감싸져 있습니다 — "
            "`edit_mode`도 함께 봐야 보기 모드에서 숨습니다")
        checked += 1
    assert checked


def test_이_검사가_실제로_잡는다():
    """감싼 조건을 정말 보는지 — 통과가 '검사 안 함'을 뜻하지 않게."""
    bad = ast.parse("if editor_allowed:\n    x('recon_panel')\n")
    found = False
    for node in ast.walk(bad):
        if isinstance(node, ast.If) and "editor_allowed" in ast.unparse(node.test):
            found = "edit_mode" in ast.unparse(node.test)
    assert found is False
