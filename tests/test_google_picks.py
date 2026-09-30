# -*- coding: utf-8 -*-
"""구글 표의 우수·저조 선정.

2026-10-01부터 메타·틱톡과 **같은 함수**(`pick_by_media`)를 쓴다. 정렬 기준이 점수
지표를 정한다 — 인스톨·소진액 = CPI > (Read CVR — 구글엔 없다) > CTR,
인앱 액션 = 인앱 CPA > CPI > CTR.
"""
import ast
import pathlib

import pandas as pd

from creative_data import pick_basis, pick_by_media


def table(rows: int, cpa_rows: int = 0) -> pd.DataFrame:
    """구글 표 흉내. `cpa_rows`개(액션 목적 ACa)에만 인앱 CPA가 있다."""
    return pd.DataFrame([
        {"asset": f"a{i}", "cost": 1_000_000 - i * 10_000,
         "CPI": 1000 + i * 100, "CTR": 0.01 + i * 0.005,
         "인앱 CPA": (5000 + i * 700) if i < cpa_rows else None}
        for i in range(rows)
    ])


def test_인스톨_기준은_CPI로_컷한다():
    """구글에는 Read CVR이 없어 2순위가 비고, CTR이 그 자리로 올라가지 않는다."""
    assert pick_basis(table(10), "total install") == ["CPI"]
    assert pick_basis(table(10), "cost") == ["CPI"]


def test_인앱_액션_기준은_인앱_CPA가_1순위다():
    assert pick_basis(table(10, cpa_rows=10), "in_app_action") == ["인앱 CPA", "CPI"]


def test_인스톨_기준은_4줄을_칠한다():
    top = table(10)
    best, worst = pick_by_media(top, rank_metric="total install")
    assert len(best) == 2 and len(worst) == 2
    assert not (set(best) & set(worst))
    assert set(best.values()) | set(worst.values()) == {"CPI"}


def test_인앱_CPA가_없는_캠페인은_인앱_액션_표에서_후보가_아니다():
    """설치 목적(ACi) 캠페인은 인앱 액션을 잡지 않는다(구조적으로 0건).

    최악으로 치면 목적이 다른 캠페인이 저조로 찍혔다(9월 구글 iOS 시뮬레이션).
    """
    top = table(10, cpa_rows=6)
    best, worst = pick_by_media(top, rank_metric="in_app_action")
    picked = set(best) | set(worst)
    assert picked
    assert all(pd.notna(top.loc[i, "인앱 CPA"]) for i in picked)


def test_빈_표는_조용히_빈_결과():
    assert pick_by_media(pd.DataFrame(), rank_metric="total install") == ({}, {})
    assert pick_basis(pd.DataFrame(), "total install") == []


def _entrypoints():
    # ⚠ madup.app 배포판은 진입점 이름이 `app.py`다(포털이 그걸 요구한다).
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("creative_dashboard.py", "app.py"):
        path = root / name
        if path.exists():
            yield name, path.read_text(encoding="utf-8")


def test_소재_카드는_선정을_다시_계산하지_않는다():
    """카드는 **표가 정한 결과를 받는다.** 두 곳에서 계산하면 반드시 갈린다.

    같은 실수를 두 번 했다: 카드만 기준이 달라 표와 칠한 개수가 달랐고, 수기 지정을
    표에만 붙였더니 카드가 자동 선정을 그렸다(2026-09-08 규리님 지적).
    """
    checked = 0
    for name, source in _entrypoints():
        tree = ast.parse(source)
        table_fn = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "render_google_table")
        cards_fn = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name == "render_google_material_cards")
        assert "pick_by_media(view, rank_metric=rank_metric)" in ast.unparse(table_fn), name
        assert "pick_by_media" not in ast.unparse(cards_fn), (
            f"{name}: 카드가 선정을 다시 계산합니다 — 표에서 받아야 합니다")
        assert "render_google_material_cards(g_top, g_best, g_worst)" in source, name
        checked += 1
    assert checked


def test_top_n_is_displayed_by_spend():
    """**고르는 기준과 보여주는 순서는 다르다**(2026-09-07 규리님 요청).

    인스톨·인앱 액션으로 TOP N을 고르되, 표는 소진액 내림차순으로 읽는다.
    진입점 코드가 그 순서로 되어 있는지 소스로 확인한다(진입점은 import할 수 없다).
    """
    _name, source = next(_entrypoints())
    assert 'g_top = g_top.sort_values(g_rank_metric, ascending=False).head' in source
    assert 'g_top = g_top.sort_values("cost", ascending=False).reset_index' in source
