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
    same_funnel_stage,
    pick_by_media,
    PICK_MIN_SPEND_SHARE,
    BACK_PICK_CANDIDATES,
    PICK_CANDIDATE_SHARE,
    pick_best_worst,
    pick_metrics_for,
)


def table(rows):
    return pd.DataFrame(rows)


def test_소진액은_지표_순위를_뒤집지_않는다():
    """규리님 2026-09-30: *"소진 예산도 더 적고 CPI도 저조한데 (왜 우수냐)."*

    ## 이 테스트는 예전 지정을 **뒤집은** 것이다 — 근거를 함께 남긴다

    예전에는 지표 상위 30% 구간 안에서 **소진액이 큰** 줄을 집었다. 팀원 피드백
    (2026-09-08) *"소진 비용은 신경 안 쓰고 CPI 좋다고 best야 이렇게 정한 느낌"* 이
    근거였고, 8월 픽 재현율이 53% → 71%로 올랐다.

    그런데 9월 화면에서 **CPI ₩1,039짜리가 CPI ₩1,424짜리에 밀렸다** — 소진이 5%
    적다는 이유였다(₩2,871,385 vs ₩3,019,416). 규리님이 그 화면을 보고 반려했다.
    규모는 이제 **후보 자격**(`PICK_MIN_SPEND_SHARE`)으로만 반영한다.

    ⚠ 재현율만 보고 되돌리지 말 것 — 되돌리면 8월 재현율은 오르지만 규리님이 실제
      화면을 보고 거부한 동작이 돌아온다.
    """
    df = table([
        {"ad": "CPI최고", "media": "Meta", "cost": 3_000_000, "CPI": 1_000},
        {"ad": "소진최고", "media": "Meta", "cost": 12_000_000, "CPI": 1_100},
        {"ad": "보통", "media": "Meta", "cost": 3_000_000, "CPI": 5_000},
        {"ad": "나쁨", "media": "Meta", "cost": 2_000_000, "CPI": 9_000},
    ])
    best, _worst = pick_best_worst(df, [("CPI", False)])
    assert [df.loc[i, "ad"] for i in best] == ["CPI최고"]


def test_저조도_지표_순위를_그대로_따른다():
    df = table([
        {"ad": "좋음", "media": "Meta", "cost": 5_000_000, "CPI": 1_000},
        {"ad": "그저그럼", "media": "Meta", "cost": 5_000_000, "CPI": 4_000},
        {"ad": "큰실패", "media": "Meta", "cost": 8_000_000, "CPI": 8_000},
        {"ad": "최악", "media": "Meta", "cost": 3_000_000, "CPI": 9_000},
    ])
    _best, worst = pick_best_worst(df, [("CPI", False)])
    assert [df.loc[i, "ad"] for i in worst] == ["최악"]


def test_볼륨_게이트가_소액을_후보에서_뺀다():
    """규리님: *"**소진 볼륨 높은 애들 중** CPI가 1순위."*

    소진을 순위에서 뺀 대신 규모는 후보 자격으로 남는다. 안 그러면 9월 `AOS·D0 Coin`
    에서처럼 소진 **₩194,915** 짜리가 그대로 우수가 된다.

    ⚠ 게이트는 **표 전체 기준**이다. 매체별로 걸면 줄이 적은 매체 안에서는 거의
      안 잘린다(그 TikTok은 4줄뿐이었다).
    """
    df = table([
        {"ad": "소액인데CPI최고", "media": "TikTok", "cost": 100_000, "CPI": 500},
        {"ad": "대규모", "media": "Meta", "cost": 12_000_000, "CPI": 1_100},
        {"ad": "보통", "media": "Meta", "cost": 3_000_000, "CPI": 5_000},
        {"ad": "나쁨", "media": "Meta", "cost": 2_000_000, "CPI": 9_000},
    ])
    best, _worst = pick_by_media(df)
    assert "소액인데CPI최고" not in {df.loc[i, "ad"] for i in best}


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

def test_코인_전환이_없는_표는_CTR로_넘어간다():
    """AOS 표는 D0 Coin CVR이 0.00~0.05%다 — 그걸로 뽑으면 아무 뜻이 없다.

    3순위는 CTR이다(규리님 지정: CPI → Coin CVR → CTR).
    """
    df = table([
        {"ad": f"a{i}", "cost": 1_000_000, "CPI": 2_000,
         "D0 coin CVR": 0.0, "D0 read CVR": 40.0 + i * 3, "CTR": 10.0 + i}
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


def test_스프레드가_아니라_우선순위_순서로_고른다():
    """⚠ **예전 지정을 뒤집은 것이다.** 예전에는 "가장 크게 갈리는 지표"를 썼다.

    규리님이 2026-09-30에 순서를 직접 지정했다(CPI → Coin CVR → Read CVR).
    그래서 **코인이 쓸 만하면 Read가 더 크게 갈려도 코인을 쓴다.**
    """
    both_usable = table([
        {"ad": f"a{i}", "cost": 1e6, "CPI": 2000,
         "D0 coin CVR": 1.0 + i * 1.4,      # 7.0%p
         "CTR": 10.0 + i * 8.0}             # 40%p — 더 크게 갈리지만 3순위다
        for i in range(6)])
    assert pick_metrics_for(both_usable)[1][0] == "D0 coin CVR"

    coin_flat = table([
        {"ad": f"a{i}", "cost": 1e6, "CPI": 2000,
         # ⚠ `metric_spread`는 비율을 **%p로 환산**한다(×100) — 문턱(1.0%p)을 밑돌게
         #   하려면 0.01이 아니라 0.001 단위로 줘야 한다.
         "D0 coin CVR": 1.0 + i * 0.001,    # 0.5%p — 갈리지 않는다 → 건너뛴다
         "CTR": 10.0 + i * 5.0}
        for i in range(6)])
    assert pick_metrics_for(coin_flat)[1][0] == "CTR"


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


def test_보조_지표_우선순위():
    """규리님 2026-09-30: *"보조 지표 순위를 CPI → Coin CVR → CTR 로 가자."*

    ⚠ CTR은 후보이되 **CPI를 이기지는 못한다** — 우수로 뽑히려면 CPI가 중앙값
    이하여야 한다(`test_우수의_주_지표가_저조보다_나쁘지_않다`).
    """
    assert [c for c, _ in BACK_PICK_CANDIDATES] == ["D0 coin CVR", "CTR"]


def test_후보_구간_기본값():
    """0 = 지표 순위를 소진액으로 뒤집지 않는다(2026-09-30 규리님 지정).

    규모는 `PICK_MIN_SPEND_SHARE` 후보 자격으로만 반영한다.
    """
    assert PICK_CANDIDATE_SHARE == pytest.approx(0.0)
    assert PICK_MIN_SPEND_SHARE == pytest.approx(0.02)


def test_화면이_이_헬퍼를_실제로_쓴다():
    """진입점은 테스트가 import할 수 없다 — 소스를 훑어 확인한다."""
    import pathlib
    for name in ("creative_dashboard.py", "app.py"):
        path = pathlib.Path(__file__).resolve().parent.parent / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "pick_metrics_for(df)" in source, name


# --------------------------------- 주 지표 자격 (규리님 2026-09-30: "우수인데 CPI가 안 좋다")

def _front_table():
    """앞단 보조 지표(CTR)를 쓰는 표. CPI와 CTR이 서로 반대로 간다."""
    # ⚠ `f` 에 소진을 가장 크게 준다 — 이 규칙은 "지표 상위 30% 구간에서 **소진이 큰**
    #   줄"을 집으므로, 소진이 작으면 자격과 무관하게 애초에 안 뽑혀 검사가 무의미해진다.
    return pd.DataFrame({
        "ad": ["a", "b", "c", "d", "e", "f"],
        "cost": [9_000_000, 8_000_000, 7_000_000, 6_000_000, 5_000_000, 10_000_000],
        "CPI": [1_200, 1_300, 1_500, 1_600, 1_800, 1_900],
        # 보조 지표 1등(`f`)이 CPI로는 꼴찌다 — 자격이 없으면 이 줄이 우수로 올라온다.
        "CTR": [1.0, 1.2, 1.4, 1.6, 1.8, 3.0],
        "total install": [7_500, 6_100, 4_600, 3_700, 2_700, 2_100],
    })


def test_우수의_주_지표가_저조보다_나쁘지_않다():
    """9월 AOS·인스톨 실측: 우수 CPI ₩1,690인데 저조가 ₩1,573·₩1,603이었다.

    CPI 컬럼만 보는 사람에게는 규칙이 틀린 것처럼 읽힌다.
    """
    table = _front_table()
    best, worst = pick_best_worst(table, [("CPI", False), ("CTR", True)])
    assert best and worst
    assert max(table.loc[i, "CPI"] for i in best) < min(table.loc[i, "CPI"] for i in worst)


def test_앞단_보조로도_주_지표_자격을_지킨다():
    """CTR 1등(`f`)은 CPI가 꼴찌라 우수가 될 수 없다."""
    table = _front_table()
    best, _worst = pick_best_worst(table, [("CPI", False), ("CTR", True)])
    assert "f" not in {table.loc[i, "ad"] for i in best}


def test_보조_슬롯에도_자격을_건다():
    """⚠ **2026-09-30에 뒤집혔다.**

    예전에는 뒷단(코인) 슬롯에 자격을 걸지 않았다 — 팀원도 코인 기준 표에서는 CPI를
    우선하지 않았기 때문이다(8월 iOS·D0Coin: BEST CPI ₩8,313 vs WORST ₩5,340).

    그런데 보조 후보에서 CTR을 뺀 뒤 보조는 **전부 뒷단**이 됐고, 규리님이 고른 B안이
    *"Read CVR 1위 — 단 CPI 중앙값 이하에서"* 였다. 그래서 자격을 모든 슬롯에 건다.
    """
    frame = _front_table().rename(columns={"CTR": "D0 coin CVR"})
    # 코인 1등(`f`)은 CPI가 꼴찌라 이제 우수가 될 수 없다.
    best, _worst = pick_best_worst(
        frame, [("CPI", False), ("D0 coin CVR", True)])
    assert "f" not in {frame.loc[i, "ad"] for i in best}


def test_퍼널_단계_구분():
    assert same_funnel_stage("CPI", "CTR")
    assert same_funnel_stage("D0 coin CVR", "D0 read CVR")
    assert not same_funnel_stage("CPI", "D0 coin CVR")


def test_자격을_만족하는_후보가_없으면_자격을_푼다():
    """색칠이 4개가 아니라 3개만 나오는 것이 더 나쁘다(실측으로 겪은 회귀다)."""
    table = _front_table()
    best, worst = pick_best_worst(table, [("CPI", False), ("CTR", True)])
    assert len(best) == 2 and len(worst) == 2
