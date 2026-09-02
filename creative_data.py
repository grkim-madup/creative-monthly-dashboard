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
    #
    # ⚠ 실무에서는 Extra Info를 `_`가 아니라 **USP 뒤에 `-`로 붙이는 표기가 섞여 쓰인다**
    #   (`..._1X1_TITLE2-comic`, `..._9X16_BACK-6s-text-epn`, `..._9X16_1-KR`).
    #   예전에는 `-`를 안 쪼개서 `TITLE2-comic` 통째가 USP가 됐고, 그 바람에
    #   ①`comic`·`epn` 같은 태그가 Extra Info 드롭다운에 아예 안 뜨고
    #   ②같은 USP가 `1`/`1-KR`/`1-kr`/`1-new`/`1-tt`/`1-thumb`로 갈렸다.
    #   실측(2026-09-02): 8월 USP 144종 → 98종으로 합쳐지고 태그 14종 → 22종으로 늘었다.
    #   2월부터 쭉 있던 표기라 8월에 새로 생긴 문제가 아니라 처음부터 있던 누락이다.
    #
    #   `split_extra_info`가 이미 `-`와 `_`를 같게 다루므로, 여기서만 안 쪼개던 것이
    #   앞뒤가 안 맞았다. 첫 조각만 USP로 남기고 나머지는 Extra Info 앞에 붙인다.
    if tail:
        usp_token = tail[0]
        extras = [t for t in tail[1:4] if t.strip()]
        if "-" in usp_token:
            chunks = [c for c in usp_token.split("-") if c.strip()]
            if chunks:
                usp_token = chunks[0]
                extras = chunks[1:] + extras
        result["usp"] = usp_token
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


# --------------------------------------------------------------------------- #
# 우수/저조 선정 (2·3번 섹션의 행 색칠)
#
# 진입점(creative_dashboard.py)에 있던 것을 여기로 옮겼다 — 진입점은 import하는 순간
# 화면을 그려서 테스트가 부를 수 없고, 그래서 테스트가 같은 함수를 **복사해** 두고 있었다.
# 복사본을 테스트해 봐야 진짜 코드는 검증되지 않는다.
# --------------------------------------------------------------------------- #


def spend_pool(
    df: pd.DataFrame, spend_quantile: float = 0.5, group_column: str = "media"
) -> pd.DataFrame:
    """소진 볼륨 하위 구간을 후보에서 제외한다. `spend_quantile <= 0`이면 전부 남긴다.

    **기준선은 매체별로 따로 잡는다.** 매체마다 배정 예산의 절대 규모가 크게 달라서, 표 전체에
    하나의 컷을 걸면 예산이 작은 매체의 소재가 통째로 후보에서 빠져 버린다.
    """
    if df.empty or "cost" not in df.columns or spend_quantile <= 0:
        return df

    if group_column in df.columns and df[group_column].notna().any():
        keep = df.groupby(group_column, dropna=False)["cost"].transform(
            lambda costs: costs >= costs.quantile(spend_quantile)
        )
        pool = df[keep.fillna(False)]
    else:
        pool = df[df["cost"] >= df["cost"].quantile(spend_quantile)]

    return pool if not pool.empty else df


def pick_best_worst(
    df: pd.DataFrame,
    metrics: list[tuple[str, bool]],
    spend_quantile: float = 0.0,
    group_column: str = "media",
) -> tuple[dict, dict]:
    """지표별 최우수/최저조 소재를 하나씩 고른다. **후보는 넘겨받은 표 전체다.**

    2026-09-01 변경: 예전에는 여기서 `spend_pool`로 소진 하위 50%를 또 잘라냈다. 그런데
    이 함수에 들어오는 표는 **이미** 최소 소진액(₩100,000)으로 거르고 볼륨 상위 N개만
    남긴 것이라, 한 번 더 자르면 후보가 절반으로 줄어 **색칠이 4개가 아니라 3개만 나오는
    경우가 생겼다**(실측: 7월 AOS · D0 Read 정렬). 화면에 보이는 10개 중에서 고르는 편이
    읽는 사람에게도 설명하기 쉽다 — "이 표 안에서 가장 좋고 나쁜 것"이 되기 때문이다.
    `spend_quantile`을 주면 예전처럼 걸러낼 수 있다(기본값은 걸러내지 않음).

    metrics: [(컬럼, 값이 클수록 좋은가)] — 예 [("CPI", False), ("D0 coin CVR", True)]
    반환: ({인덱스: 사유}, {인덱스: 사유})
    """
    best: dict = {}
    worst: dict = {}
    if df.empty or "cost" not in df.columns:
        return best, worst

    pool = spend_pool(df, spend_quantile, group_column)
    claimed: set = set()

    def claim(column: str, ascending: bool, target: dict) -> None:
        """이미 다른 슬롯이 가져간 소재는 건너뛰고 그다음 순위를 고른다."""
        if column not in pool.columns:
            return
        values = pd.to_numeric(pool[column], errors="coerce").dropna()
        values = values[values > 0]
        for index in values.sort_values(ascending=ascending).index:
            if index not in claimed:
                target[index] = column
                claimed.add(index)
                return

    # 지표마다 우수 1개 + 저조 1개 = 총 4개 소재가 서로 겹치지 않게 뽑힌다.
    # (한 소재가 여러 슬롯의 1등이면 뒤 슬롯은 차순위로 밀려난다)
    for column, higher_is_better in metrics:
        claim(column, ascending=not higher_is_better, target=best)
    for column, higher_is_better in metrics:
        claim(column, ascending=higher_is_better, target=worst)

    return best, worst


def aggregate_by_axis(
    df: pd.DataFrame,
    axis: str,
    *,
    by_media: bool = True,
    min_cost: float = 0.0,
    values: list[str] | None = None,
) -> pd.DataFrame:
    """분석 축 하나로 집계한 표를 돌려준다.

    예전에는 이 로직이 진입점(`creative_dashboard.py`)의 4번 섹션 안에
    인라인으로 있었다. 진입점은 **어떤 테스트도 import하지 않는다**
    (import하는 순간 화면을 그리기 시작한다) — 그래서 숙자가 광고주에게
    그대로 가는데도 검증되지 않았다. 여기로 옷기면서 pytest로 고정한다.

    - `extra_info_tag` 축은 **부르는 쪽이 미리 펼쳐서**(`explode_extra_info`) 넣어야
      한다. 한 소재가 여러 태그에 들어가므로 태그별 합계를 더하면 전체보다 커진다.
    - 결측은 버리지 않고 `미분류`로 묶는다 — 조용히 사라지면 합계가 안 맞는다.
    """
    if df.empty or axis not in df.columns:
        return df.iloc[0:0]

    frame = df.copy()
    frame[axis] = frame[axis].fillna("미분류").replace("", "미분류")

    keys = [axis, "media"] if by_media and "media" in frame.columns else [axis]
    result = aggregate_by(frame, keys)
    if result.empty:
        return result
    if min_cost:
        result = result[result["cost"].fillna(0) >= min_cost]
    if values:
        result = result[result[axis].astype(str).isin(values)]
    return result.reset_index(drop=True)


#: 기간 비교표의 기본 지표 순서. 볼륨 → 효율 순으로, 실제 리포트 표와 같은 흐름이다.
COMPARE_DEFAULT_METRICS = [
    "cost", "impression", "click", "CTR", "total install", "CPI",
    "D0 read", "D0 read CVR", "D0 coin", "D0 coin CVR",
]

#: **증감을 어떤 단위로 쓸지는 지표마다 다르다.**
#: 비율 지표(CTR·CVR)는 두 값의 차이를 `%p`로, 금액·건수는 변화율을 `%`로 쓴다.
#: 49% → 53% 를 "+8.2%"로 쓰면 광고주가 8.2%p 오른 것으로 읽는다. 반대도 마찬가지다.
#: 이 매핑이 이 표의 유일한 위험 지점이라 상수로 박아 두고 pytest로 고정한다.
RATIO_METRICS = frozenset({"CTR", "D0 read CVR", "D0 coin CVR", "D7 coin CVR"})


def delta_unit(metric: str) -> str:
    """그 지표의 증감 단위. 비율은 `%p`(차이), 나머지는 `%`(변화율)."""
    return "%p" if metric in RATIO_METRICS else "%"


def compare_periods(
    df: pd.DataFrame,
    periods: list[dict],
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """두 기간을 나란히 놓고 증감을 붙인 표를 만든다.

    `periods`는 `[{"label": ..., "months": [3, 4]}, {"label": ..., "months": [5, 6]}]`.
    월을 여러 개 주면 그 기간의 **누적**이다(6월 리포트의 `방영 전 (4월 누적)` 같은 표).

    돌려주는 표는 다른 집계표와 축이 반대다 — **행이 지표, 열이 기간**이다.
    실제 리포트 시트가 그 모양이고, 지표마다 증감 단위가 달라 한 열에 섞을 수 없다.

    데이터가 없는 기간은 **0으로 채우지 않고 NaN으로 둔다.** 0으로 채우면 "집행을
    안 했다"와 "데이터가 없다"가 같은 숫자가 되고, 증감이 -100%로 찍힌다.
    """
    metrics = list(metrics or COMPARE_DEFAULT_METRICS)
    if len(periods) != 2:
        raise ValueError("기간 비교는 정확히 두 기간이어야 합니다.")

    columns: list[pd.Series] = []
    labels: list[str] = []
    for period in periods:
        months = [int(m) for m in (period.get("months") or [])]
        subset = df[df["month"].isin(months)] if months else df.iloc[0:0]
        if subset.empty:
            values = pd.Series({m: float("nan") for m in metrics}, dtype="float64")
        else:
            rolled = aggregate_by(subset.assign(_all="합계"), ["_all"]).iloc[0]
            values = pd.Series(
                {m: float(rolled[m]) if m in rolled.index and pd.notna(rolled[m])
                 else float("nan") for m in metrics},
                dtype="float64",
            )
        columns.append(values)
        labels.append(str(period.get("label") or f"{'·'.join(map(str, months))}월"))

    before, after = columns
    # 같은 라벨을 두 번 쓰면 열이 하나로 뭉개진다 — 사람이 붙이는 값이라 실제로 일어난다.
    if labels[0] == labels[1]:
        labels = [f"{labels[0]} (A)", f"{labels[1]} (B)"]

    deltas, units = [], []
    for metric in metrics:
        old, new = before[metric], after[metric]
        if pd.isna(old) or pd.isna(new):
            deltas.append(float("nan"))
        elif metric in RATIO_METRICS:
            # 비율은 차이(%p). 원본이 0~1 스케일이라 100을 곱해 %포인트로 만든다.
            deltas.append((new - old) * 100)
        else:
            deltas.append(relative_change(new, old))
        units.append(delta_unit(metric))

    return pd.DataFrame({
        "지표": [METRIC_DISPLAY.get(m, m) for m in metrics],
        labels[0]: before.to_numpy(),
        labels[1]: after.to_numpy(),
        "증감": deltas,
        "단위": units,
    })


#: 기간 비교표의 행 이름. 다른 표의 컬럼 라벨과 같은 표기를 써야 화면이 어긋나지 않는다.
METRIC_DISPLAY = {
    "cost": "소진액", "impression": "노출", "click": "클릭", "CTR": "CTR",
    "total install": "설치", "CPI": "CPI", "CPC": "CPC",
    "D0 read": "D0 Read", "D0 read CVR": "D0 Read CVR",
    "D0 coin": "D0 Coin", "D0 coin CVR": "D0 Coin CVR",
    "D7 coin": "D7 coin", "D7 coin CVR": "D7 coin CVR",
}


# --------------------------------------------------------------------------- 차트용 준비

#: 값이 **작을수록** 좋은 지표. 정렬 방향과 "평균보다 나은가" 판정이 여기서 갈린다.
LOWER_IS_BETTER = frozenset({"CPI", "CPC"})

#: 비율 지표의 벤치마크는 **평균의 평균이 아니라 합계에서 다시 계산**해야 한다.
#: 행별 CPI를 산술평균하면 소진 1%짜리 소재가 소진 40%짜리와 같은 무게를 갖는다.
BENCHMARK_RATIO = {
    "CPI": ("cost", "total install"),
    "CPC": ("cost", "click"),
    "CTR": ("click", "impression"),
    "D0 read CVR": ("D0 read", "total install"),
    "D0 coin CVR": ("D0 coin", "total install"),
    "D7 coin CVR": ("D7 coin", "total install"),
}


def metric_benchmark(table: pd.DataFrame, metric: str) -> float | None:
    """이 표 전체의 가중 평균. 차트의 기준선이 된다.

    볼륨 지표(`cost` 등)는 평균선이 의미가 없어 None을 돌려준다 —
    "소진액 평균보다 많이 썼다"는 결론으로 이어지지 않는다.
    """
    pair = BENCHMARK_RATIO.get(metric)
    if pair is None or table.empty:
        return None
    numerator, denominator = pair
    if numerator not in table.columns or denominator not in table.columns:
        return None
    bottom = float(table[denominator].fillna(0).sum())
    if bottom <= 0:
        return None
    return float(table[numerator].fillna(0).sum()) / bottom


def chart_frame(
    table: pd.DataFrame,
    axis: str,
    metric: str,
    low_volume_share: float = 0.02,
    benchmark: float | None = None,
) -> pd.DataFrame:
    """집계표를 차트용으로 정렬하고 저볼륨 행을 표시한다.

    실데이터에서 이걸 안 하면 **가장 눈에 띄는 막대가 노이즈**가 된다 —
    2026년 8월 Visual·Meta는 CPI ₩29,373으로 압도적 1위였지만 소진 ₩558,087에
    설치 19건이었다. 광고주 화면에서 그게 결론처럼 보이면 안 된다.

    - `_rank_value`: 정렬·기준선 비교에 쓸 값(결측은 맨 뒤로).
    - `_low_volume`: 이 표 전체 소진에서 차지하는 비중이 `low_volume_share` 미만.
      **버리지 않고 표시만 한다** — 없애면 합계가 안 맞고, 광고주가 표와 대조할 때 어긋난다.
    - `_better`: 기준선보다 나은 쪽인가(지표 방향을 반영).

    `benchmark`를 주면 그 값을 기준으로 삼는다. **실제 리포트의 기준은 표 안의 평균이
    아니라 "그 달 그 매체 전체 성과"** 다 — 시트에서도 `TikTok 신규유형 총계` 바로 아래
    `6월 틱톡 AOS 베너 소재 총 성과`를 붙여 놓고 눈으로 대조한다. 안 주면 표 자체의
    가중 평균을 쓴다(조건 없이 전체를 보는 표에서는 둘이 같다).
    """
    if table.empty or axis not in table.columns or metric not in table.columns:
        return table.iloc[0:0].assign(_rank_value=[], _low_volume=[], _better=[])

    out = table.copy()
    values = pd.to_numeric(out[metric], errors="coerce")
    out["_rank_value"] = values

    total = float(out["cost"].fillna(0).sum()) if "cost" in out.columns else 0.0
    out["_low_volume"] = (
        (out["cost"].fillna(0) / total < low_volume_share) if total > 0
        else pd.Series(False, index=out.index)
    )

    if benchmark is None:
        benchmark = metric_benchmark(out, metric)
    if benchmark is None:
        out["_better"] = pd.Series(pd.NA, index=out.index, dtype="object")
    elif metric in LOWER_IS_BETTER:
        out["_better"] = values <= benchmark
    else:
        out["_better"] = values >= benchmark

    # 좋은 쪽이 위로 오게 정렬한다. 결측은 항상 맨 뒤.
    ascending = metric in LOWER_IS_BETTER
    return (out.sort_values("_rank_value", ascending=ascending, na_position="last")
               .reset_index(drop=True))


def dumbbell_frame(table: pd.DataFrame, axis: str, metric: str) -> pd.DataFrame:
    """같은 축값이 매체 두 곳에 다 있는 것만 남겨 (축값, 매체A값, 매체B값)으로 만든다.

    한쪽에만 있는 축값은 **비교가 아니라 착시**라서 뺀다(선을 그을 수 없다).
    """
    needed = {axis, "media", metric}
    if table.empty or not needed <= set(table.columns):
        return pd.DataFrame(columns=[axis, "media_a", "value_a", "media_b", "value_b", "gap"])

    medias = sorted(table["media"].dropna().unique())
    if len(medias) != 2:
        return pd.DataFrame(columns=[axis, "media_a", "value_a", "media_b", "value_b", "gap"])

    wide = table.pivot_table(index=axis, columns="media", values=metric, aggfunc="first")
    wide = wide.dropna(subset=medias)
    if wide.empty:
        return pd.DataFrame(columns=[axis, "media_a", "value_a", "media_b", "value_b", "gap"])

    first, second = medias
    result = pd.DataFrame({
        axis: wide.index.astype(str),
        "media_a": first, "value_a": wide[first].to_numpy(),
        "media_b": second, "value_b": wide[second].to_numpy(),
    })
    result["gap"] = (result["value_b"] - result["value_a"]).abs()
    return result.sort_values("gap", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 표 컬럼 커스터마이즈 (순수 함수 — pytest 대상)

#: **차원** 컬럼 — 고르면 집계 키가 된다. 즉 빼면 단순히 가려지는 게 아니라
#: 그 축을 합쳐서 **숫자가 다시 계산된다**(피벗과 같은 동작).
#: 매체를 빼면 소재 한 줄에 매체 합계가 들어가고, 매체를 넣으면 소재가 매체별로 쪼개진다.
DIMENSION_COLUMNS = [
    "ad", "media", "os", "title_kr", "creative_type", "format",
    "size", "orientation", "producer_group", "usp",
]

#: **지표** 컬럼 — 집계 결과를 보여줄 뿐 집계 키에 영향을 주지 않는다.
METRIC_COLUMNS = [
    "cost", "impression", "click", "total install",
    "D0 read", "D0 coin", "D7 coin",
    "CTR", "CPC", "CPI", "D0 read CVR", "D0 coin CVR", "D7 coin CVR",
]

#: 화면에 내보이는 순서 = 이 목록의 순서. 사용자가 고른 순서를 쓰지 않는다 —
#: 표마다 컬럼 순서가 달라지면 여러 표를 나란히 놓고 비교할 때 눈이 매번 헤맨다.
SELECTABLE_COLUMNS = DIMENSION_COLUMNS + METRIC_COLUMNS


def _chosen_or_default(chosen: list[str] | None,
                       fallback: list[str] | None = None) -> list[str]:
    """빈 목록을 '컬럼 0개'로 읽지 않는다 — 그러면 표가 통째로 사라진다."""
    return list(chosen) if chosen else list(fallback or DISPLAY_COLUMNS)


def grouping_keys(chosen: list[str] | None, always: list[str],
                  available, fallback: list[str] | None = None) -> list[str]:
    """이 표를 무엇으로 묶을지 — **고른 차원 컬럼이 곧 집계 키**다.

    `always`(소재 목록의 `ad`, 집계표의 축)는 사용자가 빼도 되살린다. 그게 없으면
    표가 무엇의 집계인지 알 수 없는 숫자 덩어리가 된다.
    """
    columns = set(available)
    keep = {c for c in _chosen_or_default(chosen, fallback)
            if c in DIMENSION_COLUMNS and c in columns}
    keep |= {c for c in always if c in columns}
    ordered = [c for c in always if c in keep]
    ordered += [c for c in DIMENSION_COLUMNS if c in keep and c not in ordered]
    return ordered


def pick_columns(df, chosen: list[str] | None, always: list[str] | None = None,
                 fallback: list[str] | None = None) -> list[str]:
    """표에 그릴 컬럼 순서. 집계가 끝난 프레임에 대해 부른다.

    집계 키에서 빠진 차원 컬럼은 프레임에 아예 없으므로 자동으로 제외된다 —
    "가리기"가 아니라 "다시 계산"이라는 점이 여기서 자연스럽게 지켜진다.
    """
    available = list(df.columns)
    always = list(always or [])
    keep = {c for c in _chosen_or_default(chosen, fallback) if c in available}
    keep |= {c for c in always if c in available}

    ordered = [c for c in always if c in keep]
    ordered += [c for c in SELECTABLE_COLUMNS if c in keep and c not in ordered]
    # 목록에 없는 컬럼(집계 축 등)은 always로 들어오지 않았다면 버린다 — 화면 순서를
    # 정의할 수 없는 컬럼이 끼면 표가 예측 불가능해진다.
    return ordered
