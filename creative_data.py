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
    "UA D7(uni) read": "UA D7 read",
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
    return agg.sort_values(rank_metric, ascending=False).head(limit).reset_index(drop=True)


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
