# -*- coding: utf-8 -*-
"""우수·저조 선정이 **소진 규모**를 반영한다.

팀원 피드백(2026-09-08): *"소진 비용도 보고 유입 성과, CPI랑 Coin CVR까지 넓게
봤을 때 뽑고 싶은데, 클로드는 그런 거 신경 안 쓰고 '오케이 CPI 좋다 얘 best야'
이렇게 정한 느낌."*

팀원이 직접 뽑은 8월 픽 17건 재현율: 지표 argmax 8/17(47%) → 이 규칙 12/17(71%).
측정 도구는 `tools/analyze_pick_rules.py`.
"""
import pandas as pd
import pytest

from creative_data import (
    BACK_PICK_CANDIDATES,
    PICK_CANDIDATE_SHARE,
    pick_best_worst,
    pick_metrics_for,
)


def table(rows):
    return pd.DataFrame(rows)


def test_상위구간에서_소진_큰_쪽을_고른다():
    # CPI 1등은 소액 집행이고, 2등이 소진 100배다. 실무는 후자를 우수로 본다.
    df = table([
        {"ad": "소액", "media": "Meta", "cost": 100_000, "CPI": 1_000},
        {"ad": "대규모", "media": "Meta", "cost": 12_000_000, "CPI": 1_100},
        {"ad": "보통", "media": "Meta", "cost": 3_000_000, "CPI": 5_000},
        {"ad": "나쁨", "media": "Meta", "cost": 2_000_000, "CPI": 9_000},
    ])
    best, _worst = pick_best_worst(df, [("CPI", False)])
    assert [df.loc[i, "ad"] for i in best] == ["대규모"]


def test_저조도_같은_규칙을_따른다():
    # 큰 실패가 작은 실패보다 리포트에서 중요하다.
    df = table([
        {"ad": "좋음", "media": "Meta", "cost": 5_000_000, "CPI": 1_000},
        {"ad": "그저그럼", "media": "Meta", "cost": 5_000_000, "CPI": 4_000},
        {"ad": "큰실패", "media": "Meta", "cost": 8_000_000, "CPI": 8_000},
        {"ad": "작은실패", "media": "Meta", "cost": 120_000, "CPI": 9_000},
    ])
    _best, worst = pick_best_worst(df, [("CPI", False)])
    assert [df.loc[i, "ad"] for i in worst] == ["큰실패"]


def test_후보_구간을_0으로_주면_예전_규칙_그대로():
    df = table([
        {"ad": "소액", "media": "Meta", "cost": 100_000, "CPI": 1_000},
        {"ad": "대규모", "media": "Meta", "cost": 12_000_000, "CPI": 1_100},
        {"ad": "보통", "media": "Meta", "cost": 3_000_000, "CPI": 5_000},
    ])
    best, _worst = pick_best_worst(df, [("CPI", False)], candidate_share=0.0)
    assert [df.loc[i, "ad"] for i in best] == ["소액"]


def test_네_개가_서로_다른_소재로_뽑힌다():
    # 구간이 겹쳐 후보가 먼저 소진되더라도 색칠이 4개 나와야 한다
    # (예전에 3개만 나온 실측 사고가 있었다).
    df = table([
        {"ad": f"a{i}", "media": "Meta", "cost": 1_000_000 * (i + 1),
         "CPI": 1_000 * (i + 1), "D0 coin CVR": 0.5 * (i + 1)}
        for i in range(6)
    ])
    best, worst = pick_best_worst(
        df, [("CPI", False), ("D0 coin CVR", True)])
    picked = list(best) + list(worst)
    assert len(picked) == 4
    assert len(set(picked)) == 4


def test_구간이_전부_선점되면_밖에서_이어_고른다():
    df = table([
        {"ad": "a", "media": "Meta", "cost": 3_000_000, "CPI": 1_000, "CTR": 20.0},
        {"ad": "b", "media": "Meta", "cost": 2_000_000, "CPI": 1_100, "CTR": 19.0},
    ])
    best, worst = pick_best_worst(df, [("CPI", False), ("CTR", True)])
    # 2행뿐이라 4개를 채울 수 없다 — 있는 행을 중복 없이 나눠 갖는다.
    assert set(best) | set(worst) == {0, 1}
    assert not (set(best) & set(worst))


# ---------------------------------------------------------------- 지표 선택

def test_코인_전환이_없는_표는_CTR로_뽑는다():
    """AOS 표는 D0 Coin CVR이 0.00~0.05%다 — 그걸로 뽑으면 아무 뜻이 없다."""
    df = table([
        {"ad": f"a{i}", "cost": 1_000_000, "CPI": 2_000,
         "D0 coin CVR": 0.0, "CTR": 10.0 + i}
        for i in range(6)
    ])
    assert pick_metrics_for(df) == [("CPI", False), ("CTR", True)]


def test_코인_전환이_갈리면_코인으로_뽑는다():
    """⚠ 값이 **있는 것**만으로는 부족하다 — 값이 전부 같으면 갈리지 않는다.
    예전 픽스처는 코인 CVR이 6줄 모두 3.0(스프레드 0)이었는데도 통과했다."""
    df = table([
        {"ad": f"a{i}", "cost": 1_000_000, "CPI": 2_000,
         "D0 coin CVR": 1.0 + i * 1.5, "CTR": 10.0}
        for i in range(6)
    ])
    assert pick_metrics_for(df) == [("CPI", False), ("D0 coin CVR", True)]


def test_스프레드가_큰_쪽을_보조로_고른다():
    """실측: AOS·인스톨은 코인이 0.01%p라 CTR(28%p)을, iOS는 코인(6.8%p)을 썼다."""
    coin_wins = table([
        {"ad": f"a{i}", "cost": 1e6, "CPI": 2000,
         "D0 coin CVR": 1.0 + i * 1.4, "CTR": 10.0 + i * 0.1}
        for i in range(6)])
    assert pick_metrics_for(coin_wins)[1][0] == "D0 coin CVR"
    ctr_wins = table([
        {"ad": f"a{i}", "cost": 1e6, "CPI": 2000,
         "D0 coin CVR": 1.0 + i * 0.01, "CTR": 6.0 + i * 5.0}
        for i in range(6)])
    assert pick_metrics_for(ctr_wins)[1][0] == "CTR"


def test_쓸_보조가_없으면_CPI를_두_번_넣는다():
    """지표 개수와 칠할 줄 수는 별개다 — 보조가 없어도 슬롯은 2:2를 유지한다."""
    df = table([{"ad": f"a{i}", "cost": 1_000_000, "CPI": 2_000 + i * 100}
                for i in range(6)])
    assert pick_metrics_for(df) == [("CPI", False), ("CPI", False)]
    best, worst = pick_best_worst(df, pick_metrics_for(df))
    assert len(best) == 2 and len(worst) == 2


def test_빈_표에도_안전하다():
    assert pick_metrics_for(pd.DataFrame()) == [("CPI", False)]
    assert pick_metrics_for(None) == [("CPI", False)]


def test_뒷단_후보는_돈_지표가_먼저다():
    """코인이 매출이다 — 쓸 수 있으면 코인이 우선(규리님 결정)."""
    assert [c for c, _ in BACK_PICK_CANDIDATES] == ["D0 coin CVR", "CTR"]


def test_후보_구간_기본값():
    # 20%는 53%, 30%·40%는 71%였다 — 71%가 되는 가장 좁은 값을 쓴다.
    assert PICK_CANDIDATE_SHARE == pytest.approx(0.30)


def test_화면이_이_헬퍼를_실제로_쓴다():
    """진입점은 테스트가 import할 수 없다 — 소스를 훑어 확인한다."""
    import pathlib
    for name in ("creative_dashboard.py", "app.py"):
        path = pathlib.Path(__file__).resolve().parent.parent / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "pick_metrics_for(df)" in source, name
