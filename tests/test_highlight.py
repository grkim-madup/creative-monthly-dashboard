import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# 이 함수들은 예전에 진입점(creative_dashboard.py)에 있었고, 진입점을 import할 수 없어서
# 이 파일이 **같은 구현을 복사해** 두고 테스트했다. 복사본이 통과해도 진짜 코드는 검증되지
# 않는다 — 그래서 선정 로직은 creative_data.py로 옮기고 여기서 **실제 구현을 import** 한다.
# 선정 규칙 자체는 `test_pick_rule_composite.py`가 고정한다(2026-10-01 재정립).
from creative_data import pick_by_media  # noqa: E402


def test_empty_frame_is_safe():
    assert pick_by_media(pd.DataFrame()) == ({}, {})


def test_frame_without_cost_is_safe():
    assert pick_by_media(pd.DataFrame({"ad": ["a"], "CPI": [5.0]})) == ({}, {})


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
    rows = [
        ("shared", "TikTok", 5_000_000, 1_000, 0.10),
        ("tt-b", "TikTok", 4_500_000, 3_000, 0.02),
        ("tt-c", "TikTok", 4_000_000, 3_200, 0.03),
        ("shared", "Meta", 5_000_000, 9_000, 0.001),
        ("meta-b", "Meta", 4_500_000, 5_000, 0.03),
        ("meta-c", "Meta", 4_000_000, 5_200, 0.04),
    ]
    return pd.DataFrame(rows, columns=["ad", "media", "cost", "CPI", "D0 coin CVR"])


def test_same_creative_across_media_can_both_be_picked():
    """서로 다른 매체의 같은 소재가 동시에 뽑히는 건 허용한다(막지 않는다)."""
    df = _same_ad_two_media()
    best, worst = pick_by_media(df, rank_metric="D0 coin", spend_floor_share=0.0)
    picked_ads = df.loc[list(best) + list(worst), "ad"].tolist()
    assert picked_ads.count("shared") == 2  # TikTok 우수 / Meta 저조


def test_note_flags_the_duplicated_creative_with_media_and_slot():
    df = _same_ad_two_media()
    best, worst = pick_by_media(df, rank_metric="D0 coin", spend_floor_share=0.0)
    note = shared_pick_note(df, best, worst, "ad", "media")
    assert "shared" in note
    assert "TikTok" in note and "Meta" in note
    assert "우수" in note and "저조" in note


def test_note_is_empty_when_all_picks_are_different_creatives():
    df = _same_ad_two_media()
    df.loc[3, "ad"] = "meta-only"
    best, worst = pick_by_media(df, rank_metric="D0 coin", spend_floor_share=0.0)
    assert shared_pick_note(df, best, worst, "ad", "media") == ""
