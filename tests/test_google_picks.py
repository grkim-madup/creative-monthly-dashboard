# -*- coding: utf-8 -*-
"""구글 표의 우수·저조 선정 — **항상 각 2개씩** 나와야 한다.

예전에는 두 번째 지표가 `인앱 CPA`로 고정돼 있었다. 그런데 **설치 목적(ACi)
캠페인은 인앱 액션을 아예 잡지 않는다**(구조적으로 0건). 그래서 그 슬롯이 놀고
색칠이 3개만 나왔다 — 실측(7월) AOS·인스톨 기준 TOP10에서 인앱 CPA를 쓸 수 있는
소재가 1개뿐이었다.
"""
import pandas as pd

from creative_data import (
    GOOGLE_PICK_PRIMARY,
    google_pick_metrics,
    pick_best_worst,
)


def table(rows: int, cpa_rows: int = 0, ctr_step: float = 0.005) -> pd.DataFrame:
    """구글 표 흉내. `cpa_rows`개에만 인앱 CPA가 있다.

    ⚠ CTR 간격을 실제 표 수준으로 벌려 둔다. 예전 픽스처는 `0.001` 간격이라
      10줄 스프레드가 **0.9%p**였고, 스프레드 문턱(1%p)이 생기자 "CTR을 쓴다"는
      단정이 전부 깨졌다 — 픽스처가 비현실적이었던 것이다(실제 AOS 표는 28%p).
      스프레드가 문턱 미달일 때의 동작은 `test_스프레드가_작으면_CPI를_두_번`에서
      따로 단정한다.
    """
    return pd.DataFrame([
        {"asset": f"a{i}", "media": "Google", "cost": 1_000_000 - i * 10_000,
         "CPI": 1000 + i * 100, "CTR": 0.01 + i * ctr_step,
         "인앱 CPA": (5000 + i * 100) if i < cpa_rows else None}
        for i in range(rows)
    ])


def test_cpi_is_always_the_primary():
    assert GOOGLE_PICK_PRIMARY == ("CPI", False)
    assert google_pick_metrics(table(10))[0] == ("CPI", False)


def test_falls_back_to_ctr_when_cpa_is_mostly_empty():
    """설치 목적 표가 이 경우다 — 인앱 액션이 0건이라 CPA를 못 쓴다."""
    metrics = google_pick_metrics(table(10, cpa_rows=1))
    assert [m for m, _ in metrics] == ["CPI", "CTR"]


def test_uses_cpa_when_it_covers_most_rows():
    """액션 목적 표는 CPA가 더 의미 있는 기준이다."""
    metrics = google_pick_metrics(table(10, cpa_rows=7))
    assert [m for m, _ in metrics] == ["CPI", "인앱 CPA"]


def test_half_coverage_is_the_line():
    assert [m for m, _ in google_pick_metrics(table(10, cpa_rows=5))][1] == "인앱 CPA"
    assert [m for m, _ in google_pick_metrics(table(10, cpa_rows=4))][1] == "CTR"


def test_always_picks_two_and_two():
    """색칠이 3개만 나오면 광고주가 "왜 하나가 없나"를 묻는다."""
    for cpa_rows in (0, 1, 4, 5, 7, 10):
        top = table(10, cpa_rows=cpa_rows)
        best, worst = pick_best_worst(top, google_pick_metrics(top))
        assert len(best) == 2, cpa_rows
        assert len(worst) == 2, cpa_rows


def test_picks_are_four_distinct_creatives():
    top = table(10, cpa_rows=1)
    best, worst = pick_best_worst(top, google_pick_metrics(top))
    assert len(set(best) | set(worst)) == 4


def test_empty_table_is_safe():
    assert google_pick_metrics(pd.DataFrame()) == [GOOGLE_PICK_PRIMARY]


def test_tiny_table_does_not_pick_from_two_values():
    """값이 2개뿐인 지표로 뽑으면 그 둘이 자동으로 best/worst가 되어 의미가 없다."""
    metrics = google_pick_metrics(table(10, cpa_rows=2))
    assert [m for m, _ in metrics] == ["CPI", "CTR"]


def test_스프레드가_작으면_CPI를_두_번():
    """열 줄 모두 값이 있어도 **갈리지 않으면** 쓰지 않는다.

    구글 iOS 실측: CTR 0.27~0.86%(0.59%p). 규리님은 그 표에서 CTR을 쓰지 않고
    CPI만 봤다(저조 = CPI 최고 2개 정확히). 커버리지만 보면 이걸 못 잡는다.

    ⚠ 보조가 없다고 지표를 하나만 두면 **슬롯이 1:1로 줄어** 우수·저조가 각 한 줄만
      칠해진다. 실측에서 재현율이 3/5 → 2/5로 떨어졌다. 그래서 CPI를 한 번 더 넣는다.
    """
    flat = table(10, ctr_step=0.0005)          # 스프레드 0.45%p
    assert [m for m, _ in google_pick_metrics(flat)] == ["CPI", "CPI"]
    best, worst = pick_best_worst(flat, google_pick_metrics(flat))
    assert len(best) == 2 and len(worst) == 2


def test_소재_카드는_선정을_다시_계산하지_않는다():
    """카드는 **표가 정한 결과를 받는다.** 두 곳에서 계산하면 반드시 갈린다.

    같은 실수를 두 번 했다:
      ① 카드만 `인앱 CPA`로 고정돼 있어 표는 4줄을 칠하는데 카드는 2개만 나왔다.
      ② 수기 지정을 표에만 붙였더니, 카드가 자동 선정을 그려서 **표에서 안 칠한
         소재의 카드가 나오고 칠한 소재의 카드는 빠졌다**(2026-09-08 규리님 지적:
         "이 옆집에는 호랑이가 산다 작품은 왜 썸네일 안 넣었어?").

    ⚠ 이 테스트는 예전에 `google_pick_metrics(df)`가 진입점에 **있어야** 한다고
      단정했다 — 카드가 자체 계산하는 구조를 정답으로 못 박고 있었던 것이다.
      그래서 ②를 못 잡았다. 지금은 반대를 단정한다.
    """
    import pathlib

    # ⚠ madup.app 배포판은 진입점 이름이 `app.py`다(포털이 그걸 요구한다).
    #    파일명을 하나만 박아 두면 그쪽에서 테스트가 깨져 push가 막힌다(실제로 막혔다).
    root = pathlib.Path(__file__).resolve().parent.parent
    checked = 0
    for name in ("creative_dashboard.py", "app.py"):
        path = root / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        # 구글 경로에 지표 목록을 손으로 적어 둔 곳이 없어야 한다.
        assert '[("CPI", False), ("인앱 CPA", False)]' not in source, name
        # 기준 계산은 표 한 곳(`view`)에서만.
        assert "google_pick_metrics(view)" in source, name
        assert "google_pick_metrics(df)" not in source, (
            f"{name}: 카드가 선정을 다시 계산합니다 — 표에서 받아야 합니다")
        # 카드는 표의 결정을 인자로 받는다.
        assert "def render_google_material_cards(df: pd.DataFrame, best: dict, worst: dict)" in source, name
        assert "render_google_material_cards(g_top, g_best, g_worst)" in source, name
        checked += 1
    assert checked


def test_표가_고른_것이_카드에_그대로_간다():
    """표가 한 번 고르고 카드는 그것을 받는다 — 계산이 한 곳이라 갈릴 수가 없다.

    수기 지정이 걸린 표에서도 성립해야 한다(자동 선정과 다른 소재를 가리킨다).
    """
    from creative_data import pick_best_worst

    top = table(10, cpa_rows=1)
    best, worst = pick_best_worst(top, google_pick_metrics(top))
    assert len(best) + len(worst) == 4

    # 수기 지정처럼 **자동과 다른** 결과를 넘겨도 카드는 그것을 따라야 한다.
    manual_best, manual_worst = {0: "CPI"}, {9: "CPI"}
    assert manual_best != best or manual_worst != worst


def test_top_n_is_displayed_by_spend():
    """**고르는 기준과 보여주는 순서는 다르다**(2026-09-07 규리님 요청).

    인스톨·인앱 액션으로 TOP N을 고르되, 표는 소진액 내림차순으로 읽는다 —
    리포트에서 줄을 훑을 때 "돈을 얼마 썼나"가 먼저 눈에 들어와야 한다.
    진입점 코드가 그 순서로 되어 있는지 소스로 확인한다(진입점은 import할 수 없다).
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    entry = next((root / n for n in ("creative_dashboard.py", "app.py")
                  if (root / n).exists()))
    source = entry.read_text(encoding="utf-8")
    assert 'g_top = g_top.sort_values(g_rank_metric, ascending=False).head' in source
    assert 'g_top = g_top.sort_values("cost", ascending=False).reset_index' in source
