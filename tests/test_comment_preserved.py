# -*- coding: utf-8 -*-
"""저장이 **코멘트를 조용히 비우지 않는다** (2026-10-02 유실 사고).

`<용사의 발라드>` 블록 코멘트가 사라졌고 **복구 사본이 없었다** — 백업은 9/9가
마지막인데 그 블록은 그 뒤에 만들어졌고, Firestore는 문서를 덮어써서 이력이 없다.

원인은 `save_block`의 이 한 줄이었다:

    comment=st.session_state.get(comment_key(block_id)) or ""

**세션에 키가 없으면 빈 문자열로 덮어쓴다.** 키가 없다는 것은 *에디터가 이번 리런에
안 그려졌다*는 뜻이지 *사용자가 비웠다*가 아니다. 표 설정(`view_from_widgets`)은
*"세션 키가 없으면 저장된 값을 그대로 유지한다"* 가 명시된 계약인데 코멘트만
그걸 안 지키고 있었다.

⚠ **의도적인 비우기는 계속 저장돼야 한다.** 지울 때는 에디터가 떠 있어 키가 `""`로
**존재**하므로 둘은 구분된다.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINTS = [n for n in ("creative_dashboard.py", "app.py") if (ROOT / n).exists()]


def save_block(name: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "save_block")


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_세션에_키가_없으면_빈_값으로_덮지_않는다(name):
    """**이 검사가 사고의 본체다.**

    `session_state.get(키) or ""` 형태가 코멘트에 다시 들어오면 실패한다.
    """
    body = ast.unparse(save_block(name))
    assert "comment_key" in body, f"{name}: 코멘트 키를 안 쓴다"
    # `... .get(comment_key(...)) or ''` — 키가 없을 때 빈 값이 되는 형태
    for node in ast.walk(save_block(name)):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        left = ast.unparse(node.values[0])
        if "comment_key" in left and ".get(" in left:
            pytest.fail(f"{name}: 세션에 키가 없으면 코멘트가 빈 값으로 덮인다 — "
                        f"{ast.unparse(node)}")


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_키_존재를_먼저_확인한다(name):
    """`in st.session_state` 로 **있을 때만** 세션 값을 쓴다."""
    body = ast.unparse(save_block(name))
    assert "in st.session_state" in body, f"{name}: 키 존재 확인이 없다"


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_없으면_저장소_최신값을_지킨다(name):
    """화면 스냅샷이 아니라 **저장소에서 다시 읽은 블록**의 값을 지켜야 한다 —
    `commit_blocks`가 최신 상태 위에서 돌기 때문이다."""
    body = ast.unparse(save_block(name))
    assert "find_block(" in body, f"{name}: 저장소 최신 블록을 안 읽는다"
