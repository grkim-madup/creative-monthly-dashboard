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
        # 메타·틱톡: 소재명 기준 + 축약 라벨(칩에서 앞이 잘려 구분이 안 됐다)
        assert ("manual_pick_editor(top, month, os_name, rank_metric, "
                "label_fn=ad_pick_label)") in source, name
        # 구글: 애셋 URL 기준 + 읽을 수 있는 라벨
        assert 'id_column="asset", label_fn=google_pick_label' in source, name
        assert "manual_picks.google_os(g_os)" in source, name
        checked += 1
    assert checked


@pytest.mark.parametrize("call", ["manual_pick_editor(top, month, os_name, rank_metric,",
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
        # 2026-09-09: 멀티셀렉트 → `st.data_editor`(표와 같은 순서로 체크). 칩이
        # 폭에 걸려 앞에서 잘렸고, 좌우 2열로 나누면서 더 심해졌다.
        #
        # 계약은 그대로다 — **보여주는 것은 라벨, 되받는 것은 식별자.** 라벨로
        # 저장하면 소진액이 바뀌는 다음 달에 지정이 통째로 끊긴다.
        assert "[show(ident) for ident in options]" in body, name
        assert "options[i]" in body, f"{name}: 식별자로 되받지 않는다"
        assert "st.data_editor" in body, name


def test_수기_지정_패널은_평소_접혀_있다():
    """규리님 결정(2026-09-09 오후): *"항상 펼쳐두지는 말고, 평소엔 접어뒀다가 내가
    필요할 때만 펼쳐서"*.

    ⚠ 내가 오전에 이 계약을 **반대로** 못 박아 뒀다("접히지 않는다"). 근거로
    "편집 모드에서만 뜨니 클릭 없이 보여야 한다"를 들었는데, **표가 6개면 패널도
    6개가 다 펼쳐진다**는 것을 계산하지 않았다. 화면 길이를 실제로 보고서야 드러났다.

    대신 지정된 소재는 **접힌 상태에서도 칩으로 보인다**(아래 테스트) — 원래 근거였던
    "무엇이 사람 판단인지 보여야 한다"는 그쪽으로 지킨다.
    """
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "st.expander" in body, name
        assert "expanded=False" in body, f"{name}: 기본이 펼침이면 예전으로 돌아간다"


def test_지정_칩을_접힌_줄_위에_그리지_않는다():
    """규리님이 걷어낸 것(2026-09-09) — *"선택된 소재를 드롭박스 위에 미리 보이게
    하지 말라는 의미였어."*

    내가 3안으로 만들었던 칩 미리보기다. 표 위쪽에 칩 줄이 떠서 표와 패널 사이를
    끊었다. 건수는 접힌 헤더 문구(`수기 N건`)로 알린다.
    """
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "mp-chips" not in body, name
        assert "수기 {len(current)}건" in body or "수기 " in body, name


def test_선정_기준을_헤더에_찍는다():
    """기준은 표마다 다르다(`pick_metrics_for`) — 안 찍으면 표만 보고는 알 수 없다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "pick_metrics_for(table)" in body, name
        assert "mp-basis" in body, name
        # 수기 지정이 살아 있으면 자동 선정이 버려진다는 사실을 알려야 한다.
        # 3안에서 이 문구는 **접힌 헤더**로 옮겼다 — 펼치지 않아도 보여야 한다.
        assert "자동 선정 안 씀" in body, name
        assert "자동 선정 사용 중" in body, name


def test_우수_저조_두_컬럼으로_고른다():
    """표와 같은 순서로 늘어놓고 **체크박스 두 컬럼**으로 고른다(1안, 2026-09-09).

    ⚠ 예전에는 칩 색을 표 강조색과 맞추는 것이 계약이었다(멀티셀렉트 시절).
      `st.data_editor`는 행 배경을 칠할 수 없어 그 계약이 성립하지 않는다 —
      대신 컬럼 이름(`우수`/`저조`)이 표의 색 의미와 1:1로 대응한다.
    """
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "manual_pick_editor")
        body = ast.unparse(fn)
        assert "CheckboxColumn('우수'" in body, name
        assert "CheckboxColumn('저조'" in body, name
        # 한 소재를 양쪽에 체크한 경우를 조용히 넘기지 않는다.
        assert "우수·저조 양쪽에 체크" in body, name
