# -*- coding: utf-8 -*-
"""수기 지정 편집기 — 메타·틱톡과 구글 **양쪽**에 있어야 한다.

규리님(2026-09-08): *"메타/틱톡 & 구글 모두 수기로 칠하고 싶은 색을 고를 수 있도록"*
그리고 *"너가 자동으로 선택하되, 내가 맘에 안 들 땐 수기로 수정도 가능한 거야"* —
자동이 기본이고 수기는 덮어쓰기다.

진입점은 테스트가 import할 수 없으므로(import하면 화면을 그린다) 소스와 AST로 본다.
"""
import ast
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def entrypoints():
    for name in ("creative_dashboard.py", "app.py"):
        path = ROOT / name
        if path.exists():
            yield name, path.read_text(encoding="utf-8")


def test_두_섹션_모두_편집기를_붙인다():
    checked = 0
    for name, source in entrypoints():
        # 메타·틱톡: 소재명 기준
        assert "manual_pick_editor(top, month, os_name, rank_metric)" in source, name
        # 구글: 애셋 URL 기준 + 읽을 수 있는 라벨
        assert 'id_column="asset", label_fn=google_pick_label' in source, name
        assert "manual_picks.google_os(g_os)" in source, name
        checked += 1
    assert checked


@pytest.mark.parametrize("call", ["manual_pick_editor(top, month, os_name, rank_metric)",
                                  "manual_pick_editor("])
def test_편집기는_편집_모드에서만_보인다(call):
    """광고주에게 그대로 공유하는 화면이다 — 보기 모드에 편집 도구가 있으면 안 된다."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if "edit_mode" not in ast.unparse(node.test):
                continue
            if "manual_pick_editor" in ast.unparse(node.body):
                found = True
        assert found, f"{name}: `if edit_mode:` 안에 있어야 한다"


def test_구글_라벨은_URL이_아니라_읽을_수_있는_문구다():
    """식별자가 `youtube.com/watch?v=...`이라 그대로 보여주면 못 고른다."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_labelmod", ROOT / "creative_data.py")   # 라벨 함수는 진입점에 있어 직접 재현
    assert spec is not None
    # 진입점을 import할 수 없으므로 함수 본문을 AST로 꺼내 실행한다.
    source = next(src for _n, src in entrypoints())
    tree = ast.parse(source)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "google_pick_label")
    scope: dict = {"pd": pd}
    exec(compile(ast.Module([fn], []), "<label>", "exec"), scope)
    label = scope["google_pick_label"]

    row = pd.Series({"title_kr": "쪽팔려게임", "asset_type": "YouTube 동영상",
                     "cost": 2_930_165.0,
                     "asset": "https://www.youtube.com/watch?v=G0_9MDiaCe8"})
    got = label(row)
    assert "쪽팔려게임" in got
    assert "동영상" in got            # `YouTube ` 접두어는 떼서 짧게
    assert "2,930,165" in got        # 같은 작품이 네 줄인 표가 있어 소진액이 필요하다
    assert "http" not in got


def test_구글_라벨은_작품명이_없어도_안전하다():
    source = next(src for _n, src in entrypoints())
    tree = ast.parse(source)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "google_pick_label")
    scope: dict = {"pd": pd}
    exec(compile(ast.Module([fn], []), "<label>", "exec"), scope)
    label = scope["google_pick_label"]
    got = label(pd.Series({"title_kr": None, "asset_type": "이미지", "cost": None}))
    assert "(작품 없음)" in got and "이미지" in got


def test_저장_키는_라벨이_아니라_식별자다():
    """라벨로 저장하면 소진액이 바뀌는 다음 달에 지정이 통째로 끊긴다."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        # 멀티셀렉트의 값은 `options`(식별자)이고 라벨은 `format_func`로만 쓴다.
        assert "format_func=show" in body, name
        # `ast.unparse`는 따옴표를 정규화한다 — 홑따옴표로 확인한다.
        assert "st.multiselect('우수', options" in body, name
        assert "st.multiselect('저조', [a for a in options" in body, name


def test_수기_지정_패널은_접히지_않는다():
    """시안 A(2026-09-09 승인) — 편집 모드에서만 뜨는 패널이므로 클릭 없이 보여야 한다.

    `st.expander`로 되돌리면 "지금 자동으로 뭐가 뽑혔는지"가 한 번 숨는다.
    """
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "st.expander" not in body, name
        assert "st.container(key=f'mp_{key}')" in body, name


def test_선정_기준을_헤더에_찍는다():
    """기준은 표마다 다르다(`pick_metrics_for`) — 안 찍으면 표만 보고는 알 수 없다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "pick_metrics_for(table)" in body, name
        assert "mp-basis" in body, name
        # 수기 지정이 살아 있으면 자동 선정이 버려진다는 사실을 배지로 알린다.
        assert "is-manual" in body, name


def test_칩_색은_표_강조색과_같은_키로_묶인다():
    """칩과 표가 다른 색이면 "이 지정이 그 색인가"를 다시 확인해야 한다."""
    css = pathlib.Path("ui.py").read_text(encoding="utf-8")
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "mpbest_{key}" in body and "mpworst_{key}" in body, name
    for key, fill in (("mpbest_", "#eefaf3"), ("mpworst_", "#fdf1f1")):
        assert f'st-key-{key}' in css and fill in css
