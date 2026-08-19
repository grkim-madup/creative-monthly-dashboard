"""iOS 전환 지표(코호트) 데이터 계층.

`Media_RAW`의 iOS 행에는 소진·노출·클릭만 있고 **설치·열람·코인이 전부 0**이다. iOS 전환은
앱스플라이어 코호트 기준으로 별도 `iOS 코호트 RD` 탭에 들어온다(기존 시트의 iOS 표가
'UA D0 read'를 쓰는 이유). 이 모듈이 그 탭을 읽어 iOS 전환 지표를 채워 넣는다.

탭 구조상 주의점:
- 한 소재가 `event_name` 4종(open / af_content_view / af_spent_credits / af_purchase)으로
  4행 반복되고 **`users`(설치) 값이 모든 행에 똑같이 복제**된다. 그냥 더하면 설치가 4배가 된다.
- 반대로 day별 지표 컬럼은 자기 event 행에만 값이 있고 나머지는 0이라 그대로 합산해도 된다.
"""

from __future__ import annotations

import pandas as pd

from creative_data import _find_column, normalize_media, to_number

IOS_COHORT_SHEET_NAME = "iOS 코호트 RD"

INSTALL_EVENT = "open"

# 코호트 탭 컬럼 → 대시보드 표준 지표
COHORT_METRICS = {
    "af_content_view_unique_users_day_0": "D0 read",
    "af_content_view_unique_users_day_7": "D7 read",
    "af_spent_credits_unique_users_day_0": "D0 coin",
    "af_spent_credits_unique_users_day_7": "D7 coin",
}

PID_ALIASES = {
    "facebook ads": "Meta",
    "tiktokglobal_int": "TikTok",
    "googleadwords_int": "Google",
    "apple search ads": "Apple Search Ads",
}


def _normalize_pid(value: str) -> str:
    return PID_ALIASES.get(str(value).strip().lower(), normalize_media(value))


def parse_ios_cohort(values: list[list[str]]) -> pd.DataFrame:
    """`iOS 코호트 RD` 값 → (month, media, ad) 단위 iOS 전환 지표."""
    if not values:
        return pd.DataFrame()

    header = values[0]
    width = len(header)
    raw = pd.DataFrame(
        [row + [""] * (width - len(row)) for row in values[1:]], columns=header
    )

    ad_col = _find_column(raw.columns, "ad 변환")
    if ad_col is None:
        raise ValueError("'ad 변환' 컬럼을 찾을 수 없습니다.")
    event_col = _find_column(raw.columns, "event_name")
    month_col = _find_column(raw.columns, "month")
    pid_col = _find_column(raw.columns, "pid")
    users_col = _find_column(raw.columns, "users")

    out = pd.DataFrame()
    out["ad"] = raw[ad_col].astype(str).str.strip()
    out["event"] = raw[event_col].astype(str).str.strip() if event_col else ""
    out["month"] = raw[month_col].map(to_number) if month_col else pd.NA
    out["media"] = raw[pid_col].map(_normalize_pid) if pid_col else ""

    # 설치는 event 4종에 복제되므로 한 종류만 센다. 나머지 지표는 자기 행에만 값이 있어 합산해도 안전.
    users = raw[users_col].map(to_number) if users_col else 0
    out["total install"] = users.where(out["event"] == INSTALL_EVENT, 0)

    for source, label in COHORT_METRICS.items():
        column = _find_column(raw.columns, source)
        out[label] = raw[column].map(to_number).fillna(0) if column is not None else 0.0

    out = out[out["ad"].astype(bool) & (out["ad"] != "nan")]
    if out.empty:
        return pd.DataFrame()

    metrics = ["total install", *COHORT_METRICS.values()]
    return (
        out.groupby(["month", "media", "ad"], dropna=False)[metrics]
        .sum(min_count=1)
        .reset_index()
    )


def apply_ios_cohort(df: pd.DataFrame, cohort: pd.DataFrame) -> pd.DataFrame:
    """iOS 행의 비어 있는 전환 지표를 코호트 값으로 채운다.

    RAW는 일별 행이고 코호트는 월 단위라, 각 (month, media, ad) 그룹의 **첫 행에만** 전환값을
    싣는다. 대시보드의 모든 집계가 이 키 이상으로 묶이므로 어떤 합계도 정확히 나온다.
    (일별 추이를 그리게 되면 이 방식은 다시 봐야 한다.)
    """
    if df.empty or cohort.empty:
        return df

    metrics = ["total install", *COHORT_METRICS.values()]
    out = df.copy()
    is_ios = out["os"] == "iOS"
    if not is_ios.any():
        return out

    lookup = cohort.set_index(["month", "media", "ad"])
    ios_rows = out[is_ios]
    first_of_group = ~ios_rows.duplicated(subset=["month", "media", "ad"], keep="first")
    keys = pd.MultiIndex.from_frame(ios_rows[["month", "media", "ad"]])
    # 구글처럼 소재 단위(ad)가 없는 iOS 행은 코호트 탭에 애초에 매칭될 수 없다. 매칭 안 되는
    # 행을 그냥 0으로 채우면 Media_RAW에 이미 있던 값(예: 구글의 자체 설치 수)까지 지워버린다
    # — 매칭된 행만 코호트 값으로 덮어쓰고, 매칭 안 된 행은 원래 값을 그대로 둔다.
    matched = pd.Series(keys.isin(lookup.index), index=ios_rows.index)

    for metric in metrics:
        if metric not in out.columns:
            out[metric] = 0.0
        cohort_values = pd.Series(
            lookup[metric].reindex(keys).to_numpy(), index=ios_rows.index
        ).fillna(0.0)
        original = out.loc[ios_rows.index, metric]
        out.loc[ios_rows.index, metric] = original.where(
            ~matched, cohort_values.where(first_of_group, 0.0)
        )

    return out
