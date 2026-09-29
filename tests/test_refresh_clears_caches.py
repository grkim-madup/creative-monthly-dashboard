# -*- coding: utf-8 -*-
"""`다시 불러오기`가 **그 시트에서 파생된 캐시를 전부** 비우는지.

2026-09-29 실제 사고: 규리님이 시트를 갱신했는데 9/19에 시작한 작품
(`11224 용사의 발라드`, 소진 ₩8,239,106)이 필터 드롭다운에 아예 안 떴다.

원인은 캐시 한 겹이었다. 갱신 핸들러가 `_load`만 비웠는데, 화면이 실제로 쓰는
프레임은 `_media_frozen`이 들고 있다. 그 캐시 키는 `(시트id, 고정시각, 장르시트)`
뿐이라 **시트를 새로 받아도 바뀌지 않는다** → `_media_frozen`이 다시 돌지 않고,
비워 둔 `_load`는 불리지조차 않는다.

**증상이 조용하다**: 갱신 시각은 parquet 파일 mtime이라 `0분 전`으로 멀쩡히 바뀐다.
행 수만 옛날 것이다(실측: 시트 9월 5,693행 vs 화면 2,886행).

같은 뿌리의 전례가 둘 더 있다 — 컷오버 때 `prefetch.py` 분기 누락,
`b92de54`(긴 TTL로 "고쳤는데 화면이 그대로"). 그래서 개별 이름을 못 박지 않고
**의존 관계를 계산해서** 검사한다.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 진입점 이름은 배포처마다 다르다 — 로컬·Streamlit Cloud는 `creative_dashboard.py`,
#: madup.app 포털은 `app.py`로 이름을 바꿔 복사한다.
ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def entrypoint() -> pathlib.Path:
    for name in ENTRYPOINTS:
        path = ROOT / name
        if path.exists():
            return path
    pytest.skip("진입점을 찾지 못했다")


def _cached_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    out = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            text = ast.unparse(deco.func if isinstance(deco, ast.Call) else deco)
            if text.endswith("cache_data"):
                out[node.name] = node
    return out


def _direct_calls(node: ast.AST) -> set[str]:
    return {n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def _refresh_block(source: str) -> str:
    """시트 `다시 불러오기`를 처리하는 구간."""
    start = source.index("if _sheet_hit:")
    return source[start:source.index("st.rerun()", start)]


def test_시트를_다시_읽으면_파생_캐시도_비운다():
    source = entrypoint().read_text(encoding="utf-8")
    tree = ast.parse(source)
    cached = _cached_functions(tree)
    calls = {name: _direct_calls(node)
             for name, node in ((n.name, n) for n in tree.body
                                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))}

    def reaches(name: str, target: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if name in seen:
            return False
        seen.add(name)
        return any(c == target or reaches(c, target, seen)
                   for c in calls.get(name, ()))

    # 시트를 읽는 함수(`_load`)에 직접·간접으로 의존하는 캐시 전부
    dependents = {name for name in cached if reaches(name, "_load")} | {"_load"}
    block = _refresh_block(source)
    cleared = {node.func.value.id
               for node in ast.walk(ast.parse(ast.unparse(ast.parse(block))))
               if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "clear"
               and isinstance(node.func.value, ast.Name)}

    missing = sorted(dependents - cleared)
    assert not missing, (
        "시트를 다시 읽는데 이 캐시들이 안 비워진다 — 파일만 새것이 되고 화면은 "
        f"옛 프레임을 계속 본다: {missing}"
    )


def test_검사가_실제로_잡는지_자기검증():
    """`_media_frozen.clear()`를 지우면 이 테스트가 실패해야 한다."""
    source = entrypoint().read_text(encoding="utf-8")
    broken = source.replace("            _media_frozen.clear()\n", "", 1)
    assert broken != source, "`_media_frozen.clear()` 를 못 찾았다 — 검사가 낡았다"
    block = _refresh_block(broken)
    assert "_media_frozen.clear()" not in block
