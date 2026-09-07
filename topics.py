"""이번 달 분석 주제 후보를 찾고, 그 주제의 표 두 개를 만들어 준다.

**왜 이 모듈이 있는가.** 6·7월 시트 리포트와 8월 대시보드 블록을 실제로 대조해 보면
`■ 신규 소재 유형별 성과` 아래는 늘 같은 모양이다 — 주제 하나가 소재 태그/유형 하나이고,
그 아래에 표가 붙는다. 그리고 8월에 만든 뷰 6개의 형태는 딱 두 가지뿐이었다:

  A. 매체별 집계 — 행 `media`(+`os`), 대조군 ON, 썸네일 ON
  B. 소재단 상세 — 행 `ad`, `media`, 대조군 OFF

여섯 중 넷이 기본 7지표를 그대로 썼다. 즉 표 하나에서 실제로 정해지는 것은 **필터 하나**인데,
지금은 라벨·행·값·필터필드·필터값·대조군·썸네일·대조기준을 매번 다시 고르고 있었다
(뷰당 10~15회, 8월 전체로 80회 안팎).

주제 선정도 마찬가지다. 8월에 처음 등장한 태그는 `epn`·`comic`·`hashtag`·`comment` 넷이고
규리님이 잡은 주제 3개 중 2개가 여기서 그대로 나왔다. 나머지 MIX는 신규가 아니라 소진이
7월 ₩1.9M → 8월 ₩3.8M로 두 배 늘어난 유형이었다. 둘 다 계산으로 뽑힌다.

**이 모듈은 제안만 한다.** 무엇을 주제로 삼을지는 사람이 정한다 — 숫자에 안 나오는 맥락
(제작 의도, 광고주와 합의한 테스트 계획)이 늘 있기 때문이다. 우수/저조 자동 선정에
100%를 목표로 하지 않는 것과 같은 이유다.
"""

from __future__ import annotations

import copy
import re
from uuid import uuid4

import pandas as pd

from creative_data import (
    DEFAULT_PIVOT_VALUES,
    EXTRA_INFO_NONE,
    NON_MIX_LABEL,
    explode_extra_info,
)

#: 후보를 찾을 축. 값이 그대로 필터가 되므로 `DIMENSION_COLUMNS`에 있는 것만 쓴다.
CANDIDATE_FIELDS = ("extra_info_tag", "creative_type", "mix_group")

#: 주제가 될 수 없는 값. `없음`은 태그가 안 붙은 소재 전부, `일반`은 MIX가 아닌 소재
#: 전부라서 "이번 달 신규 소재군"이라는 뜻이 성립하지 않는다.
SENTINEL_VALUES = frozenset({EXTRA_INFO_NONE, NON_MIX_LABEL, "미분류", "확인불가", ""})

KIND_NEW = "new"
KIND_SURGE = "surge"

#: 급증 판정 배수. 직전 달 대비 이만큼 늘면 후보로 본다.
#:
#: 2.0으로 잡았더니 **8월 MIX가 1.97배로 아슬하게 빠졌다** — 규리님이 실제로 주제로 삼은
#: 소재군이다. 1.5로 낮추면 잡히고, 7월·8월 실데이터에서 후보가 3개만 늘었다.
SURGE_RATIO = 1.5

#: 후보로 볼 최소 소진액. 표 하나를 세울 만한 규모가 아니면 제안하지 않는다.
#: 대시보드의 `MIN_COST`와 같은 값이지만 뜻이 다르다(저쪽은 TOP N 후보 컷).
MIN_TOPIC_COST = 100_000


#: 버전·배리에이션 표기는 분석 주제가 아니다. 실데이터의 태그 어휘에는 `1`·`2`·`a`·`ab`·
#: `12th`·`12anniversaryw2`처럼 USP 버전 번호나 소재 배리에이션 표기가 섞여 들어와 있다
#: (소재명 규칙상 Extra Info 자리에 그런 값이 들어간다). 그대로 두면 7월 후보 목록의 3분의
#: 1이 이런 값으로 찬다. 규칙은 셋 중 하나라도 맞으면 제외:
#:   · 순수 숫자          `1`, `2`, `8`
#:   · 숫자로 시작        `12th`, `12anniversaryw2`
#:   · 길이 2 이하        `a`, `ab`, `bc`
_NOISE_TAG = re.compile(r"^\d|^[A-Za-z0-9]{1,2}$")


def _is_noise(field: str, value: str) -> bool:
    """주제가 될 수 없는 표기인가. 태그 축에만 적용한다 — 유형·MIX는 통제된 어휘다."""
    return field == "extra_info_tag" and bool(_NOISE_TAG.match(str(value).strip()))


def _axis_frame(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    """그 축으로 집계할 수 있는 프레임. 태그 축만 펼쳐야 한다.

    ⚠ 태그를 펼치면 한 소재가 여러 행이 되므로 **태그별 합계를 더하면 전체를 넘는다.**
    후보 목록은 순위를 매기는 용도지 구성비가 아니라 문제 없지만, 화면에는 그 사실을 적는다.
    """
    if field == "extra_info_tag":
        return explode_extra_info(frame)
    return frame


def _monthly_cost(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    """축의 값 × 월 → 소진액 표."""
    work = _axis_frame(frame, field)
    if work.empty or field not in work.columns or "month" not in work.columns:
        return pd.DataFrame()
    work = work[["month", field, "cost", "ad"]].copy()
    work[field] = work[field].fillna("").astype(str).str.strip()
    work = work[~work[field].isin(SENTINEL_VALUES)]
    if work.empty:
        return pd.DataFrame()
    return work


def _display_label(field: str, value: str) -> str:
    """화면·블록 제목에 쓸 이름.

    태그는 실데이터가 소문자로 정규화돼 있어(`split_extra_info`) 그대로 쓰면 제목이
    `epn 소재 성과 분석`이 된다. 실제 리포트는 `COMIC & HASHTAG`, `TEXT형`처럼 대문자로
    적으므로 아스키 태그는 대문자로 올린다. 한글·한자가 섞이면 손대지 않는다.
    """
    text = str(value).strip()
    if field == "extra_info_tag" and re.fullmatch(r"[a-z0-9]+", text):
        return text.upper()
    return text


def candidates(all_months: pd.DataFrame, month: int, *, lookback: int = 3,
               min_cost: float = MIN_TOPIC_COST) -> list[dict]:
    """이번 달 분석 주제 후보.

    · `new`   — 이번 달 소진이 문턱 이상이고, 직전 `lookback`개월 소진이 **0**
    · `surge` — 이번 달 소진이 문턱 이상이고, 직전 달 대비 `SURGE_RATIO`배 이상

    신규를 급증보다 위에 두고, 그 안에서는 소진액 내림차순이다. 신규가 "이번 달에 새로
    시도한 것"이라 리포트에서 먼저 다뤄지기 때문이다(6·7·8월 모두 그렇다).
    """
    if all_months is None or all_months.empty:
        return []

    month = int(month)
    window = [m for m in range(month - lookback, month) if m >= 1]
    found: list[dict] = []

    for field in CANDIDATE_FIELDS:
        table = _monthly_cost(all_months, field)
        if table.empty:
            continue

        cost = table.pivot_table(index=field, columns="month", values="cost",
                                 aggfunc="sum").fillna(0.0)
        this_month = cost[month] if month in cost.columns else None
        if this_month is None:
            continue
        prior_cols = [m for m in window if m in cost.columns]
        prior = cost[prior_cols].sum(axis=1) if prior_cols else 0.0
        last_month = cost[month - 1] if (month - 1) in cost.columns else None

        current_rows = table[table["month"] == month]
        ad_counts = current_rows.groupby(field)["ad"].nunique()

        for value, spend in this_month.items():
            if spend < min_cost or _is_noise(field, value):
                continue
            before = float(prior[value]) if prior_cols else 0.0
            previous = float(last_month[value]) if last_month is not None else 0.0

            if before == 0:
                kind = KIND_NEW
            elif previous > 0 and spend >= previous * SURGE_RATIO:
                kind = KIND_SURGE
            else:
                continue

            found.append({
                "field": field,
                "value": str(value),
                "label": _display_label(field, value),
                "cost": float(spend),
                "prev_cost": previous,
                "kind": kind,
                "ads": int(ad_counts.get(value, 0)),
            })

    # 같은 이름이 여러 축에 걸린다 — 7월 `MIX`가 태그 ₩0.6M · 유형 ₩1.9M · mix_group ₩11.0M
    # 셋으로 나왔다. 셋 다 보여주면 어느 것을 골라야 할지 알 수 없으므로 **소진액이 가장 큰
    # 축 하나만** 남긴다. MIX의 경우 그게 `mix_group`인데, 소재명 규칙이 안 지켜지는
    # 소재군이라 판정을 그 한 곳에 모아 둔 것과도 맞는다(`creative_data.mix_group`).
    widest: dict[str, dict] = {}
    for item in found:
        seen = widest.get(item["label"])
        if seen is None or item["cost"] > seen["cost"]:
            widest[item["label"]] = item

    result = list(widest.values())
    result.sort(key=lambda c: (c["kind"] != KIND_NEW, -c["cost"]))
    return result


def preset_title(label: str) -> str:
    return f"{label} 소재 성과 분석"


def preset_views(label: str, field: str, value: str) -> list[dict]:
    """이 주제의 표 두 개. 8월에 실제로 만든 구성과 같은 모양이다.

    ⚠ `id`를 반드시 여기서 박는다. 비워 두면 `view_with_defaults`가 리런마다 새 uuid를
      발급해 `view_key`가 계속 바뀌고, 위젯 상태·셀 강조 키가 전부 앵커를 잃는다.

    뷰 A의 행에 `os`를 넣는 이유: iOS·AOS는 CPI가 3배 이상 벌어져 한 덩어리로 묶으면
    소재 차이가 묻힌다(대조군 카드가 이미 같은 이유로 OS를 나눈다).
    """
    filters = {field: [str(value)]}

    def fresh() -> dict:
        """뷰마다 새 객체를 준다.

        ⚠ `dict(filters)`는 **얕은 복사**라 안쪽 리스트를 두 뷰가 공유한다. 한쪽 필터를
          고치면 다른 쪽이 따라 바뀐다 — `BLOCK_DEFAULTS`를 얕게 복사해 모든 블록이
          오염됐던 `a76aaa2`와 같은 유형이다. 테스트가 실제로 잡았다.
        """
        return {"filters": copy.deepcopy(filters),
                "values": list(DEFAULT_PIVOT_VALUES)}

    return [
        {
            "id": uuid4().hex[:6],
            "label": f"매체별 {label} 소재 성과",
            "kind": "pivot",
            "rows": [{"field": "media"}, {"field": "os"}],
            "contrast": True,
            "contrast_field": field,
            "thumbs": True,
            **fresh(),
        },
        {
            "id": uuid4().hex[:6],
            "label": f"{label} 소재단 성과",
            "kind": "pivot",
            "rows": [{"field": "ad"}, {"field": "media"}],
            "contrast": False,
            "contrast_field": "",
            "thumbs": False,
            **fresh(),
        },
    ]
