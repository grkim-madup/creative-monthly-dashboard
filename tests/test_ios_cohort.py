import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ios_cohort import apply_ios_cohort, parse_ios_cohort  # noqa: E402

AD = "9764_地下白晝_VID_Webtoon_VoTrailer_9X16_1-KR"

HEADER = [
    "키값", "Title no", "국문명", "주차", "month", "ad 변환", "app_os", "cohort_type",
    "event_name", "date", "pid", "c", "af_adset", "af_ad", "users",
    "open_unique_users_day_0", "open_unique_users_day_2", "open_unique_users_day_7",
    "af_content_view_unique_users_day_0", "af_content_view_unique_users_day_2",
    "af_content_view_unique_users_day_7", "af_spent_credits_unique_users_day_0",
    "af_spent_credits_unique_users_day_2", "af_spent_credits_unique_users_day_7",
]


def _row(event, users, read0=0, read7=0, coin0=0, coin7=0, ad=AD, pid="Facebook Ads", month="7"):
    return [
        "key", "9764", "벙커의 낮", "27", month, ad, "ios", "user_acquisition",
        event, "2026-07-01", pid, "c", "adset", ad, str(users),
        "0", "0", "0",
        str(read0), "0", str(read7), str(coin0), "0", str(coin7),
    ]


def _values():
    """실제 탭처럼 한 소재가 event 4종으로 반복되고 users가 전부 복제된 형태."""
    return [
        HEADER,
        _row("open", "4,219"),
        _row("af_content_view", "4,219", read0=3336, read7=3515),
        _row("af_spent_credits", "4,219", coin0=167, coin7=291),
        _row("af_purchase", "4,219"),
    ]


def test_users_replicated_across_events_is_not_quadrupled():
    df = parse_ios_cohort(_values())
    assert len(df) == 1
    row = df.iloc[0]
    assert row["total install"] == pytest.approx(4219)  # 4219*4 = 16876 이면 버그
    assert row["D0 read"] == pytest.approx(3336)
    assert row["D0 coin"] == pytest.approx(167)
    assert row["D7 coin"] == pytest.approx(291)
    assert row["media"] == "Meta"
    assert row["month"] == 7


def test_pid_is_normalized_to_dashboard_media_names():
    values = [HEADER, _row("open", "10", pid="tiktokglobal_int")]
    assert parse_ios_cohort(values).loc[0, "media"] == "TikTok"


def test_rows_without_ad_are_dropped():
    values = [HEADER, _row("open", "10", ad="  ")]
    assert parse_ios_cohort(values).empty


def test_requires_ad_column():
    with pytest.raises(ValueError):
        parse_ios_cohort([["month", "users"], ["7", "1"]])


def _raw(rows):
    return pd.DataFrame(
        rows,
        columns=["month", "media", "os", "ad", "cost", "total install", "D0 read", "D0 coin"],
    )


def test_apply_fills_ios_conversions_once_per_group():
    cohort = parse_ios_cohort(_values())
    raw = _raw([
        [7, "Meta", "iOS", AD, 100.0, 0.0, 0.0, 0.0],   # 같은 소재의 일별 행 3개
        [7, "Meta", "iOS", AD, 200.0, 0.0, 0.0, 0.0],
        [7, "Meta", "iOS", AD, 300.0, 0.0, 0.0, 0.0],
    ])
    out = apply_ios_cohort(raw, cohort)
    # 그룹 전체 합이 코호트 값과 정확히 같아야 한다(행마다 복제되면 3배가 된다).
    assert out["total install"].sum() == pytest.approx(4219)
    assert out["D0 read"].sum() == pytest.approx(3336)
    assert out["cost"].sum() == pytest.approx(600)  # 소진액은 건드리지 않는다


def test_apply_leaves_aos_rows_untouched():
    cohort = parse_ios_cohort(_values())
    raw = _raw([[7, "Meta", "AOS", AD, 100.0, 55.0, 40.0, 2.0]])
    out = apply_ios_cohort(raw, cohort)
    assert out.loc[0, "total install"] == pytest.approx(55)
    assert out.loc[0, "D0 read"] == pytest.approx(40)


def test_apply_zeroes_ios_rows_with_no_cohort_match():
    cohort = parse_ios_cohort(_values())
    raw = _raw([[7, "Meta", "iOS", "다른_소재명", 100.0, 0.0, 0.0, 0.0]])
    out = apply_ios_cohort(raw, cohort)
    assert out.loc[0, "total install"] == pytest.approx(0)


def test_apply_preserves_original_value_when_ad_has_no_cohort_row():
    """구글처럼 소재 단위(ad='-')가 없는 매체는 코호트 탭에 애초에 매칭될 수 없다.

    매칭 안 된다고 0으로 덮어쓰면 Media_RAW에 이미 있던 구글의 자체 설치 수까지 지워진다 —
    매칭 안 된 행은 원래 값을 그대로 둬야 한다(위 '다른_소재명' 테스트는 원본이 이미 0이라
    이 회귀를 못 잡는다).
    """
    cohort = parse_ios_cohort(_values())
    raw = _raw([[7, "Google", "iOS", "-", 100.0, 42.0, 7.0, 0.0]])
    out = apply_ios_cohort(raw, cohort)
    assert out.loc[0, "total install"] == pytest.approx(42)
    assert out.loc[0, "D0 read"] == pytest.approx(7)


def test_apply_is_noop_when_cohort_empty():
    raw = _raw([[7, "Meta", "iOS", AD, 100.0, 0.0, 0.0, 0.0]])
    out = apply_ios_cohort(raw, pd.DataFrame())
    assert out.equals(raw)
