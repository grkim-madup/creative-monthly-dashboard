"""전월 대비 델타 — 달이 안 끝난 상태로 전체 월끼리 비교하면 조용히 틀린 숫자가 나온다.

실제 데이터(2026-08-23까지 들어온 8월)로 재보면 7월 전체 대비 소진액 -26.2%,
7월 1~23일 대비 -0.4%다. 전자를 리포트에 실으면 광고주에게 "예산이 4분의 1 줄었다"고
잘못 전달된다. 그 분기를 여기서 못 박는다.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from creative_data import (  # noqa: E402
    comparison_window,
    delta_label,
    month_is_complete,
    relative_change,
    scope_to_day,
)


def _dates(*values):
    return pd.Series(pd.to_datetime(list(values)))


def test_month_is_complete_when_data_reaches_last_day():
    assert month_is_complete(_dates("2026-07-01", "2026-07-31"), 7) is True


def test_month_is_incomplete_when_data_stops_early():
    assert month_is_complete(_dates("2026-08-01", "2026-08-23"), 8) is False


def test_february_last_day_is_month_specific():
    assert month_is_complete(_dates("2026-02-28"), 2) is True   # 2026년은 평년
    assert month_is_complete(_dates("2024-02-28"), 2, year=2024) is False  # 윤년은 29일


def test_missing_month_is_not_complete():
    assert month_is_complete(_dates("2026-07-31"), 8) is False


def test_comparison_window_is_open_for_a_finished_month():
    assert comparison_window(_dates("2026-07-01", "2026-07-31"), 7) is None


def test_comparison_window_caps_at_last_loaded_day():
    assert comparison_window(_dates("2026-08-01", "2026-08-23"), 8) == 23


def test_scope_to_day_trims_the_comparison_month():
    df = pd.DataFrame({
        "month": [7, 7, 7],
        "date": pd.to_datetime(["2026-07-10", "2026-07-23", "2026-07-31"]),
        "cost": [1, 1, 1],
    })
    assert len(scope_to_day(df, 7, 23)) == 2
    assert len(scope_to_day(df, 7, None)) == 3


def test_relative_change_basic():
    assert relative_change(110, 100) == pytest.approx(0.10)
    assert relative_change(90, 100) == pytest.approx(-0.10)


def test_relative_change_returns_none_instead_of_infinity():
    # 'inf%'나 '+99999%'는 광고주에게 숫자가 아니라 결함으로 읽힌다
    assert relative_change(100, 0) is None
    assert relative_change(None, 100) is None
    assert relative_change(100, float("nan")) is None


def test_delta_label_shows_only_the_change_rate():
    # 전월 실적 원값은 붙이지 않는다 — 좁은 카드에서 두 숫자가 섞이면 헷갈린다
    assert delta_label(0.094) == "▲ 9.4%"
    assert delta_label(-0.004) == "▼ 0.4%"
    assert delta_label(0) == "－ 0.0%"
    assert delta_label(None) == ""


def test_partial_month_comparison_matches_the_real_incident():
    """실제 사고 재현: 같은 집행량인데 비교 방식만 다르면 결론이 뒤집힌다."""
    july = pd.DataFrame({
        "month": [7] * 31,
        "date": pd.date_range("2026-07-01", periods=31),
        "cost": [10.0] * 31,
    })
    august = pd.DataFrame({
        "month": [8] * 23,
        "date": pd.date_range("2026-08-01", periods=23),
        "cost": [10.0] * 23,
    })
    data = pd.concat([july, august])

    naive = relative_change(august["cost"].sum(), july["cost"].sum())
    assert naive == pytest.approx(-0.258, abs=0.001)  # 하루 집행액은 그대로인데 -26%

    day = comparison_window(data["date"], 8)
    fair = relative_change(
        scope_to_day(data, 8, day)["cost"].sum(),
        scope_to_day(data, 7, day)["cost"].sum(),
    )
    assert fair == pytest.approx(0.0)  # 같은 기간끼리면 변화 없음


# ---------------------------------------------------------------------------
# 표 컬럼 구성 — 정렬 기준 컬럼이 표에서 빠지면 "왜 이 순서인지" 읽는 사람이 알 수 없다.

from creative_data import DISPLAY_COLUMNS, display_columns  # noqa: E402

ALL_COLUMNS = [
    "ad", "media", "cost", "impression", "click", "CTR", "CPC",
    "total install", "CPI", "D0 read", "D0 read CVR", "D0 coin", "D0 coin CVR",
]


def _frame(columns=None):
    return pd.DataFrame(columns=columns or ALL_COLUMNS)


def test_default_view_drops_redundant_raw_columns():
    columns = display_columns(_frame())
    assert "click" not in columns and "CPC" not in columns
    assert "CTR" in columns and "CPI" in columns
    assert len(columns) == 9  # 13 → 9


def test_identifier_columns_come_first():
    assert display_columns(_frame())[:2] == ["ad", "media"]


@pytest.mark.parametrize("metric", ["D0 read", "D0 coin"])
def test_rank_metric_is_restored_next_to_its_ratio(metric):
    columns = display_columns(_frame(), metric)
    assert metric in columns
    assert columns.index(metric) == columns.index(f"{metric} CVR") - 1


@pytest.mark.parametrize("metric", ["cost", "total install"])
def test_rank_metric_already_shown_is_not_duplicated(metric):
    columns = display_columns(_frame(), metric)
    assert columns.count(metric) == 1
    assert columns == display_columns(_frame())


def test_missing_columns_are_skipped_not_faked():
    columns = display_columns(_frame(["ad", "media", "cost"]))
    assert columns == ["ad", "media", "cost"]


def test_unknown_rank_metric_does_not_break_the_table():
    assert display_columns(_frame(), "없는지표") == display_columns(_frame())


def test_delta_direction_follows_korean_market_convention():
    from creative_data import delta_direction
    assert delta_direction(0.05) == "up"      # 상승 → 빨강
    assert delta_direction(-0.05) == "down"   # 하락 → 파랑
    assert delta_direction(0) == ""           # 변화 없음 → 색 없음
    assert delta_direction(None) == ""
