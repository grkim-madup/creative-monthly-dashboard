# -*- coding: utf-8 -*-
"""`?ranks=all` — 정렬 기준마다 표를 이어 그린다(PDF용, 규리님 선택 2026-09-09).

PDF는 정적이라 셀렉트박스를 누를 수 없다. 그래서 화면이 한 번에 다 그려 줘야
`tools/export_pdf.py`가 기준별 표를 한 문서에 담을 수 있다.

진입점은 import하면 화면을 그리기 시작해서 테스트가 부를 수 없다(`0096e4f`).
그래서 소스를 AST로 읽어 계약만 고정한다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

#: 배포판은 진입점 이름이 `app.py`다. 파일명을 하드코딩하면 배포 복사본에서 깨진다.
ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def entrypoints():
    found = [(n, pathlib.Path(n).read_text(encoding="utf-8"))
             for n in ENTRYPOINTS if pathlib.Path(n).exists()]
    if not found:
        pytest.skip("진입점을 찾지 못했습니다")
    return found


def test_쿼리_파라미터로_전체_기준을_켠다():
    for name, source in entrypoints():
        assert 'st.query_params.get("ranks")' in source, name
        assert "all_ranks" in source, name


def test_두_섹션_모두_정본_목록에서_기준을_가져온다():
    """셀렉트박스 값 하나만 쓰면 PDF에 기준이 하나만 담긴다."""
    for name, source in entrypoints():
        assert "list(RANK_METRICS) if all_ranks" in source, name
        assert "list(GOOGLE_RANK_METRICS) if all_ranks" in source, name


def test_기준을_돌면서_그린다():
    """`for` 문이 실제로 있어야 한다 — 목록만 만들고 안 돌면 아무 일도 안 일어난다."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        loops = {ast.unparse(n.target) + " in " + ast.unparse(n.iter)
                 for n in ast.walk(tree) if isinstance(n, ast.For)}
        assert "rank_metric in rank_metrics" in loops, name
        assert "g_rank_metric in g_rank_metrics" in loops, name


def test_기본값은_고른_기준_하나다():
    """평소 화면까지 네 벌로 늘어나면 안 된다 — `?ranks=all`일 때만 전부 그린다."""
    for name, source in entrypoints():
        assert "else [picked_rank]" in source, name
        assert "else [g_picked_rank]" in source, name


def test_표_제목에_기준_이름이_들어간다():
    """기준별 표가 이어지면 어느 기준인지 제목으로 구분돼야 한다."""
    for name, source in entrypoints():
        assert "RANK_METRICS[rank_metric]} 기준 TOP" in source, name
        assert "GOOGLE_RANK_METRICS[g_rank_metric]} 기준 TOP" in source, name


def test_PDF_도구가_이_파라미터를_쓴다():
    """도구와 화면이 갈라지면 PDF에 기준이 하나만 담긴다."""
    tool = pathlib.Path("tools/export_pdf.py")
    if not tool.exists():   # 배포 복사본에는 tools/가 없다
        pytest.skip("tools/export_pdf.py 없음 (배포 복사본)")
    assert "ranks=all" in tool.read_text(encoding="utf-8")
