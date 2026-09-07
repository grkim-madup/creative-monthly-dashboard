# -*- coding: utf-8 -*-
"""`os == "All"` 은 분석에서 뺀다.

규리님 확인(2026-09-08): *"OS가 ALL 인 데이터는 포함되지 않는 게 맞아.
우린 UA 데이터만 분석하면 돼."*

⚠ 예전 필터는 `raw["os"].dropna().unique()` 였다 — **`"All"` 은 비어있지 않은
값이라 그대로 통과**해 화면 숫자에 들어가 있었고(8월 271행·소진 545만원),
2번 섹션에는 AOS/iOS 말고 색칠 없는 빈 표가 하나 더 그려졌다.
"""
import pandas as pd

from creative_data import NON_OS_VALUES, os_values


def frame(*values) -> pd.DataFrame:
    return pd.DataFrame({"os": list(values), "cost": [1.0] * len(values)})


def test_All을_뺀다():
    assert os_values(frame("AOS", "iOS", "All")) == ["AOS", "iOS"]


def test_대소문자_표기를_모두_뺀다():
    assert os_values(frame("AOS", "all", "ALL", "All")) == ["AOS"]


def test_하이픈과_빈_문자열도_뺀다():
    assert os_values(frame("iOS", "-", "")) == ["iOS"]


def test_결측은_원래대로_뺀다():
    assert os_values(pd.DataFrame({"os": ["AOS", None]})) == ["AOS"]


def test_공백이_붙어_있어도_잡는다():
    assert os_values(frame("AOS", " All ")) == ["AOS"]


def test_정렬된_목록을_돌려준다():
    assert os_values(frame("iOS", "AOS", "iOS")) == ["AOS", "iOS"]


def test_빈_프레임에도_안전하다():
    assert os_values(pd.DataFrame()) == []
    assert os_values(None) == []
    assert os_values(pd.DataFrame({"cost": [1.0]})) == []


def test_화면이_이_함수를_쓴다():
    """진입점은 테스트가 import할 수 없어 소스를 훑는다.

    `dropna().unique()` 로 되돌아가면 `All` 이 조용히 다시 들어온다.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    checked = 0
    for name in ("creative_dashboard.py", "app.py"):
        path = root / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "os_selection = os_values(raw)" in source, name
        assert 'sorted(raw["os"].dropna().unique())' not in source, name
        assert 'sorted(meta_tiktok["os"].dropna().unique())' not in source, name
        checked += 1
    assert checked


def test_비_OS_값_목록():
    assert "All" in NON_OS_VALUES and "AOS" not in NON_OS_VALUES
