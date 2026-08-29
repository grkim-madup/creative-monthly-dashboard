"""먼슬리 크리에이티브 리포트 대시보드의 순수 데이터 계층.

Streamlit 의존성 없음 — 전부 pytest로 검증 가능한 순수 함수.
원본은 구글시트 `Media_RAW` 탭이며 절대 쓰지 않고 읽기만 한다.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

RAW_SHEET_NAME = "Media_RAW"

COL_MONTH = "월"
COL_DATE = "date"
COL_MEDIA = "매체명"
COL_UA = "UA / non-UA 구분"
COL_OS = "OS 구분"
COL_AD = "최종 AD"
COL_TITLE_KR = "타이틀 명 (국문)"
COL_TITLE_CODE = "Title ID (작품코드 상세)"
COL_GENRE = "유형"

# 합산 대상 원본 지표 (RAW 헤더명 → 대시보드 표기명)
SUM_METRICS = {
    "impression": "impression",
    "click": "click",
    "cost (마크업 포함)": "cost",
    "total install": "total install",
    "D0(uni) read": "D0 read",
    "D0(uni) coin": "D0 coin",
    "D7(uni) coin": "D7 coin",
    # "UA D7(uni) read"는 표에 노출하지 않는다(2026-08-28, 사용자 요청) — 집계 대상에서
    # 빼면 aggregate_by가 만들어내지 않으므로 모든 표에서 한 번에 사라진다.
}

MEDIA_ALIASES = {
    "facebook": "Meta",
    "meta": "Meta",
    "tiktok": "TikTok",
    "google": "Google",
    "googleadwords_int": "Google",
    "apple search ads": "Apple Search Ads",
}

# 소재명은 두 가지 순서가 공존한다(구형/신형 모두 실데이터에 존재):
#   신형: {작품코드}_{작품명}_{포맷}_{제작주체}_{유형}_{사이즈}_{변형...}
#         예) 2401_極權教師_VID_Webtoon-VS_MixTitle_9X16_1
#   구형: {작품코드}_{작품명}_{사이즈}_{포맷}_{제작주체}_{변형...}
#         예) 1618_某天成為公主_9X16_VID_VS_Teaser_1
_FORMATS = ("VID", "IMG", "GIF")
_SIZE_PATTERN = re.compile(r"^(?:\d+(?:\.\d+)?[Xx]\d+(?:\.\d+)?|ALL)$")

_KNOWN_PRODUCERS = ("webtoon", "madup", "wecreative", "krlab", "vs")


def size_orientation(size: str | None) -> str | None:
    """사이즈 토큰에서 방향을 계산한다. 가로세로 비를 직접 보므로 새 규격이 나와도 자동 대응."""
    if not size:
        return None
    if size.upper() == "ALL":
        return "혼합"
    match = re.fullmatch(r"(\d+(?:\.\d+)?)[Xx](\d+(?:\.\d+)?)", size)
    if not match:
        return None
    width, height = float(match.group(1)), float(match.group(2))
    if height == 0:
        return None
    ratio = width / height
    if ratio > 1.1:
        return "가로"
    if ratio < 0.9:
        return "세로"
    return "정방형"

# Extra Info 태그: 소재명 꼬리에 붙는 제작 배리에이션 마커.
# 네이밍 컨벤션 시트(Y~AH열)의 Extra Info1/2/3 실측값 기준.
VARIANT_TAGS = {
    "6s": "6초 컷다운",
    "text": "자막형",
    "sns": "SNS형",
    "kr": "한국어 VO",
    "thumb": "썸네일 변형",
    "tt": "틱톡 전용",
    "new": "신규 리프레시",
    "poster": "포스터형",
    "social": "소셜형",
    "epn": "EPN",
    "hashtag": "해시태그형",
    "comment": "댓글형",
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).lower()


def _find_column(columns, target: str):
    """공백/대소문자 차이를 무시하고 컬럼을 찾는다. 시트 헤더가 달마다 미묘하게 달라지기 때문."""
    wanted = _norm(target)
    for col in columns:
        if _norm(col) == wanted:
            return col
    return None


def normalize_media(value: str) -> str:
    return MEDIA_ALIASES.get(_norm(value), str(value).strip())


def to_number(value) -> float:
    """'₩1,234', '18.5%', '-', '' 같은 시트 표기를 float으로. 퍼센트는 비율(0.185)로 반환."""
    if value is None:
        return np.nan
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if text in ("", "-", "--", "#DIV/0!", "#N/A", "N/A"):
        return np.nan
    is_percent = text.endswith("%")
    text = re.sub(r"[^\d.\-]", "", text)
    if text in ("", "-", "."):
        return np.nan
    try:
        number = float(text)
    except ValueError:
        return np.nan
    return number / 100 if is_percent else number


def parse_ad_name(ad_name: str) -> dict:
    """소재명을 속성으로 분해한다. 규칙에 안 맞으면 해당 필드를 None으로 둔다(추정하지 않음)."""
    blank = {
        "title_code": None,
        "title_name": None,
        "format": None,
        "producer": None,
        "creative_type": None,
        "size": None,
        "orientation": None,
        "usp": None,
        "extra_info": None,
        "variants": [],
    }
    if not ad_name or not str(ad_name).strip():
        return blank

    parts = str(ad_name).strip().split("_")
    result = dict(blank)

    format_index = next(
        (i for i, p in enumerate(parts) if p.upper() in _FORMATS),
        None,
    )
    if format_index is None:
        return result

    result["format"] = parts[format_index].upper()

    head = parts[:format_index]
    tail = parts[format_index + 1:]

    # 구형 표기는 포맷 앞에 사이즈가 온다 — 그때는 그 토큰을 작품명에서 떼어낸다.
    if head and _SIZE_PATTERN.match(head[-1]):
        result["size"] = head[-1].upper()
        head = head[:-1]

    if len(head) >= 1:
        result["title_code"] = head[0]
    if len(head) >= 2:
        result["title_name"] = "_".join(head[1:])

    size_index = (
        None
        if result["size"]
        else next((i for i, p in enumerate(tail) if _SIZE_PATTERN.match(p)), None)
    )

    if size_index is None:
        # 사이즈가 앞에 있었거나 아예 없는 경우 — 제작주체/유형만 위치로 채운다.
        attrs = tail
    else:
        result["size"] = tail[size_index].upper()
        attrs = tail[:size_index]
        tail = tail[size_index + 1:]

    if attrs:
        # 첫 토큰이 알려진 제작주체일 때만 producer로 인정한다. 아니면 유형 후보로 넘긴다
        # (구형 표기에는 제작주체 자리가 아예 없어서, 위치로만 찍으면 버전번호가 제작주체로 들어간다).
        first = attrs[0]
        if any(first.lower().startswith(p) for p in _KNOWN_PRODUCERS):
            result["producer"] = first
            attrs = attrs[1:]
        if attrs:
            candidate = "_".join(attrs)
            if not candidate.isdigit():
                result["creative_type"] = candidate

    result["orientation"] = size_orientation(result["size"])

    # Dimension 뒤의 첫 토큰이 USP, 그 뒤 최대 3개가 Extra Info1/2/3 (네이밍 컨벤션 Y~AH열 기준).
    if tail:
        result["usp"] = tail[0]
        extras = [t for t in tail[1:4] if t.strip()]
        result["extra_info"] = "_".join(extras) if extras else None

    variants = []
    for token in tail:
        for chunk in re.split(r"[-_]", token):
            label = VARIANT_TAGS.get(chunk.lower())
            if label and label not in variants:
                variants.append(label)
    result["variants"] = variants
    return result


# 구형 소재명은 유형 자리에 버전번호/사이즈/담당자코드가 섞여 들어온다
# (예: "RT_9X16_1", "2_DA_Highlight"). 알려진 유형 키워드가 보이면 그걸로 정규화한다.
# 네이밍 컨벤션 시트(AC열 Creative Type)의 실제 값 18종 + 실데이터에만 있는 몇 가지.
CANONICAL_TYPES = (
    "SingleImage", "SingleVideo", "Highlight", "VoTrailer", "Trailer", "Carousel",
    "Explainer", "Teaser", "Visual", "Trend", "MixTitle", "MIX", "RECAP", "Spoiler",
    "SlideShow", "Actional", "AI", "OST", "Prologue", "Meme", "Event", "Branding",
)


def normalize_creative_type(creative_type: str | None) -> str | None:
    # `.map()`으로 이 함수를 호출하면 결측값이 파이썬 None이 아니라 float('nan')로 들어올
    # 때가 있다 — `bool(float('nan'))`은 True라서 `not creative_type`으로는 안 걸러지고
    # 그대로 str(nan) = "nan" 문자열이 되어버린다(실측으로 잡은 버그). pd.isna로 먼저 거른다.
    if pd.isna(creative_type) or not creative_type:
        return None
    text = str(creative_type)
    for canonical in CANONICAL_TYPES:
        if re.search(rf"(?<![A-Za-z]){re.escape(canonical)}(?![A-Za-z])", text, re.IGNORECASE):
            return canonical
    cleaned = re.sub(r"[_-]?\d+$", "", text).strip("_-")
    return cleaned or None


def producer_group(producer: str | None) -> str | None:
    """제작주체를 고객사 보고용 대분류로. Webtoon-XX(담당자 코드)는 전부 '네이버웹툰'."""
    if not producer:
        return None
    head = str(producer).split("-")[0].strip().lower()
    if head == "webtoon":
        return "네이버웹툰"
    if head == "madup":
        return "매드업"
    return str(producer)


def parse_raw_values(values: list[list[str]]) -> pd.DataFrame:
    """Media_RAW 2차원 값 → 정규화된 소재 단위 DataFrame."""
    if not values:
        return pd.DataFrame()

    header = values[0]
    width = len(header)
    rows = [row + [""] * (width - len(row)) for row in values[1:]]
    raw = pd.DataFrame(rows, columns=header)

    ad_col = _find_column(raw.columns, COL_AD) or _find_column(raw.columns, "ad")
    if ad_col is None:
        raise ValueError(f"'{COL_AD}' 컬럼을 찾을 수 없습니다. 헤더: {list(raw.columns)[:12]}")

    out = pd.DataFrame()
    out["ad"] = raw[ad_col].astype(str).str.strip()

    for source, label in [
        (COL_MONTH, "month"),
        (COL_DATE, "date"),
        (COL_MEDIA, "media"),
        (COL_UA, "ua_type"),
        (COL_OS, "os"),
        (COL_TITLE_KR, "title_kr"),
        (COL_TITLE_CODE, "title_code_raw"),
        (COL_GENRE, "genre"),
    ]:
        col = _find_column(raw.columns, source)
        out[label] = raw[col].astype(str).str.strip() if col is not None else ""

    out["month"] = out["month"].map(to_number)
    out["media"] = out["media"].map(normalize_media)

    for source, label in SUM_METRICS.items():
        col = _find_column(raw.columns, source)
        out[label] = raw[col].map(to_number) if col is not None else np.nan

    # 구글은 '최종 AD'(소재명) 컬럼이 항상 비어 있다 — 소재 단위 태깅이 없어서지, 데이터가
    # 없는 게 아니다. 그대로 두면 아래 빈 값 필터에 걸려 구글 행 전체가 통째로 사라진다.
    # 소재 단위로는 못 쓴다는 걸 알 수 있게 자리표시자를 채워 살려 둔다.
    is_google = out["media"] == "Google"
    out.loc[is_google & (out["ad"] == ""), "ad"] = "-"

    out = out[out["ad"].astype(bool) & (out["ad"] != "nan")]
    return out.reset_index(drop=True)


def attach_creative_attributes(df: pd.DataFrame) -> pd.DataFrame:
    """소재명 파싱 결과를 컬럼으로 붙인다. 유니크 소재명 단위로만 파싱해 대용량에서도 빠르게."""
    if df.empty:
        return df
    unique_ads = pd.Series(df["ad"].unique(), name="ad")
    parsed = pd.DataFrame([parse_ad_name(a) for a in unique_ads])
    parsed["ad"] = unique_ads.values
    parsed["producer_group"] = parsed["producer"].map(producer_group)
    parsed["creative_type"] = parsed["creative_type"].map(normalize_creative_type)
    parsed["variant_label"] = parsed["variants"].map(
        lambda v: ", ".join(v) if v else "기본"
    )
    parsed["extra_info_label"] = parsed["extra_info"].fillna("없음")
    parsed = parsed.drop(columns=["variants"])
    return df.merge(parsed, on="ad", how="left")


def _safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    return numerator.divide(denominator.replace(0, np.nan))


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """CTR/CPC/CPI/CVR 파생 지표를 붙인다. 0으로 나누기는 NaN."""
    out = df.copy()
    out["CTR"] = _safe_divide(out["click"], out["impression"])
    out["CPC"] = _safe_divide(out["cost"], out["click"])
    out["CPI"] = _safe_divide(out["cost"], out["total install"])
    out["D0 read CVR"] = _safe_divide(out["D0 read"], out["total install"])
    out["D0 coin CVR"] = _safe_divide(out["D0 coin"], out["total install"])
    out["D7 coin CVR"] = _safe_divide(out["D7 coin"], out["total install"])
    return out


def aggregate_by(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """지정한 키로 합산 후 파생 지표 재계산. 비율은 절대 평균내지 않고 합계에서 다시 계산한다."""
    if df.empty:
        return df
    metrics = [c for c in SUM_METRICS.values() if c in df.columns]
    grouped = (
        df.groupby(keys, dropna=False)[metrics]
        .sum(min_count=1)
        .reset_index()
        .sort_values("cost", ascending=False)
    )
    return add_derived_metrics(grouped).reset_index(drop=True)


def top_creatives(
    df: pd.DataFrame,
    rank_metric: str,
    limit: int = 10,
    min_cost: float = 0.0,
) -> pd.DataFrame:
    """소재×매체 단위 합산 후 rank_metric 내림차순 TOP N."""
    agg = aggregate_by(df, ["ad", "media"])
    if agg.empty:
        return agg
    if min_cost > 0:
        agg = agg[agg["cost"].fillna(0) >= min_cost]
    top = agg.sort_values(rank_metric, ascending=False).head(limit).reset_index(drop=True)
    # 하이라이트 카드에 원어(국문) 작품명을 보여주려면 title_kr이 필요하다 — 집계 키에
    # 넣으면 소재×매체 단위가 쪼개지므로, 집계 후 소재별 대표값(최빈값)으로 붙인다.
    if "title_kr" in df.columns:
        title_map = (
            df[df["title_kr"].astype(bool)]
            .groupby("ad")["title_kr"]
            .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "")
        )
        top["title_kr"] = top["ad"].map(title_map).fillna("")
    return top


EXTRA_INFO_NONE = "없음"


def split_extra_info(value) -> list[str]:
    """`text-thumb`, `social_KR` 같은 값을 개별 태그로 쪼갠다. 값이 없으면 ['없음'].

    실데이터에 `SNS`/`sns`, `New`/`new`처럼 대소문자만 다른 표기가 섞여 있어 소문자로 통일한다
    (네이밍 컨벤션 시트의 Extra Info 표기도 소문자 기준). 안 그러면 같은 태그가 두 줄로 갈린다.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return [EXTRA_INFO_NONE]
    tags = [t.strip().lower() for t in re.split(r"[-_]", str(value)) if t.strip()]
    return list(dict.fromkeys(tags)) or [EXTRA_INFO_NONE]


def explode_extra_info(df: pd.DataFrame) -> pd.DataFrame:
    """Extra Info를 태그 단위 행으로 펼친다.

    한 소재가 태그를 여러 개 달고 있으면(`text-thumb`) 그 소재는 `text` 행과 `thumb` 행에
    **모두** 들어간다. 즉 태그별 합계를 전부 더하면 전체 소진액보다 커진다 — 태그별 비교용이지
    구성비를 보는 용도가 아니다. 화면에도 이 점을 표시한다.
    """
    if df.empty:
        return df.assign(extra_info_tag=pd.Series(dtype="object"))
    exploded = df.assign(extra_info_tag=df["extra_info"].map(split_extra_info))
    return exploded.explode("extra_info_tag").reset_index(drop=True)


def month_options(df: pd.DataFrame) -> list[int]:
    months = sorted({int(m) for m in df["month"].dropna().unique()})
    return months


def benchmark_row(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """전체 평균(합계 기반) 벤치마크 한 줄. TOP 소재 표 아래에 비교 기준으로 붙인다."""
    if df.empty:
        return df
    total = aggregate_by(df.assign(_all=label), ["_all"]).rename(columns={"_all": "ad"})
    total["media"] = "전체"
    return total


# ---------------------------------------------------------------------------
# 전월 대비 델타
#
# 리포트는 9월 초에 8월분을 보내므로 **발송 시점에는 그 달이 완결**돼 있다. 그래서 기본은
# 전체 월끼리 비교한다. 문제는 월중에 미리 열어볼 때다 — 8/23까지만 들어온 8월을 7월
# 31일치와 비교하면 소진액이 -26.2%로 나온다(실측). 실제로는 같은 기간끼리 -0.4%라
# 집행은 거의 동일한데, 달이 안 끝났다는 이유만으로 "예산이 4분의 1 줄었다"고 읽힌다.
#
# 이 프로젝트에서 반복된 실패 유형(에러 없이 조용히 틀림)이라, 사람이 매번 올바른 비교
# 방식을 고르게 두지 않고 **데이터가 그 달을 다 덮었는지 보고 자동으로 갈라준다.**


def month_is_complete(dates: pd.Series, month: int, year: int | None = None) -> bool:
    """그 달 마지막 날까지 데이터가 들어와 있는지. 순수 함수 — pytest 대상."""
    values = pd.to_datetime(pd.Series(dates), errors="coerce").dropna()
    scoped = values[values.dt.month == month]
    if year is not None:
        scoped = scoped[scoped.dt.year == year]
    if scoped.empty:
        return False
    last = scoped.max()
    return int(last.day) == int(last.days_in_month)


def comparison_window(dates: pd.Series, month: int, year: int | None = None) -> int | None:
    """비교에 쓸 '일자 상한'. 달이 완결됐으면 None(제한 없음), 아니면 마지막 일자.

    None을 돌려준다는 건 "전체 월끼리 비교해도 안전하다"는 뜻이다.
    """
    if month_is_complete(dates, month, year):
        return None
    values = pd.to_datetime(pd.Series(dates), errors="coerce").dropna()
    scoped = values[values.dt.month == month]
    if year is not None:
        scoped = scoped[scoped.dt.year == year]
    return None if scoped.empty else int(scoped.max().day)


def scope_to_day(df: pd.DataFrame, month: int, max_day: int | None) -> pd.DataFrame:
    """그 달 데이터에서 max_day 이하만 남긴다. max_day가 None이면 그 달 전체."""
    scoped = df[df["month"] == month]
    if max_day is None or scoped.empty or "date" not in scoped.columns:
        return scoped
    days = pd.to_datetime(scoped["date"], errors="coerce").dt.day
    return scoped[days <= max_day]


def relative_change(current: float, previous: float) -> float | None:
    """(현재-이전)/이전. 이전이 0이거나 값이 없으면 None(= 표시하지 않음).

    0으로 나눠 inf를 화면에 띄우는 것보다 아예 안 보여주는 게 낫다 — 광고주가 보는
    리포트에서 'inf%'나 '+99999%'는 숫자가 아니라 결함으로 읽힌다.
    """
    if current is None or previous is None:
        return None
    try:
        current = float(current)
        previous = float(previous)
    except (TypeError, ValueError):
        return None
    if pd.isna(current) or pd.isna(previous) or previous == 0:
        return None
    return (current - previous) / previous


def delta_direction(change: float | None) -> str:
    """델타 색상 클래스. 상승=빨강(up) / 하락=파랑(down) — 국내 증시 관례를 따른다
    (2026-08-28 사용자 지정). 변화가 없거나 알 수 없으면 색을 주지 않는다."""
    if not change:
        return ""
    return "up" if change > 0 else "down"


def delta_label(change: float | None) -> str:
    """KPI 카드에 붙일 변화율 한 조각(예: "▲ 12.1%").

    전월 실적 원값은 붙이지 않는다(2026-08-28) — 카드가 좁아 두 숫자가 한 줄에 들어가면
    어느 쪽이 이번 달 값인지 헷갈린다. '전월 대비'라는 기준만 옆에 표기한다.
    """
    if change is None:
        return ""
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "－")
    return f"{arrow} {abs(change) * 100:,.1f}%"


# ---------------------------------------------------------------------------
# 표에 그릴 컬럼 구성 (순수 함수 — pytest 대상)

# 표에 항상 띄우는 컬럼. 13개를 한 줄에 늘어놓으면 가로로 잘려 스크롤해야 읽히므로
# **원값과 비율이 겹치는 것부터 덜어냈다**(클릭→CTR, D0 read/coin 원값→각 CVR에 반영).
# 정렬 기준으로 고른 지표는 표에 안 보이면 왜 그 순서인지 알 수 없으므로, 아래
# display_columns()가 그 컬럼만 다시 끼워 넣는다.
DISPLAY_COLUMNS = [
    "ad", "media", "cost", "impression", "total install",
    "CTR", "CPI", "D0 read CVR", "D0 coin CVR",
]


# 원값 컬럼과 그 자리를 대신하는 비율 컬럼 — 정렬 기준으로 쓰일 때만 되살린다.
RAW_METRIC_SLOTS = {
    "total install": "total install",
    "D0 read": "D0 read CVR",
    "D0 coin": "D0 coin CVR",
    "cost": "cost",
}


def display_columns(df, rank_metric: str | None = None) -> list[str]:
    """표에 그릴 컬럼 순서. 정렬 기준 컬럼이 빠져 있으면 그 자리에 끼워 넣는다."""
    columns = [c for c in DISPLAY_COLUMNS if c in df.columns]
    if not rank_metric or rank_metric in columns or rank_metric not in df.columns:
        return columns
    anchor = RAW_METRIC_SLOTS.get(rank_metric)
    if anchor in columns:
        columns.insert(columns.index(anchor), rank_metric)
    else:
        columns.append(rank_metric)
    return columns
