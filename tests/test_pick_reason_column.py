# -*- coding: utf-8 -*-
"""`선정` 컬럼을 표에서 걷어냈다 (규리님 2026-10-01).

*"내가 말한건 선정 컬럼을 빼라는 거였어, 각 테이블마다."*

2026-09-30에 *"우수인데 CPI가 안 좋다"* 를 설명하려고 넣었던 컬럼이다. 규리님이
화면을 보고 뺐다 — **되살리려면 먼저 물어볼 것.**

⚠ 대신 **표 아래 각주는 남아 있어야 한다.** 컬럼도 각주도 없으면 녹색·붉은색이
무슨 뜻인지 화면 어디에도 안 적힌다.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINTS = ("creative_dashboard.py", "app.py")
ENTRY = next(ROOT / name for name in ENTRYPOINTS if (ROOT / name).exists())
SOURCE = ENTRY.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

#: 색을 칠하는 표를 그리는 함수 전부.
RENDERERS = ("render_google_table", "render_table_best_worst",
             "render_ranked_table")


def body(name: str) -> str:
    node = next((n for n in ast.walk(TREE)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert node is not None, f"{name} 이 사라졌다 — 이 검사가 무력해진다"
    return ast.unparse(node)


class TestColumnGone:
    def test_어느_표에도_선정_컬럼이_없다(self):
        for name in RENDERERS:
            assert "pick_reason(" not in body(name), name

    def test_상수도_남아_있지_않다(self):
        """죽은 상수를 남기면 다음 사람이 '아직 쓰나' 하고 되살린다."""
        assert "PICK_REASON_COLUMN" not in SOURCE


class TestStillDisclosed:
    def test_색의_뜻은_각주가_말한다(self):
        """컬럼을 뺀 대가다 — 각주까지 없애면 아무 설명이 없다."""
        assert SOURCE.count("녹색 = 우수") >= 2

    def test_편집기_자동_컬럼은_그대로다(self):
        """`pick_reason`은 편집기에서 계속 쓴다 — 함께 지우지 말 것."""
        assert "def pick_reason(" in SOURCE
        assert 'columns["자동"]' in SOURCE
        assert "pick_reason(" in body("manual_pick_editor")
