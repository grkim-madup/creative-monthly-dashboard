import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# creative_dashboard는 streamlit 스크립트라 통째로 import하면 실행된다 —
# 선택 로직만 같은 구현으로 떼어 검증한다.
def spend_pool(df, spend_quantile=0.5, group_column="media"):
    if df.empty or "cost" not in df.columns:
        return df
    if group_column in df.columns and df[group_column].notna().any():
        keep = df.groupby(group_column, dropna=False)["cost"].transform(
            lambda costs: costs >= costs.quantile(spend_quantile)
        )
        pool = df[keep.fillna(False)]
    else:
        pool = df[df["cost"] >= df["cost"].quantile(spend_quantile)]
    return pool if not pool.empty else df


def pick_best_worst(df, metrics, spend_quantile=0.5, group_column="media"):
    best, worst = {}, {}
    if df.empty or "cost" not in df.columns:
        return best, worst
    pool = spend_pool(df, spend_quantile, group_column)
    claimed = set()

    def claim(column, ascending, target):
        if column not in pool.columns:
            return
        values = pd.to_numeric(pool[column], errors="coerce").dropna()
        values = values[values > 0]
        for index in values.sort_values(ascending=ascending).index:
            if index not in claimed:
                target[index] = column
                claimed.add(index)
                return

    for column, higher_is_better in metrics:
        claim(column, not higher_is_better, best)
    for column, higher_is_better in metrics:
        claim(column, higher_is_better, worst)
    return best, worst


def _two_media():
    """예산 규모가 크게 다른 두 매체. TikTok은 전부 소액, Meta는 전부 고액."""
    return pd.DataFrame({
        "ad": ["tt-big", "tt-mid", "tt-small", "meta-big", "meta-mid", "meta-small"],
        "media": ["TikTok", "TikTok", "TikTok", "Meta", "Meta", "Meta"],
        "cost": [2_000_000.0, 1_500_000.0, 100_000.0,
                 90_000_000.0, 70_000_000.0, 40_000_000.0],
        "CPI": [1_500.0, 2_500.0, 300.0, 6_000.0, 12_000.0, 9_000.0],
        "D0 coin CVR": [0.02, 0.03, 0.90, 0.05, 0.004, 0.01],
    })


def test_threshold_is_per_media_not_global():
    """전체 컷이면 TikTok 소재가 통째로 빠진다 — 매체별 컷이라 각 매체 상위가 남아야 한다."""
    pool = spend_pool(_two_media())
    assert set(pool["ad"]) == {"tt-big", "tt-mid", "meta-big", "meta-mid"}


def test_global_cut_would_have_dropped_the_small_budget_media():
    # 비교용: 매체 구분 없이 자르면 TikTok은 둘 다 탈락한다.
    pool = spend_pool(_two_media(), group_column="(없음)")
    assert set(pool["media"]) == {"Meta"}


def test_small_spend_creative_within_its_media_is_excluded():
    best, worst = pick_best_worst(_two_media(), [("CPI", False), ("D0 coin CVR", True)])
    picked = set(best) | set(worst)
    assert 2 not in picked  # tt-small: CPI 300으로 최저지만 TikTok 내 하위라 제외
    assert 5 not in picked  # meta-small: Meta 내 하위라 제외


def test_picks_one_best_and_one_worst_per_metric():
    best, worst = pick_best_worst(_two_media(), [("CPI", False), ("D0 coin CVR", True)])
    assert best[0] == "CPI"            # tt-big = 남은 후보 중 CPI 최저
    assert best[3] == "D0 coin CVR"    # meta-big = 남은 후보 중 coin CVR 최고
    assert worst[4] == "CPI"           # meta-mid = CPI 최고(저조)
    assert len(best) == 2 and len(worst) >= 1


def test_always_four_distinct_creatives_are_highlighted():
    """CPI 우수/저조 + Coin CVR 우수/저조 = 서로 다른 소재 4개가 하이라이트되어야 한다."""
    best, worst = pick_best_worst(_two_media(), [("CPI", False), ("D0 coin CVR", True)])
    assert len(best) == 2 and len(worst) == 2
    assert not (set(best) & set(worst))  # 겹치는 소재 없음
    assert len(set(best) | set(worst)) == 4


def test_same_creative_winning_two_slots_pushes_the_next_one_up():
    """한 소재가 두 지표 모두 1등이면, 두 번째 슬롯은 차순위 소재가 가져간다."""
    df = pd.DataFrame({
        "ad": ["all-star", "second", "third", "worst"],
        "media": ["TikTok"] * 4,
        "cost": [100.0, 100.0, 100.0, 100.0],
        "CPI": [1.0, 2.0, 3.0, 9.0],          # all-star가 CPI 최저
        "D0 coin CVR": [0.9, 0.5, 0.2, 0.01],  # all-star가 coin CVR 최고
    })
    best, worst = pick_best_worst(df, [("CPI", False), ("D0 coin CVR", True)])
    assert best[0] == "CPI"              # all-star는 CPI 슬롯이 먼저 가져감
    assert best[1] == "D0 coin CVR"      # coin CVR 슬롯은 차순위 second로 밀림
    assert len(set(best) | set(worst)) == 4


def test_falls_back_to_whole_table_when_media_column_missing():
    """구글 표에는 매체 컬럼이 없다(전부 구글) — 그때는 표 전체 기준으로 자른다."""
    df = pd.DataFrame({
        "ad": ["a", "b", "c", "d"],
        "cost": [400.0, 300.0, 200.0, 100.0],
        "CPI": [10.0, 20.0, 30.0, 40.0],
    })
    pool = spend_pool(df)
    assert set(pool["ad"]) == {"a", "b"}


def test_empty_frame_is_safe():
    assert pick_best_worst(pd.DataFrame(), [("CPI", False)]) == ({}, {})


def test_pool_never_returns_empty():
    df = pd.DataFrame({"ad": ["a"], "media": ["TikTok"], "cost": [0.0], "CPI": [5.0]})
    assert len(spend_pool(df)) == 1


METRIC_LABELS = {"CPI": "CPI", "D0 coin CVR": "D0 코인 CVR"}


def shared_pick_note(df, best, worst, id_column, group_column):
    picked = {**{i: ("우수", c) for i, c in best.items()},
              **{i: ("저조", c) for i, c in worst.items()}}
    if not picked or id_column not in df.columns:
        return ""
    rows = df.loc[list(picked)]
    duplicated = rows[rows[id_column].duplicated(keep=False)]
    if duplicated.empty:
        return ""
    notes = []
    for name, group in duplicated.groupby(id_column, sort=False):
        parts = []
        for index, row in group.iterrows():
            kind, column = picked[index]
            where = str(row[group_column]) if group_column in group.columns else ""
            parts.append(f"{where} {kind}·{METRIC_LABELS.get(column, column)}".strip())
        notes.append(f"{name} → {' / '.join(parts)}")
    return "같은 소재가 중복 선정됨 — " + " , ".join(notes)


def _same_ad_two_media():
    """같은 소재명이 TikTok/Meta 양쪽에 집행된 상황 — 매체별로 성과가 갈린다."""
    return pd.DataFrame({
        "ad": ["shared", "shared", "tt-b", "tt-small", "meta-b", "meta-small"],
        "media": ["TikTok", "Meta", "TikTok", "TikTok", "Meta", "Meta"],
        "cost": [5_000_000.0, 5_000_000.0, 4_500_000.0, 100_000.0,
                 4_500_000.0, 100_000.0],
        "CPI": [1_000.0, 9_000.0, 3_000.0, 50.0, 5_000.0, 50.0],
        "D0 coin CVR": [0.10, 0.001, 0.02, 0.99, 0.03, 0.99],
    })


def test_same_creative_across_media_can_both_be_picked():
    """서로 다른 매체의 같은 소재가 동시에 뽑히는 건 허용한다(막지 않는다)."""
    df = _same_ad_two_media()
    best, worst = pick_best_worst(df, [("CPI", False), ("D0 coin CVR", True)])
    picked_ads = df.loc[list(best) + list(worst), "ad"].tolist()
    assert picked_ads.count("shared") == 2  # TikTok/Meta 양쪽이 각각 선정됨


def test_note_flags_the_duplicated_creative_with_media_and_slot():
    df = _same_ad_two_media()
    best, worst = pick_best_worst(df, [("CPI", False), ("D0 coin CVR", True)])
    note = shared_pick_note(df, best, worst, "ad", "media")
    assert "shared" in note
    assert "TikTok" in note and "Meta" in note
    assert "우수" in note and "저조" in note


def test_note_is_empty_when_all_picks_are_different_creatives():
    best, worst = pick_best_worst(_two_media(), [("CPI", False), ("D0 coin CVR", True)])
    assert shared_pick_note(_two_media(), best, worst, "ad", "media") == ""
