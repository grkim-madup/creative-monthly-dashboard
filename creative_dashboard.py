"""먼슬리 크리에이티브 성과 리포트 대시보드 (네이버웹툰-대만).

기존 구글시트 피벗 리포트를 대체한다. 원본 `Media_RAW` 탭을 읽기 전용으로 가져와
TOP 소재 / 소재 속성별 성과 / 작품별 성과를 매달 같은 절차로 재생산한다.

실행: run_creative_dashboard.bat  (localhost:8502 — ASA 대시보드 8501과 충돌 방지)
"""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import blocks as report_blocks
import dropbox_source
import highlights
import locks
import overrides as manual_overrides
from creative_data import (
    add_derived_metrics,
    aggregate_by,
    explode_extra_info,
    month_options,
    top_creatives,
)
from google_ads_report import (
    DEFAULT_COST_MARKUP,
    aggregate_google,
    creative_assets,
    load_google_ads_folder,
)
from sheet_loader import cache_timestamp, extract_sheet_id, load_media_raw
from streamlit_quill import st_quill

from next_step import (
    DEFAULT_IMAGE_MAX_HEIGHT,
    delete_image,
    image_data_uri,
    parse_pasted_table,
    save_image,
    to_preview_html,
)
from ui import (  # noqa: E402
    LOGO_PATH,
    footnote,
    inject_css,
    kpi_cards,
    note_header,
    report_header,
    section,
    sidebar_brand,
    status_row,
    table_title,
)

st.set_page_config(
    page_title="네이버웹툰 대만 · 먼슬리 크리에이티브 리포트",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else None,
    layout="wide",
    # Streamlit은 접힘 상태를 브라우저 localStorage에 저장한다. 항상 펼친 상태로 시작하게 고정해서
    # 이전 세션에서 접어둔 탓에 필터가 안 보이는 상황을 막는다.
    initial_sidebar_state="expanded",
)
inject_css()
auth.require_password()

# 구글 애셋 보고서 CSV가 쌓이는 드롭박스 폴더 (사이드바에서 변경 가능)
DEFAULT_GOOGLE_FOLDER = (
    r"C:\Users\MADUP\주식회사매드업 Dropbox\광고사업부\4. 광고주"
    r"\네이버 웹툰 대만\8. 기타\구글 먼슬리 크리"
)

DEFAULT_SHEET = (
    "https://docs.google.com/spreadsheets/d/1U7qbbsqlDhYAXUelEfSbGUP_DMkVS6qE8bo8m_ZFQko/edit"
)

# 매체 비교 차트 색 — 매체별로 고정된 색을 명시해 어떤 매체가 데이터에 먼저 나오든
# 항상 같은 색으로 보이게 한다(Plotly 기본 팔레트는 등장 순서대로 배정해 매달 바뀔 수 있다).
# 브랜드 그린은 리포트 전체에서 액센트 한 곳에만 쓰기로 해서 여기서는 제외하고,
# 구분은 잘 되면서 채도는 눈이 편한 수준으로 낮춘 색으로 골랐다.
MEDIA_COLORS = {
    "Meta": "#5b8fd1", "TikTok": "#e0806b", "Google": "#dba64d", "LINE": "#6fb98f",
}
MEDIA_COLOR_FALLBACK = "#a89bc9"

RANK_METRICS = {
    "total install": "인스톨",
    "D0 coin": "D0 Coin",
    "D0 read": "D0 Read",
    "cost": "소진액",
}

DISPLAY_COLUMNS = [
    "ad", "media", "cost", "impression", "click", "CTR", "CPC",
    "total install", "CPI", "D0 read", "D0 read CVR", "D0 coin", "D0 coin CVR",
]

COLUMN_LABELS = {
    "ad": "소재명",
    "media": "매체",
    "cost": "소진액(마크업 포함)",
    "impression": "노출",
    "click": "클릭",
    "total install": "설치",
    "D0 read": "D0 열람",
    "D0 coin": "D0 코인",
    "D0 read CVR": "D0 열람 CVR",
    "D0 coin CVR": "D0 코인 CVR",
}

# 퍼센트가 아닌 값은 전부 소수점 없이. 퍼센트만 소수 2자리.
MONEY_COLUMNS = ("cost", "cost_raw", "CPC", "CPI", "인앱 CPA")
COUNT_COLUMNS = (
    "impression", "click", "total install", "D0 read", "D7 read",
    "D0 coin", "D7 coin", "UA D7 read", "in_app_action",
)
PERCENT_COLUMNS = ("CTR", "D0 read CVR", "D0 coin CVR", "D7 coin CVR")

FORMATS = {
    **{c: "₩{:,.0f}" for c in MONEY_COLUMNS},
    **{c: "{:,.0f}" for c in COUNT_COLUMNS},
    **{c: "{:.2%}" for c in PERCENT_COLUMNS},
}
# 표는 컬럼을 한글 라벨로 바꾼 뒤 렌더링하므로, 같은 포맷을 한글 라벨에도 걸어둔다.
# (이게 없으면 renamed 컬럼에 포맷이 안 먹어 소진액·노출·설치가 소수점째로 나온다.)
FORMATS.update({
    COLUMN_LABELS[key]: fmt for key, fmt in list(FORMATS.items()) if key in COLUMN_LABELS
})
FORMATS.update({
    "인앱 액션": "{:,.0f}",
    "원가(마크업 전)": "₩{:,.0f}",
})

# 소재를 찾을 때 조건으로 쓸 수 있는 구분자 (네이밍 컨벤션 Y~AH열 + 집행 축)
PIVOT_FIELDS = {
    "creative_type": "Creative Type",
    "format": "Creative Format",
    "size": "Dimension",
    "orientation": "사이즈 방향",
    "extra_info_tag": "Extra Info (태그별)",
    "producer_group": "제작 주체",
    "usp": "USP",
    "title_kr": "작품",
    "media": "매체",
    "os": "OS",
}

METRIC_LABELS = {
    "cost": "소진액", "impression": "노출", "click": "클릭",
    "total install": "설치", "D0 read": "D0 열람", "D0 coin": "D0 코인",
    "D0 read CVR": "D0 열람 CVR", "D0 coin CVR": "D0 코인 CVR",
}


# 단일 톤 그라데이션 — 흰색에서 브랜드 그린 쪽으로만 진해진다.
# 무지개(RdYlBu)처럼 색상이 바뀌면 표가 많은 화면에서 눈이 금방 피로해져서, 명도 차이로만 추세를 본다.
_TONE_TARGET = (0, 194, 90)
_TONE_MAX_MIX = 0.55


def performance_colors(series: pd.Series, dark_when_large: bool = True) -> list[str]:
    """열 내 상대 위치를 한 가지 색의 농담으로만 표현한다.

    규칙은 '값이 클수록 진하게' 하나로 통일한다(사용자 요청). 좋고 나쁨을 색으로 판단하는 게 아니라
    숫자 크기의 분포를 눈으로 훑는 용도라, 지표마다 방향이 뒤집히면 오히려 헷갈린다.
    """
    values = pd.to_numeric(series, errors="coerce")
    valid = values.dropna()
    if valid.empty or valid.max() == valid.min():
        return [""] * len(values)

    low, high = valid.min(), valid.max()
    span = high - low
    styles = []
    for value in values:
        if pd.isna(value):
            styles.append("")
            continue
        position = (value - low) / span
        strength = position if dark_when_large else 1 - position
        mix = _TONE_MAX_MIX * strength
        r, g, b = (round(255 + (target - 255) * mix) for target in _TONE_TARGET)
        styles.append(f"background-color: rgb({r},{g},{b}); color: #14171a;")
    return styles


def style_table(df: pd.DataFrame, color_columns: list[str] | None = None):
    present = [c for c in df.columns if c in FORMATS]
    styler = df.style.format({c: FORMATS[c] for c in present}, na_rep="-")
    for column in color_columns or []:
        if column not in df.columns:
            continue
        colors = performance_colors(df[column])
        styler = styler.apply(lambda _, c=colors: c, subset=[column])
    return styler


HIGHLIGHT_STYLE = "background-color: #ffd93d; font-weight: 700;"


def render_table(
    df: pd.DataFrame, color_columns: list[str] | None = None,
    highlight_key: str | None = None, month: int | None = None,
) -> None:
    """표를 그린다. highlight_key를 주면 셀을 클릭·드래그해 그때그때 강조할 수 있다.

    st.dataframe은 캔버스라 Styler의 border는 무시하지만(실측 확인) background-color·
    font-weight는 반영된다 — "굵은 선" 대신 이 조합으로 강조한다. 강조는 월 단위로
    저장해 새로고침·재접속 후에도 남는다. 드래그로 여러 셀을 한 번에 잡을 수 있고,
    같은 범위를 다시 잡으면 취소된다.
    """
    renamed = df.rename(columns=COLUMN_LABELS)
    colors = [COLUMN_LABELS.get(c, c) for c in (color_columns or [])]
    styler = style_table(renamed, colors)

    if not highlight_key or month is None:
        st.dataframe(styler, width="stretch", hide_index=True)
        return

    saved_cells = highlights.load(month, highlight_key)

    def paint_selected(row):
        position = renamed.index.get_loc(row.name)
        return [
            HIGHLIGHT_STYLE if (position, col) in saved_cells else ""
            for col in row.index
        ]

    styler = styler.apply(paint_selected, axis=1)
    widget_key = f"hl_table_{highlight_key}_{month}"
    # 강조 목록은 항상 디스크가 기준이고, 프론트엔드 선택 상태는 "방금 드래그/클릭한
    # 범위"를 알려주는 일회성 신호로만 쓴다 — 새로고침 시 프론트엔드가 빈 선택으로
    # 시작하는 것 자체는 문제가 아니다(빈 값이면 그냥 아무 것도 안 한다). multi-cell이라
    # 드래그로 여러 셀을 한 번에 잡을 수 있다. 방금 잡은 범위가 전부 이미 강조돼 있으면
    # 그 범위를 전부 해제하고, 하나라도 강조가 안 돼 있으면 범위 전체를 강조한다 —
    # 그래서 같은 범위를 다시 드래그하면 "취소"가 된다.
    event = st.dataframe(
        styler, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="multi-cell", key=widget_key,
    )
    picked = [tuple(c) for c in event["selection"]["cells"]]
    if picked:
        cells = set(saved_cells)
        if all(c in cells for c in picked):
            cells.difference_update(picked)
        else:
            cells.update(picked)
        highlights.save(month, highlight_key, list(cells))
        # 위젯이 이미 이번 실행에서 그려진 뒤라 session_state에 새 값을 대입하면
        # StreamlitAPIException이 난다("cannot be modified after the widget is
        # instantiated") — 대신 키를 통째로 지운다. 다음 렌더에서 위젯이 빈 선택
        # 상태로 다시 시작해, 방금 처리한 드래그가 또 처리되는 걸 막는다.
        del st.session_state[widget_key]
        st.rerun()


# 행 전체 강조용 색 (기존 시트의 파랑=우수 / 빨강=저조 컨벤션)
ROW_GOOD = "background-color: #e7f9f0; color: #04703a; font-weight: 700;"
ROW_BAD = "background-color: #fdf1f1; color: #9b2c2c; font-weight: 700;"


def spend_pool(
    df: pd.DataFrame, spend_quantile: float = 0.5, group_column: str = "media"
) -> pd.DataFrame:
    """소진 볼륨 하위 구간을 후보에서 제외한다.

    **기준선은 매체별로 따로 잡는다.** 매체마다 배정 예산의 절대 규모가 크게 달라서, 표 전체에
    하나의 컷을 걸면 예산이 작은 매체의 소재가 통째로 후보에서 빠져 버린다.
    """
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


def pick_best_worst(
    df: pd.DataFrame,
    metrics: list[tuple[str, bool]],
    spend_quantile: float = 0.5,
    group_column: str = "media",
) -> tuple[dict, dict]:
    """소진 볼륨이 큰 편인 소재들 중에서만 지표별 최우수/최저조 소재를 하나씩 고른다.

    소액 집행 소재는 우연히 극단적인 효율이 찍히므로 후보에서 뺀다. 컷은 매체별로 잡는다.
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


def shared_pick_note(
    df: pd.DataFrame, best: dict, worst: dict, id_column: str, group_column: str
) -> str:
    """같은 소재가 슬롯 두 개 이상에 함께 뽑혔는지 알려주는 문구.

    서로 다른 매체에서 같은 소재가 동시에 선정되는 건 막지 않는다 — 같은 소재인데 매체별로 성과가
    갈린다는 뜻이라 그 자체가 인사이트다. 다만 표만 봐서는 알아채기 어려우니 문구로 짚어준다.
    """
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
            label = f"{where} {kind}·{METRIC_LABELS.get(column, column)}".strip()
            parts.append(label)
        notes.append(f"{name} → {' / '.join(parts)}")
    return "같은 소재가 중복 선정됨 — " + " , ".join(notes)


GOOGLE_RANK_METRICS = {
    "total install": "인스톨",
    "in_app_action": "인앱 액션",
    "cost": "소진액",
}

GOOGLE_COLUMNS = [
    "asset", "asset_type", "title_kr", "objective", "direction", "rating",
    "cost", "impression", "click", "CTR", "CPC",
    "total install", "CPI", "in_app_action", "인앱 CPA",
]

GOOGLE_LABELS = {
    "asset": "소재 링크", "asset_type": "애셋 유형", "title_kr": "작품",
    "objective": "캠페인 목적", "direction": "방향", "rating": "구글 실적 평가",
    "in_app_action": "인앱 액션",
}

GOOGLE_COLUMN_CONFIG = {
    "소진액(마크업 포함)": {"format": "₩%,d"},
    "노출": {"format": "%,d"},
    "클릭": {"format": "%,d"},
    "CTR": {"format": "%.2f%%"},
    "CPC": {"format": "₩%,d"},
    "설치": {"format": "%,d"},
    "CPI": {"format": "₩%,d"},
    "인앱 액션": {"format": "%,d"},
    "인앱 CPA": {"format": "₩%,d"},
}


def render_google_table(df: pd.DataFrame, highlight: bool = True, link_column: bool = True):
    """구글 표 — 소재 식별자가 URL이라 링크 컬럼이 필요해서 별도 렌더러를 쓴다.

    강조 규칙은 매체별 TOP 소재와 동일하게 우수/저조 행 단위. 다만 구글은 Coin CVR이 없어
    CPI와 인앱 CPA를 기준으로 뽑는다.
    """
    view = df[[c for c in GOOGLE_COLUMNS if c in df.columns]].copy()
    best, worst = pick_best_worst(view, [("CPI", False), ("인앱 CPA", False)]) if highlight else ({}, {})
    # NumberColumn의 '%.2f%%'는 값을 그대로 찍으므로 비율을 퍼센트 포인트로 바꿔서 넘긴다.
    if "CTR" in view.columns:
        view["CTR"] = view["CTR"] * 100

    renamed = view.rename(columns={**COLUMN_LABELS, **GOOGLE_LABELS})

    def paint(row):
        if row.name in best:
            return [ROW_GOOD] * len(row)
        if row.name in worst:
            return [ROW_BAD] * len(row)
        return [""] * len(row)

    config = {
        name: st.column_config.NumberColumn(**options)
        for name, options in GOOGLE_COLUMN_CONFIG.items()
        if name in renamed.columns
    }
    if link_column and "소재 링크" in renamed.columns:
        config["소재 링크"] = st.column_config.LinkColumn("소재 링크", display_text="열기")

    st.dataframe(
        renamed.style.apply(paint, axis=1),
        width="stretch",
        hide_index=True,
        column_config=config,
    )
    if highlight:
        note = shared_pick_note(view, best, worst, "asset", "objective")
        if note:
            status_row("info", "동일 소재 중복 선정", note)


def render_table_best_worst(df: pd.DataFrame, metrics: list[tuple[str, bool]]):
    """지표별 히트맵 대신, 우수 2행·저조 2행만 행 전체를 색칠한다(시트 컨벤션)."""
    best, worst = pick_best_worst(df, metrics)
    renamed = df.rename(columns=COLUMN_LABELS)
    present = [c for c in renamed.columns if c in FORMATS]
    styler = renamed.style.format({c: FORMATS[c] for c in present}, na_rep="-")

    def paint(row):
        if row.name in best:
            return [ROW_GOOD] * len(row)
        if row.name in worst:
            return [ROW_BAD] * len(row)
        return [""] * len(row)

    styler = styler.apply(paint, axis=1)
    st.dataframe(styler, width="stretch", hide_index=True)

    # 우수/저조 기준 설명은 OS(AOS/iOS)마다 똑같은 문구가 반복돼 눈이 피로하다는 피드백을
    # 받아, 이 함수에서는 더 이상 찍지 않는다 — 호출부(섹션 2)가 맨 아래에 한 번만 보여준다.
    if best or worst:
        note = shared_pick_note(df, best, worst, "ad", "media")
        if note:
            status_row("info", "동일 소재 중복 선정", note)


# --------------------------------------------------------------------------- 사이드바

sidebar_brand("크리에이티브 리포트", "네이버웹툰 대만 · 월간")

# 사이드바는 성격이 다른 것들이 한 줄로 섞여 있으면 금방 산만해진다. 매번 만지는 컨트롤과
# 어디서 읽어오는지를 알려주는 데이터 정보를 카드 두 개로 갈라 놓는다.
# 월·모드는 값 계산이 아래에서 이뤄지므로 자리만 먼저 잡고 나중에 채운다.
with st.sidebar.container(key="sb_controls"):
    st.markdown('<div class="sb-lab">리포트 월</div>', unsafe_allow_html=True)
    month_slot = st.container()
    st.markdown('<div class="sb-lab">모드</div>', unsafe_allow_html=True)
    mode_slot = st.container()

data_card = st.sidebar.container(key="sb_data")
with data_card:
    st.markdown('<div class="sb-card-t">데이터</div>', unsafe_allow_html=True)
    sheet_url = st.text_input(
        "구글시트 링크",
        value=DEFAULT_SHEET,
        help="매달 새 리포트 시트로 바뀌면 이 링크만 갈아끼우면 됩니다. 읽기 전용으로만 접근합니다.",
    )

try:
    sheet_id = extract_sheet_id(sheet_url)
except ValueError as error:
    st.sidebar.error(str(error))
    st.stop()

with data_card:
    if st.button("시트에서 다시 불러오기", width="stretch"):
        st.cache_data.clear()
        load_media_raw(sheet_id, refresh=True)
        st.rerun()

    stamp = cache_timestamp(sheet_id)
    if stamp:
        st.caption(
            f"마지막 동기화: {dt.datetime.fromtimestamp(stamp):%Y-%m-%d %H:%M}"
        )


@st.cache_data(show_spinner="Media_RAW 불러오는 중…")
def _load(sid: str) -> pd.DataFrame:
    return load_media_raw(sid)


try:
    raw = _load(sheet_id)
except Exception as error:  # 시트 권한/탭 이름 문제를 화면에 그대로 노출
    st.error(f"시트를 읽지 못했습니다: {error}")
    st.stop()

if raw.empty:
    st.warning("Media_RAW 탭에 데이터가 없습니다.")
    st.stop()

months = month_options(raw)
if not months:
    st.warning("월 컬럼을 해석하지 못했습니다.")
    st.stop()

# ?month=7 처럼 URL로도 월을 지정할 수 있게 해둔다(링크 공유·확인용).
_query_month = st.query_params.get("month")
try:
    _default_index = months.index(int(_query_month))
except (TypeError, ValueError):
    _default_index = len(months) - 1

with month_slot:
    month = st.selectbox(
        "리포트 월", months, index=_default_index, key="report_month",
        format_func=lambda m: f"2026년 {m}월", label_visibility="collapsed",
    )

# 로그인이 없으므로 브라우저 세션이 곧 편집자 신원이다
st.session_state.setdefault("editor_token", uuid4().hex)
with mode_slot:
    mode_choice = st.segmented_control(
        "모드", ["보기", "편집"], default="보기", key="mode_toggle",
        label_visibility="collapsed",
        help="편집을 선택하면 블록 추가·삭제·이동과 글 편집 버튼이 보입니다. "
             "보기는 고객사가 보는 화면 그대로입니다.",
    )
edit_mode = mode_choice == "편집"

# 아래 조건은 사이드바 위젯을 없애고 고정값으로 둔다(사용자 요청 — 사이드바를 비우기로 함).
# 매체·Creative Format·Creative Type·Dimension은 1번 총괄 섹션 안에서 직접 고를 수 있고,
# 나머지(OS·UA·최소 소진액)는 매달 같은 기준으로 보는 값이라 바뀔 일이 없다.
media_options = sorted(raw["media"].dropna().unique())
# 총괄(1번)에는 구글도 포함한다 — Media_RAW에 구글의 OS별 앱스플라이어 코호트 성과
# (cost/install/D0 read/D0 coin)가 메타·틱톡과 같은 스키마로 이미 들어 있다(2026-08-17 확인).
# 다만 구글은 소재 단위(ad='-')가 없어 2번(TOP 소재) 쪽은 별도로 메타/틱톡만 걸러 쓴다.
media_selection = [m for m in ("TikTok", "Meta", "Google") if m in media_options]
os_selection = sorted(raw["os"].dropna().unique())
ua_selection = ["UA"]
format_selection = ["VID", "IMG", "GIF"]
MIN_COST = 100_000  # 소액 집행 소재가 우연히 좋은 효율로 상위에 오르는 것을 막는 컷
min_cost = MIN_COST

@st.cache_data(show_spinner="Dropbox에서 구글 애셋 보고서 내려받는 중…", ttl=3600)
def _synced_google_folder(_cache_bust: int) -> str:
    """Dropbox 자격증명이 설정돼 있으면 그 폴더를 내려받아 로컬 캐시 경로를 반환한다.

    배포 서버엔 이 PC의 드롭박스 동기화 폴더가 없으므로, 서버에서는 이 경로가 항상 쓰인다.
    로컬 개발 PC처럼 자격증명이 없는 환경은 기존 동기화 폴더로 그대로 폴백한다(동작 그대로 유지).
    `_cache_bust`는 사이드바 새로고침 버튼이 눌릴 때만 값을 바꿔 캐시를 무효화하는 용도다.
    """
    if dropbox_source.configured():
        return str(dropbox_source.sync_google_folder())
    return DEFAULT_GOOGLE_FOLDER


# 구글은 시트가 아니라 드롭박스 폴더에서 읽는 별도 경로다. 다만 사용자 입장에서는 둘 다
# '이 리포트가 어디서 데이터를 읽는가'라서 같은 데이터 카드 안에 이어서 보여준다.
# 폴더 경로 대신 '실제로 읽은 파일'을 보여준다 — 잘못된 파일을 읽었을 때 바로 알아채려면
# 경로보다 파일 목록이 유용하다. 경로는 물음표 도움말로 옮긴다.
with data_card:
    st.markdown('<div class="sb-sub">구글 (별도 소스)</div>', unsafe_allow_html=True)
    google_files_slot = st.container()
    if dropbox_source.configured():
        if st.button("Dropbox에서 다시 불러오기", key="google_refetch"):
            st.session_state["_google_cache_bust"] = (
                st.session_state.get("_google_cache_bust", 0) + 1
            )
    cost_markup = st.number_input(
        "구글 비용 마크업 배율",
        min_value=1.0, max_value=2.0, value=DEFAULT_COST_MARKUP, step=0.001, format="%.4f",
        help="보고서의 '비용'은 원가입니다. 리포트 시트의 'cost (마크업 포함)' 기준에 맞추려면 "
             "이 배율을 곱합니다(2026-07 실측 1.0830).",
    )

google_folder = _synced_google_folder(st.session_state.get("_google_cache_bust", 0))

scope = raw[raw["month"] == month]
if media_selection:
    scope = scope[scope["media"].isin(media_selection)]
if os_selection:
    scope = scope[scope["os"].isin(os_selection)]
if ua_selection:
    scope = scope[scope["ua_type"].isin(ua_selection)]
if format_selection:
    # 구글은 Creative Format 컬럼 자체가 항상 비어 있다(소재 단위 태깅이 없어서지 미분류라서가
    # 아니다) — VID/IMG/GIF로 필터링하면 구글 행이 전부 잘려나가므로 구글은 이 필터를 건너뛴다.
    scope = scope[scope["format"].isin(format_selection) | (scope["media"] == "Google")]

scope = add_derived_metrics(scope)

report_header(
    kicker="LINE WEBTOON TAIWAN · MONTHLY CREATIVE REVIEW",
    title=f"{month}월 크리에이티브 성과 리포트",
    meta=[("기간", f"2026년 {month}월")],
    agenda=["총괄 성과", "매체별 TOP 소재 성과", "신규 소재 유형별 성과", "NEXT STEP"],
)

if scope.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 사이드바 필터를 조정해 주세요.")
    st.stop()

# --------------------------------------------------------------------------- 1. 총괄

section("1", "총괄 성과")

overview_controls = st.columns(4)
overview_media = overview_controls[0].multiselect(
    "매체", sorted(scope["media"].dropna().unique()), key="ov_media",
    placeholder="전체",
)
overview_format = overview_controls[1].multiselect(
    "Creative Format", sorted(scope["format"].dropna().unique()), key="ov_format",
    placeholder="전체",
)
overview_type = overview_controls[2].multiselect(
    "Creative Type", sorted(scope["creative_type"].dropna().unique()), key="ov_type",
    placeholder="전체",
)
overview_dimension = overview_controls[3].multiselect(
    "Dimension", sorted(scope["size"].dropna().unique()), key="ov_dim",
    placeholder="전체",
)

overview = scope
for column, selection in (
    ("media", overview_media),
    ("format", overview_format),
    ("creative_type", overview_type),
    ("size", overview_dimension),
):
    if selection:
        overview = overview[overview[column].isin(selection)]

if overview.empty:
    status_row("warn", "총괄 필터 조건에 맞는 데이터가 없습니다", "필터를 완화해 주세요.")
    st.stop()

# 소재명이 명명 규칙과 안 맞아 자동 분류가 실패한 실제 소재를, 사용자가 4·5번 섹션에서
# 수동으로 채워 넣은 값으로 패치한다(성과 수치는 그대로, 분류 컬럼만 덮어씀).
overview = manual_overrides.apply(overview, month)

# 4번(소재 속성별 성과)·5번(소재 분석)은 소재명 규칙(작품코드_작품명_...) 파싱이
# 있어야 의미가 있다. 구글은 소재 단위 태깅이 없어 ad가 전부 "-"라 규칙 파싱 대상이
# 아니다 — 두 섹션의 기준 데이터에서 미리 뺀다(1·2·3번 총괄/매체별 표는 그대로 포함).
named_overview = overview[overview["ad"] != "-"]

totals = aggregate_by(overview.assign(_all="전체"), ["_all"]).iloc[0]
kpi_cards([
    {"label": "소진액", "value": f"₩{totals['cost']:,.0f}", "sub": "마크업 포함",
     "primary": True},
    {"label": "노출", "value": f"{totals['impression']:,.0f}", "sub": "Impression"},
    {"label": "CTR", "value": f"{totals['CTR']:.2%}", "sub": "클릭 ÷ 노출"},
    {"label": "인스톨", "value": f"{totals['total install']:,.0f}", "sub": "Total install"},
    {"label": "CPI", "value": f"₩{totals['CPI']:,.0f}", "sub": "소진 ÷ 인스톨"},
    {"label": "D0 Read CVR", "value": f"{totals['D0 read CVR']:.2%}", "sub": "D0 Read ÷ 인스톨"},
])

table_title("매체 × OS 요약")
by_media_os = aggregate_by(overview, ["media", "os"])
render_table(by_media_os, color_columns=["CPI"], highlight_key="media_os", month=month)

# --------------------------------------------------------------------------- 2. TOP 소재

meta_tiktok = overview[overview["media"].isin(["Meta", "TikTok"])]

section(
    "2", "메타/틱톡 TOP 소재 성과", "*앱스플라이어 코호트 데이터 기준",
    badge=f"소재 {meta_tiktok['ad'].nunique():,}개",
)

controls = st.columns([2, 1])
rank_metric = controls[0].selectbox(
    "정렬 기준", list(RANK_METRICS), format_func=lambda m: RANK_METRICS[m]
)
top_n = controls[1].number_input("표시 개수", min_value=5, max_value=50, value=10, step=5)

for os_name in sorted(meta_tiktok["os"].dropna().unique()):
    os_scope = meta_tiktok[meta_tiktok["os"] == os_name]
    top = top_creatives(os_scope, rank_metric, limit=int(top_n), min_cost=min_cost)
    if top.empty:
        status_row("warn", f"{os_name}", "조건에 맞는 소재가 없습니다.")
        continue

    table_title(f"{os_name} — {RANK_METRICS[rank_metric]} 기준 TOP {int(top_n)}")
    render_table_best_worst(
        top[[c for c in DISPLAY_COLUMNS if c in top.columns]],
        metrics=[("CPI", False), ("D0 coin CVR", True)],
    )

    benchmark = aggregate_by(
        os_scope.assign(_all=f"{os_name} 전체 평균 (벤치마크)"), ["_all"]
    ).rename(columns={"_all": "ad"})
    render_table(
        benchmark[[c for c in DISPLAY_COLUMNS if c in benchmark.columns]],
        highlight_key=f"sec2_benchmark_{os_name}", month=month,
    )

# OS(AOS/iOS)마다 똑같이 반복되던 우수/저조 기준 설명을 섹션 하단에 한 번만 작게 남긴다.
st.caption(
    f"녹색 = 우수 / 붉은색 = 저조 · 매체별 소진 볼륨 하위 50% 제외 후 "
    f"{METRIC_LABELS.get('CPI', 'CPI')} · {METRIC_LABELS.get('D0 coin CVR', 'D0 coin CVR')} "
    f"기준으로 우수·저조 각 1개씩 선정 · 최소 소진 ₩{min_cost:,.0f} 이상"
)

# --------------------------------------------------------------------------- 3. 구글


@st.cache_data(show_spinner="구글 애셋 보고서 읽는 중…")
def _google(folder: str, markup: float) -> pd.DataFrame:
    return load_google_ads_folder(folder, cost_markup=markup)


google_all = pd.DataFrame()
google_error = None
try:
    google_all = _google(google_folder, cost_markup)
except Exception as error:
    google_error = str(error)

google = pd.DataFrame()
if not google_all.empty:
    google_all = google_all[google_all["month"] == month]
    google = creative_assets(google_all)

# 사이드바에 '이번 달 실제로 읽은 파일'을 채운다(위에서 자리만 잡아둔 곳).
with google_files_slot:
    if google_error:
        st.metric("애셋 보고서 파일", "읽기 실패", help=f"폴더: {google_folder}")
        st.caption(google_error[:120])
    elif google_all.empty:
        st.metric("애셋 보고서 파일", "0개", help=f"폴더: {google_folder}")
        st.caption(f"{month}월분 보고서가 폴더에 없습니다.")
    else:
        used_files = sorted(google_all["source_file"].dropna().unique())
        st.metric(
            "애셋 보고서 파일", f"{len(used_files)}개",
            help=f"폴더: {google_folder} (하위 폴더까지 모두 읽습니다)",
        )
        st.caption(f"{month}월 데이터로 사용 중")
        with st.expander("읽은 파일 보기"):
            st.markdown("\n".join(f"- `{name}`" for name in used_files))

# "이 데이터를 어디서 읽었는지"는 매달 볼 필요는 없는 진단 정보라 헤더의 "?" 아이콘으로
# 옮긴다 — 성공적으로 읽었을 때만 채워진다(실패·데이터 없음은 아래 경고로 바로 보여준다).
google_read_hint = None
if not google_error and not google.empty:
    google_read_hint = (
        "구글 광고 애셋 보고서를 직접 읽었습니다.\n"
        f"{google_folder} · 원가에 마크업 ×{cost_markup:.4f} 적용 · "
        f"캠페인 {google['source_file'].nunique()}개 파일"
    )

section(
    "3", "구글 TOP 소재 성과",
    "영상·이미지 소재만 포함하며, 텍스트 애셋은 제외했습니다.\n"
    "*매체 대시보드 데이터 기준",
    badge=f"소재 {len(google):,}개" if not google.empty else "데이터 없음",
    extra_hint=google_read_hint,
)

if google_error:
    status_row("bad", "구글 보고서를 읽지 못했습니다", google_error)
elif google.empty:
    status_row("warn", f"{month}월 구글 소재 데이터가 없습니다",
        "폴더에 해당 월 '애셋 세부정보 보고서' CSV가 있어야 합니다. "
        "사이드바에서 폴더 경로를 확인해 주세요.",
    )
else:
    failures = google_all.attrs.get("failures") or []
    if failures:
        status_row("warn", f"읽지 못한 파일 {len(failures)}개", " / ".join(failures[:3]))

    g_controls = st.columns([2, 1])
    g_rank_metric = g_controls[0].selectbox(
        "정렬 기준", list(GOOGLE_RANK_METRICS),
        format_func=lambda m: GOOGLE_RANK_METRICS[m], key="google_rank",
    )
    g_top_n = g_controls[1].number_input(
        "표시 개수", min_value=5, max_value=50, value=10, step=5, key="google_top_n"
    )

    for g_os in [o for o in ("AOS", "iOS") if o in set(google["os"].dropna())]:
        g_os_scope = google[google["os"] == g_os]
        g_top = aggregate_google(
            g_os_scope,
            ["asset", "asset_type", "title_kr", "objective", "direction", "rating"],
        )
        g_top = g_top[g_top["cost"].fillna(0) >= min_cost]
        if g_top.empty:
            status_row("warn", g_os, "조건에 맞는 소재가 없습니다.")
            continue

        g_top = g_top.sort_values(g_rank_metric, ascending=False).head(int(g_top_n))
        g_top = g_top.reset_index(drop=True)
        table_title(f"{g_os} — {GOOGLE_RANK_METRICS[g_rank_metric]} 기준 TOP {int(g_top_n)}")
        render_google_table(g_top)

        g_benchmark = aggregate_google(
            g_os_scope.assign(_all=f"{g_os} 전체 평균 (벤치마크)"), ["_all"]
        ).rename(columns={"_all": "asset"})
        render_google_table(g_benchmark, highlight=False, link_column=False)

# --------------------------------------------------------------------------- 4. 소재 속성별

# 분석 축은 피벗(6번 섹션)과 같은 구분자를 쓴다 — 화면마다 이름이 다르면 헷갈린다.
ATTRIBUTES = {
    "creative_type": "Creative Type",
    "format": "Creative Format",
    "size": "Dimension",
    "orientation": "사이즈 방향",
    "extra_info_tag": "Extra Info (태그별)",
    "producer_group": "제작 주체",
    "usp": "USP",
}

def override_options(frame: pd.DataFrame) -> dict[str, list[str]]:
    """수동 분류 드롭다운의 후보 값 — 이번 달 데이터에 실제로 존재하는 분류값만 모은다.

    자유 입력이면 `Highlight`/`highlight`처럼 오타 하나로 없던 분류가 새로 생겨 집계가
    갈라진다. 기존 어휘에서 고르게 하는 게 이 화면의 핵심이다. Creative Format만은
    VID/IMG/GIF 세 값으로 고정된 규격이라 데이터와 무관하게 박아 둔다.
    """
    # 시트에서 온 결측이 문자열 그대로 굳은 값들 — 실제로 producer_group에 "nan"이 섞여 있어
    # 그냥 두면 분류 후보로 노출된다(고르면 그 자체가 새 분류가 되어 버린다).
    empties = {"nan", "none", "null", "na", "n/a", "-", "미분류"}

    def values(column: str) -> list[str]:
        if column not in frame.columns:
            return []
        series = frame[column].dropna().astype(str).str.strip()
        series = series[(series != "") & (~series.str.lower().isin(empties))]
        return sorted(series.unique())

    return {
        "creative_type": values("creative_type"),
        "format": ["VID", "IMG", "GIF"],
        "producer_group": values("producer_group"),
        "extra_info": values("extra_info"),
        "usp": values("usp"),
    }


def render_manual_override_panel(
    month: int, show: bool, valid_ads: set, key_prefix: str,
    options: dict[str, list[str]] | None = None,
) -> None:
    """소재명 규칙이 안 맞아 '미분류'로 빠진 실제 소재를 수동으로 분류한다.

    성과 수치는 원본 그대로 두고 분류 컬럼만 사용자가 지정한 값으로 덮어쓴다 — 구글의
    '-' 자리표시자(애초에 소재 단위 태깅이 없음)와는 다른, 진짜 소재의 명명 규칙 예외
    처리다. 저장소는 4번·5번 양쪽에서 공유하지만, 언제 보여줄지는 호출부가 정한다 —
    4번은 보기 모드에서도 항상 보이고(데이터 보정이지 리포트 편집이 아니라서), 5번은
    블록마다 편집 모드에서만 보인다.
    """
    if not show:
        return

    manual = manual_overrides.load(month)
    with st.expander(f"수동 분류 소재 ({len(manual)}개)"):
        for ad, fields in list(manual.items()):
            row = st.columns([5, 1])
            summary = " · ".join(
                f"{manual_overrides.FIELDS[k]}={v}" for k, v in fields.items() if v
            )
            row[0].caption(f"`{ad}` — {summary or '(값 없음)'}")
            if row[1].button("삭제", key=f"{key_prefix}_del_{ad}"):
                manual_overrides.remove(month, ad)
                st.rerun()

        st.caption(
            "소재명이 명명 규칙과 안 맞아 '미분류'로 빠진 실제 소재를 여기서 직접 "
            "분류합니다. 성과 수치는 그대로 두고 분류 값만 채웁니다."
        )
        pasted = st.text_input("소재명 붙여넣기", key=f"{key_prefix}_paste")
        if pasted and pasted not in valid_ads:
            st.error("이번 달 데이터에서 이 소재명을 찾을 수 없습니다. 정확히 복붙했는지 확인하세요.")
        elif pasted:
            existing = manual.get(pasted, {})
            choices = options or {}

            def pick(container, field: str, label: str, key_suffix: str, help_text=None):
                """기존 어휘 드롭다운. 비워 두면 그 필드는 덮어쓰지 않는다.

                후보에 없는 값이 정말 필요할 때를 위해 직접 입력도 허용하되(새 분류를
                만들 일이 아예 없지는 않다), 기본은 목록에서 고르는 것이다.
                """
                items = list(choices.get(field, []))
                current = existing.get(field, "")
                if current and current not in items:
                    items.insert(0, current)
                return container.selectbox(
                    label, items,
                    index=items.index(current) if current in items else None,
                    key=f"{key_prefix}_{key_suffix}",
                    placeholder="비워 두면 그대로",
                    accept_new_options=True,
                    help=help_text,
                )

            c1, c2, c3 = st.columns(3)
            creative_type = pick(c1, "creative_type", "Creative Type", "ct")
            fmt = pick(c2, "format", "Creative Format", "fmt")
            producer = pick(c3, "producer_group", "제작 주체", "pg")
            c4, c5 = st.columns(2)
            extra_info = pick(
                c4, "extra_info", "Extra Info", "ei",
                help_text="여러 태그는 `text-thumb`처럼 하이픈으로 이어 붙인 값 그대로 고릅니다.",
            )
            usp = pick(c5, "usp", "USP", "usp")

            if st.button("저장", type="primary", key=f"{key_prefix}_save"):
                manual_overrides.save(month, pasted, {
                    "creative_type": creative_type or "",
                    "format": fmt or "",
                    "producer_group": producer or "",
                    "extra_info": extra_info or "",
                    "usp": usp or "",
                })
                st.rerun()


# 드롭다운 후보는 총괄 필터가 걸리기 전의 이 달 전체(scope)에서 뽑는다 — 1번에서 Creative
# Type을 하나로 좁혀 보는 중이라고 해서 분류 후보까지 그 하나로 줄어들면 안 된다.
override_choices = override_options(scope[scope["ad"] != "-"])

section(
    "4", "소재 속성별 성과",
    "소재명 규칙(작품코드_작품명_Creative Format_제작주체_Creative Type_Dimension_USP_Extra Info)을 "
    "자동 분해해 집계합니다. 규칙에 맞지 않는 소재명은 추정하지 않고 '미분류'로 남깁니다.",
    hint=True,
)

# 분석 축과 그 축의 값 선택은 한 덩어리로 읽혀야 한다("이 축의 값을 고른다"는 관계). 테두리
# 상자 하나에 두 위젯을 나란히 담고, 소재 분류를 다루는 도구라는 점에서 결이 같은 수동 분류도
# 같은 상자 안에 붙인다. 값 선택지는 축을 고른 뒤 집계를 해야 알 수 있으므로, 컬럼만 먼저
# 만들어 두고 아래에서 계산이 끝난 뒤 가운데 칸을 채운다.
with st.container(border=True, key="attr_axis_box"):
    axis_cols = st.columns([1, 3])
    override_slot = st.container()
with axis_cols[0]:
    attribute = st.selectbox(
        "분석 축", list(ATTRIBUTES), format_func=lambda a: ATTRIBUTES[a]
    )
with override_slot:
    # 상시 필터가 아니라 예외 보정 도구라, 옆에 나란히 두면 축·값 선택과 같은 비중으로 보인다.
    # 같은 상자 안에서 한 단 아래로 내려 접어 둔다(데이터 분류 보정이므로 편집 모드와
    # 무관하게 보기 모드에서도 항상 노출한다).
    render_manual_override_panel(
        month, True, set(named_overview["ad"].unique()), key_prefix="sec4_override",
        options=override_choices,
    )

attr_scope = explode_extra_info(named_overview) if attribute == "extra_info_tag" else named_overview
attr_scope = attr_scope.copy()
attr_scope[attribute] = attr_scope[attribute].fillna("미분류").replace("", "미분류")
by_attribute = aggregate_by(attr_scope, [attribute, "media"])
by_attribute = by_attribute[by_attribute["cost"].fillna(0) >= min_cost]

# 모든 값을 한 화면에 늘어놓지 않고, 보고 싶은 값만 골라서 비교할 수 있게 한다.
attr_options = sorted(by_attribute[attribute].astype(str).unique())
with axis_cols[1]:
    attr_selection = st.multiselect(
        "값 선택 (비우면 전체)",
        attr_options,
        key=f"attr_values_{attribute}",
        placeholder="예: 6초 컷다운, SNS형만 골라서 비교",
    )

# 선택지가 고정이라 드롭다운일 이유가 없다 — 펼쳐 두면 지금 무슨 지표를 보고 있는지
# 열지 않아도 보이고, 지표를 바꿀 때 클릭이 두 번에서 한 번으로 준다.
# 소진액(cost)은 효율이 아니라 볼륨 지표라, "어디에 얼마를 썼는지"를 먼저 보고 효율로 넘어가는
# 순서에 맞춰 맨 앞에 둔다. 값은 집계 프레임의 컬럼명 그대로 쓰고 라벨만 한글로 보여준다.
compare_metric = st.segmented_control(
    "비교 지표", ["cost", "CPI", "CTR", "D0 read CVR", "D0 coin CVR", "CPC"],
    default="CPI", key="sec4_metric",
    format_func=lambda m: METRIC_LABELS.get(m, m),
) or "CPI"

if attr_selection:
    by_attribute = by_attribute[by_attribute[attribute].astype(str).isin(attr_selection)]

if attribute == "extra_info_tag":
    status_row(
        "warn", "Extra Info는 태그별로 펼쳐 봅니다",
        "`text-thumb`처럼 태그가 여러 개인 소재는 각 태그에 모두 들어갑니다. "
        "따라서 태그별 합계를 전부 더하면 전체 소진액보다 커집니다 — 태그 간 비교용입니다.",
    )

if by_attribute.empty:
    status_row("warn", "표시할 조합이 없습니다", "값 선택을 비우거나 최소 소진액 조건을 낮춰 보세요.")
else:
    chart = px.bar(
        by_attribute,
        x=attribute,
        y=compare_metric,
        color="media",
        barmode="group",
        labels={
            attribute: ATTRIBUTES[attribute], "media": "매체",
            compare_metric: METRIC_LABELS.get(compare_metric, compare_metric),
        },
        color_discrete_map=MEDIA_COLORS,
        color_discrete_sequence=[MEDIA_COLOR_FALLBACK],
    )
    chart.update_layout(
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        margin=dict(l=10, r=10, t=30, b=10), height=380,
        font=dict(size=12), legend_title_text="",
        yaxis=dict(gridcolor="#eef1f3"), xaxis=dict(showgrid=False),
        font_family="Pretendard, sans-serif",
    )
    if compare_metric in ("CTR", "D0 read CVR", "D0 coin CVR"):
        chart.update_layout(yaxis_tickformat=".1%")
    elif compare_metric == "cost":
        # 금액은 자릿수가 커서 기본 지수 표기(30k)로는 규모 감이 안 온다 — 원화 표기로 고정한다.
        chart.update_layout(yaxis_tickprefix="₩", yaxis_tickformat=",.0f")
    st.plotly_chart(chart, width="stretch")
    render_table(
        by_attribute.rename(columns={attribute: ATTRIBUTES[attribute]}),
        color_columns=["CPI"], highlight_key=f"sec4_{attribute}_{compare_metric}", month=month,
    )

# ------------------------------------------------- 5. 소재 분석 (블록 목록)


def clear_editor_state(block_id: str) -> None:
    """편집을 끝낸(또는 놓친) 블록의 임시 위젯 상태를 비운다.

    조건 행(cond_*) 상태는 위젯이라 잠금을 놓아도 세션에 그대로 남는다. 그냥 두면 취소한
    선택이 다음에 블록을 열 때 되살아나고, 그대로 저장하면 실제로 반영돼 버린다.
    """
    prefixes = (f"cond_rows_{block_id}", f"cond_field_{block_id}_",
                f"cond_values_{block_id}_", f"cond_panel_{block_id}",
                f"title_{block_id}", f"comment_{block_id}", f"next_step_md_{block_id}")
    for key in [k for k in list(st.session_state) if k.startswith(prefixes)]:
        del st.session_state[key]
    st.session_state.pop(f"held_{block_id}", None)


def editor_taken_over(block_id: str, month: int) -> bool:
    """내가 잡고 있던 잠금을 남이 가져갔는지."""
    owner = st.session_state["editor_token"]
    if not st.session_state.get(f"held_{block_id}"):
        return False
    return locks.status(f"block:{block_id}", month, owner).state != "mine"


def lock_gate(
    block_id: str, month: int, title: str, edit_mode: bool, info: str | None = None
) -> bool:
    """블록 헤더와 잠금 조작을 그리고, 편집 UI를 그려도 되는지 돌려준다.

    info는 잠금 상태와 무관하게 제목 옆에 항상 보여줄 중립 배지(예: 조건 요약)다.

    edit_mode가 꺼져 있으면 이 블록의 잠금이 내 것이든 남의 것이든 상관없이
    순수 리포트 헤더만 그리고 False를 돌려준다 — 배지·저장 버튼·잠금 해제 UI를
    전부 숨기고, touch도 호출하지 않는다(편집 모드를 끄고 나간 사람의 잠금은
    스스로 만료되도록 그냥 둔다).
    """
    owner = st.session_state["editor_token"]
    kind = f"block:{block_id}"

    if not edit_mode:
        note_header(title, info=info)
        return False

    state = locks.status(kind, month, owner)

    if state.state == "mine":
        # 이 세션이 이 블록을 잡고 있다는 사실을 남겨둔다 — 나중에 잠금을 빼앗겼을 때
        # '원래 편집 중이던 사람'인지 구분하는 유일한 근거다.
        st.session_state[f"held_{block_id}"] = True
        note_header(title, ("mine", "편집 중 · 나"), info=info)
        # 완료 버튼은 폼 맨 아래(저장 버튼과 합쳐서 하나)에 둔다 — 예전엔 여기 위에서
        # "작성 완료"를 먼저 누르면 저장 없이 잠금만 풀려서, 폼 아래 "저장"을 안 누르고
        # 나가면 방금 쓴 내용이 그대로 날아갔다. 완료 = 저장이 되도록 폼 쪽에서 처리한다.
        locks.touch(kind, month, owner)
        return True

    if st.session_state.get(f"held_{block_id}"):
        # 잠금을 빼앗긴 경우. 여기서 False를 돌려주면 작성 중이던 에디터가 통째로 사라져
        # 입력하던 글이 아무 말 없이 날아간다 — 저장만 막고 화면은 그대로 둔다.
        note_header(title, ("other", "다른 사람이 이어받음"), info=info)
        st.error("다른 사람이 이 블록을 이어받았습니다. 작성 중이던 내용을 복사해 두세요.")
        if st.button("확인했습니다", key=f"ack_{block_id}"):
            clear_editor_state(block_id)
            st.rerun()
        return True

    if state.state == "other":
        note_header(
            title, ("other", f"다른 사람이 편집 중 · {int(state.held_minutes)}분째"), info=info
        )
        if state.held_minutes >= locks.STEAL_AFTER_MINUTES:
            if st.session_state.get(f"steal_{block_id}"):
                st.warning("다른 사람이 작성 중일 수 있습니다. 그래도 잠금을 해제할까요?")
                yes, no = st.columns([1, 4])
                if yes.button("해제", key=f"steal_yes_{block_id}"):
                    locks.force_release(kind, month)
                    st.session_state[f"steal_{block_id}"] = False
                    st.rerun()
                if no.button("취소", key=f"steal_no_{block_id}"):
                    st.session_state[f"steal_{block_id}"] = False
                    st.rerun()
            elif st.button("잠금 해제", key=f"steal_btn_{block_id}"):
                st.session_state[f"steal_{block_id}"] = True
                st.rerun()
        else:
            st.caption("편집이 끝나면 자동으로 열립니다. 15분간 저장이 없으면 잠금이 스스로 풀립니다.")
        return False

    note_header(title, info=info)
    return False


def block_menu(slot: str, block_id: str, month: int, owner: str) -> None:
    """블록 하나의 조작 버튼을 한 줄에 그린다.

    편집 모드 자체가 사이드바 스위치 뒤에 숨어 있으므로, 이미 편집 모드에 들어온 다음에
    또 팝오버를 열어야 하는 건 불필요한 한 단계였다 — 버튼을 그대로 늘어놓는다.
    """
    confirm_key = f"confirm_del_{block_id}"
    if st.session_state.get(confirm_key):
        cols = st.columns([2, 1, 1, 4])
        cols[0].caption("이 블록을 삭제할까요? 코멘트·조건이 모두 사라집니다.")
        if cols[1].button("삭제", key=f"del_yes_{block_id}"):
            locks.force_release(f"block:{block_id}", month)
            report_blocks.mutate(month, lambda d: report_blocks.remove_block(d, slot, block_id))
            st.session_state.pop(confirm_key, None)
            st.rerun()
        if cols[2].button("취소", key=f"del_no_{block_id}"):
            st.session_state[confirm_key] = False
            st.rerun()
        return

    cols = st.columns([1, 1, 1, 1, 4])
    if cols[0].button("편집하기", key=f"edit_{block_id}"):
        if locks.acquire(f"block:{block_id}", month, owner):
            st.rerun()
        else:
            st.error("다른 사람이 방금 편집을 시작했습니다.")
    if cols[1].button("▲", key=f"up_{block_id}", help="위로"):
        report_blocks.mutate(month, lambda d: report_blocks.move_block(d, slot, block_id, -1))
        st.rerun()
    if cols[2].button("▼", key=f"down_{block_id}", help="아래로"):
        report_blocks.mutate(month, lambda d: report_blocks.move_block(d, slot, block_id, 1))
        st.rerun()
    if cols[3].button("삭제", key=f"del_{block_id}"):
        st.session_state[confirm_key] = True
        st.rerun()


def insert_block_row(slot: str, position: int, block_type: str, default_title: str) -> None:
    """블록과 블록 사이에 얇은 '+' 줄을 둔다 — 항상 맨 끝이 아니라 원하는 자리에 끼워 넣는다."""
    label = "＋ 분석 블록 추가" if block_type == "creative_query" else "＋ 노트 블록 추가"
    with st.container(key=f"insert_{slot}_{position}"):
        if st.button(label, key=f"insert_btn_{slot}_{position}",
                     help="이 자리에 블록을 추가합니다", width="stretch"):
            report_blocks.mutate(month, lambda d: report_blocks.add_block(
                d, slot, block_type, default_title, position=position))
            st.rerun()


def condition_editor(block_id: str, conditions: dict, show_table: bool) -> tuple[dict, bool]:
    """조건 행 UI + 실시간 결과 요약 + 표 노출 여부. (조건, 표 노출 여부)를 돌려준다.

    이 조건이 "무엇에 걸리는지" 편집 중에 바로 보이지 않는다는 피드백을 받아, 조건과
    결과 요약(소재 수·소진액)과 표 노출 토글을 한 패널 안에 묶는다. 표를 꺼 두면 이 조건이
    아직 리포트에 반영되지 않는다는 걸 알 수 있게 흐린 안내를 덧붙인다.

    블록의 저장된 조건에서 시작하고, 위젯 키에는 반드시 block_id를 섞어 블록 간
    상태가 섞이지 않게 한다.
    """
    rows_key = f"cond_rows_{block_id}"
    if rows_key not in st.session_state:
        st.session_state[rows_key] = list(conditions.keys()) or [list(PIVOT_FIELDS)[0]]

    rows: list[str] = list(st.session_state[rows_key])

    # Extra Info는 태그 단위로 펼쳐야 값 선택지가 태그로 나온다. 필요할 때만 한 번 만든다.
    exploded: pd.DataFrame | None = None

    def field_frame(field: str) -> pd.DataFrame:
        nonlocal exploded
        if field != "extra_info_tag":
            return overview
        if exploded is None:
            exploded = explode_extra_info(overview)
        return exploded

    result: dict[str, list[str]] = {}
    active_rows: list[str] = []
    dropped: int | None = None

    with st.container(border=True, key=f"cond_panel_{block_id}"):
        st.markdown(
            '<div class="cp-label">이 블록의 표에 걸리는 조건</div>',
            unsafe_allow_html=True,
        )
        for position, field in enumerate(rows):
            label_col, value_col, drop_col = st.columns(
                [1.5, 4.2, 0.5], vertical_alignment="center"
            )
            # 같은 구분자를 두 줄에 걸 이유가 없으니 다른 줄이 쓰는 것은 선택지에서 뺀다
            taken = set(rows) - {field}
            available = [f for f in PIVOT_FIELDS if f not in taken]
            # 선택이 바뀌어도 rerun을 부르지 않는다 — 위젯 상태와 되받아치며 무한 루프가 난다
            picked = label_col.selectbox(
                "구분자", available,
                index=available.index(field),
                format_func=lambda f: PIVOT_FIELDS[f],
                key=f"cond_field_{block_id}_{position}",
                label_visibility="collapsed",
            )
            active_rows.append(picked)

            options = sorted(
                field_frame(picked)[picked]
                .dropna().astype(str).replace("", pd.NA).dropna().unique()
            )
            defaults = [v for v in conditions.get(field, []) if v in options]
            chosen = value_col.multiselect(
                PIVOT_FIELDS[picked], options,
                default=defaults or None,
                key=f"cond_values_{block_id}_{picked}",
                placeholder=f"{PIVOT_FIELDS[picked]} 전체",
                label_visibility="collapsed",
            )
            if chosen:
                result[picked] = chosen

            if drop_col.button("✕", key=f"cond_drop_{block_id}_{position}", help="이 조건 삭제"):
                dropped = position

        add_col = st.columns([3, 1], vertical_alignment="center")[0]
        unused = [f for f in PIVOT_FIELDS if f not in active_rows]
        add_clicked = add_col.button(
            "+ 조건 추가", key=f"cond_add_{block_id}", disabled=not unused
        )

        if dropped is not None:
            active_rows.pop(dropped)
            # 줄이 당겨지면 뒤쪽 구분자 위젯 상태가 옛 값을 물고 있으므로 같이 비운다
            for index in range(len(rows)):
                st.session_state.pop(f"cond_field_{block_id}_{index}", None)
            st.session_state[rows_key] = active_rows
            st.rerun()
        if add_clicked:
            st.session_state[rows_key] = active_rows + [unused[0]]
            st.rerun()

        st.session_state[rows_key] = active_rows

        # 실시간 요약 — 저장 전에도 "지금 조건이 몇 개·얼마를 걸러내는지"가 바로 보여야
        # 조건이 표에 걸리는 필터라는 게 체감된다. 결과 계산은 render_query_result와
        # 완전히 같은 match_conditions()를 써서 표와 어긋나지 않게 한다.
        _, live_count = match_conditions(result)
        st.markdown(
            f'<div class="cp-summary">이 조건에 맞는 소재 <b>{live_count:,}개</b></div>',
            unsafe_allow_html=True,
        )

        # 조건을 보다가 미분류로 빠진 소재를 발견하면 그 자리에서 바로 고칠 수 있게, 이 블록의
        # 조건 패널 안에 둔다. 저장소는 이 달 전체가 공유하므로(같은 소재는 어느 블록에서 고쳐도
        # 동일 반영) 여러 블록에 나눠 걸어도 값이 어긋나지 않는다.
        render_manual_override_panel(
            month, True, set(named_overview["ad"].unique()),
            key_prefix=f"sec5_override_{block_id}",
            options=override_choices,
        )

        show_table = st.checkbox(
            "이 표를 리포트에 함께 싣기", value=show_table, key=f"showtbl_{block_id}",
        )
        if not show_table:
            st.markdown(
                '<div class="cp-hint">표를 꺼 두면 위 조건은 저장해도 리포트에 나오지 않고, '
                '아래 코멘트만 실립니다.</div>',
                unsafe_allow_html=True,
            )

    return result, show_table


def match_conditions(conditions: dict) -> tuple[pd.DataFrame, int]:
    """조건에 맞는 소재를 찾는다. (매칭된 원본 스코프, 소재 수)를 돌려준다.

    condition_editor의 실시간 요약과 render_query_result의 표가 같은 매칭 결과를 써야
    "이 조건이 무엇에 걸리는지"가 편집 중에도 어긋나지 않는다 — 로직을 한 곳에 둔다.
    """
    # 소재명 규칙 파싱이 있어야 조건이 의미가 있다 — 구글은 소재 단위 태깅이 없어 제외한다.
    # 조건 매칭도 태그를 쓰면 펼친 프레임에서 해야 한다.
    base = explode_extra_info(named_overview) if "extra_info_tag" in conditions else named_overview

    matched = base
    for field, values in conditions.items():
        matched = matched[matched[field].astype(str).isin(values)]
    matched_ads = matched["ad"].unique()

    # 집계는 펼치기 전 원본에서 한다 — 태그를 여러 개 고르면 펼친 프레임에선 같은 소재가 겹친다.
    scope_of_match = overview[overview["ad"].isin(matched_ads)]
    return scope_of_match, len(matched_ads)


def condition_label(conditions: dict) -> str | None:
    """조건을 'Extra Info = mix' 같은 한 줄로 요약한다. 조건이 없으면 None(배지 자체를 숨긴다).

    블록 헤더 옆 배지와 조건 편집 패널 양쪽에서 같은 문구를 써야 어긋나지 않는다.
    """
    if not conditions:
        return None
    return " · ".join(
        f"{PIVOT_FIELDS[f]} = {', '.join(map(str, v))}" for f, v in conditions.items()
    )


def render_query_result(conditions: dict, month: int, highlight_key: str) -> None:
    """조건에 맞는 소재를 집계해 KPI + 표로 보여준다."""
    scope_of_match, matched_count = match_conditions(conditions)
    detail = aggregate_by(scope_of_match, ["ad", "media"]).sort_values("cost", ascending=False)

    if detail.empty:
        status_row("warn", "조건에 맞는 소재가 없습니다", "조건을 완화해 보세요.")
        return

    summary = aggregate_by(scope_of_match.assign(_all="합계"), ["_all"]).iloc[0]
    # 조건 요약은 이제 블록 헤더 옆 배지로 옮겨서 여기서는 다시 찍지 않는다.
    kpi_cards([
        {"label": "소재 수", "value": f"{matched_count:,}개",
         "sub": "조건에 맞는 소재", "primary": True},
        {"label": "소진액", "value": f"₩{summary['cost']:,.0f}", "sub": "마크업 포함"},
        {"label": "CTR", "value": f"{summary['CTR']:.2%}", "sub": "클릭 ÷ 노출"},
        {"label": "인스톨", "value": f"{summary['total install']:,.0f}", "sub": "Total install"},
        {"label": "CPI", "value": f"₩{summary['CPI']:,.0f}", "sub": "소진 ÷ 인스톨"},
        {"label": "D0 Read CVR", "value": f"{summary['D0 read CVR']:.2%}",
         "sub": "D0 Read ÷ 인스톨"},
    ])
    render_table(
        detail[[c for c in DISPLAY_COLUMNS if c in detail.columns]],
        color_columns=["CPI"], highlight_key=highlight_key, month=month,
    )


def render_query_block(block: dict, month: int, edit_mode: bool) -> None:
    block_id = block["id"]
    owner = st.session_state["editor_token"]
    # 저장된 조건을 제목 옆 배지로 보여준다 — 표 위 캡션에 있을 땐 눈에 잘 안 띄었다.
    saved_conditions = dict(block.get("conditions") or {})
    editing = lock_gate(
        block_id, month, block.get("title") or "제목 없는 블록", edit_mode,
        info=condition_label(saved_conditions),
    )

    if edit_mode and not editing:
        block_menu(report_blocks.SLOT_ANALYSIS, block_id, month, owner)

    conditions = saved_conditions
    show_table = bool(block.get("show_table", True))

    if editing:
        title_value = st.text_input("블록 제목", value=block.get("title", ""),
                                    key=f"title_{block_id}")
        conditions, show_table = condition_editor(block_id, conditions, show_table)
        comment = st_quill(
            value=block.get("comment", ""), html=True,
            toolbar=[
                ["bold", "italic", "underline", "strike"],
                [{"header": [2, 3, False]}],
                [{"list": "ordered"}, {"list": "bullet"}],
                [{"color": []}, {"background": []}],
                ["link", "blockquote", "code-block"],
                ["clean"],
            ],
            key=f"comment_{block_id}",
        )
        taken_over = editor_taken_over(block_id, month)
        # 버튼을 하나로 합친다 — 예전엔 "작성 완료"(잠금만 해제)와 "저장"(내용만 저장)이
        # 따로 있어서, 완료를 먼저 누르면 저장 안 된 글이 그대로 날아갔다. 완료는 항상 저장까지
        # 같이 한다.
        if st.button("완료", type="primary", key=f"save_{block_id}", disabled=taken_over):
            if locks.status(f"block:{block_id}", month, owner).state != "mine":
                st.error("다른 사람이 이 블록을 이어받았습니다. 내용을 복사해 두고 다시 편집하세요.")
            else:
                # 화면이 들고 있는 스냅샷이 아니라 디스크의 최신 상태에 이 블록만 덮어쓴다
                report_blocks.mutate(month, lambda d: report_blocks.update_block(
                    d, report_blocks.SLOT_ANALYSIS, block_id,
                    title=title_value, conditions=conditions,
                    show_table=show_table, comment=comment or "",
                ))
                locks.release(f"block:{block_id}", month, owner)
                clear_editor_state(block_id)
                st.rerun()

    # 편집 중에는 저장된 값이 아니라 화면의 체크박스 값을 따른다 — 안 그러면 체크를 껐는데도
    # 저장하기 전까지 표가 그대로 남아 반응이 없는 것처럼 보인다.
    if show_table:
        render_query_result(conditions, month, f"sec5_{block_id}")

    if block.get("comment"):
        st.markdown(
            f'<div class="note-body">{to_preview_html(block["comment"])}</div>',
            unsafe_allow_html=True,
        )


page_blocks = report_blocks.load_blocks(month)
# 파일이 깨져 있었다면 지우지 않고 옆에 치워둔 상태다. 조용히 빈 화면을 보여주면 사용자가
# 눈치채지 못한 채 새로 저장해서 복구 기회를 날린다.
_corrupt = report_blocks.pop_corruption(month)
analysis_blocks = page_blocks[report_blocks.SLOT_ANALYSIS]

# 편집 상태는 블록마다 자기 헤더에 이미 표시되므로(편집 중 · 나 / 다른 사람이 편집 중),
# 섹션 배지에 또 요약하지 않는다 — 중복이다.
section("5", "소재 분석")

if _corrupt:
    st.error(
        f"{month}월 블록 파일이 손상되어 읽지 못했습니다. 원본은 `{_corrupt}` 로 옮겨 두었으니 "
        "복구가 필요하면 이 파일을 확인해 주세요."
    )

if not analysis_blocks:
    st.caption("아직 분석 블록이 없습니다.")

# 블록 사이사이(맨 앞·맨 뒤 포함)에 얇은 "+" 줄을 둔다 — 노션처럼 원하는 자리에 바로
# 끼워 넣을 수 있게. 편집 모드가 꺼져 있으면 고객사 화면이라 아예 그리지 않는다.
if edit_mode:
    insert_block_row(report_blocks.SLOT_ANALYSIS, 0, "creative_query", "새 분석 블록")
for index, block in enumerate(list(analysis_blocks)):
    render_query_block(block, month, edit_mode)
    if edit_mode:
        insert_block_row(report_blocks.SLOT_ANALYSIS, index + 1, "creative_query", "새 분석 블록")

# --------------------------------------------------------------------------- 6. 작품별

section("6", "작품별 성과")

# 작품별 성과는 "이 작품이 iOS에서 잘 도는지 / 메타에서 잘 도는지"를 자주 따로 봐야 해서, 상단 총괄
# 필터와 별개로 이 섹션 전용 OS·매체 필터를 둔다(비워두면 전체).
title_controls = st.columns(2)
title_os = title_controls[0].multiselect(
    "OS", sorted(overview["os"].dropna().unique()), key="title_os", placeholder="전체",
)
title_media = title_controls[1].multiselect(
    "매체", sorted(overview["media"].dropna().unique()), key="title_media", placeholder="전체",
)

title_scope = overview
if title_os:
    title_scope = title_scope[title_scope["os"].isin(title_os)]
if title_media:
    title_scope = title_scope[title_scope["media"].isin(title_media)]

if title_scope.empty:
    status_row("warn", "선택한 OS·매체 조건에 맞는 작품 데이터가 없습니다", "필터를 완화해 주세요.")
else:
    by_title = aggregate_by(title_scope, ["title_kr"])
    by_title = by_title[by_title["cost"].fillna(0) >= min_cost].head(20)
    scope_label = " · ".join(
        [", ".join(title_os) if title_os else "전체 OS",
         ", ".join(title_media) if title_media else "전체 매체"]
    )
    st.caption(f"{scope_label} · 상위 {len(by_title)}개 작품")
    render_table(
        by_title.rename(columns={"title_kr": "작품"}),
        color_columns=["CPI"], highlight_key="sec6_by_title", month=month,
    )

# --------------------------------------------------------------------------- 7. NEXT STEP


def render_note_block(block: dict, month: int, edit_mode: bool) -> None:
    """자유 노트 블록 — 5번 분석 블록과 같은 잠금·조작 UI를 두르고, 본문은 기존 NEXT STEP의
    에디터/이미지/표 UI를 그대로 옮긴다. 위젯 키는 전부 block_id를 섞어 블록끼리 상태가
    안 섞이게 한다.
    """
    block_id = block["id"]
    owner = st.session_state["editor_token"]
    editing = lock_gate(block_id, month, block.get("title") or "노트", edit_mode)

    if edit_mode and not editing:
        block_menu(report_blocks.SLOT_NEXT_STEP, block_id, month, owner)

    if editing:
        # 업로더·텍스트영역은 rerun으로 비워지지 않는다. 저장에 성공할 때마다 키의 nonce를 올려
        # 새 위젯으로 갈아끼워야, 같은 이미지·표가 저장할 때마다 다시 append되지 않는다.
        nonce = int(st.session_state.get(f"attach_nonce_{block_id}", 0))
        title_value = st.text_input("블록 제목", value=block.get("title", ""),
                                    key=f"title_{block_id}")

        editor_col, side_col = st.columns([2.1, 1], gap="large")

        with editor_col:
            st.markdown('<div class="ns-label">본문</div>', unsafe_allow_html=True)
            draft_markdown = st_quill(
                value=block.get("comment", ""),
                html=True,
                toolbar=[
                    ["bold", "italic", "underline", "strike"],
                    [{"header": [2, 3, False]}],
                    [{"list": "ordered"}, {"list": "bullet"}],
                    [{"color": []}, {"background": []}],
                    ["link", "blockquote", "code-block"],
                    ["clean"],
                ],
                key=f"next_step_md_{block_id}",
            )

            # 표 붙여넣기는 '첨부' 레일 안에 있으면 이미지 업로드와 헷갈린다 — 본문 아래로 뺀다
            st.markdown('<div class="ns-label">표 붙여넣기</div>', unsafe_allow_html=True)
            pasted = st.text_area(
                "표 붙여넣기",
                height=96,
                key=f"next_step_tbl_{block_id}_{nonce}",
                placeholder="엑셀·시트에서 표를 복사해 그대로 붙여넣으세요. 첫 줄은 헤더로 봅니다.",
                label_visibility="collapsed",
                help="첫 줄을 헤더로 봅니다. 탭·쉼표 구분을 자동으로 가려냅니다.",
            )

        with side_col:
            st.markdown('<div class="ns-label">레퍼런스 이미지</div>', unsafe_allow_html=True)
            with st.container(border=True):
                uploaded = st.file_uploader(
                    "레퍼런스 이미지",
                    type=["png", "jpg", "jpeg", "gif", "webp"],
                    accept_multiple_files=True,
                    key=f"next_step_img_{block_id}_{nonce}",
                    label_visibility="collapsed",
                )
                image_max_height = st.slider(
                    "이미지 최대 높이",
                    min_value=200, max_value=900,
                    value=int(block.get("image_max_height") or DEFAULT_IMAGE_MAX_HEIGHT),
                    step=20, key=f"next_step_imgh_{block_id}",
                    help="세로로 긴 이미지의 높이를 제한합니다. 가로로 긴 이미지는 폭을 다 씁니다.",
                )

            taken_over = editor_taken_over(block_id, month)
            # 버튼 하나로 합친다 — "저장"과 "작성 완료"가 따로 있으면 완료를 먼저 눌러
            # 저장 안 된 글이 날아가기 쉽다. 완료는 항상 저장부터 하고 잠금을 놓는다.
            if st.button("완료", type="primary", key=f"next_step_save_{block_id}",
                         width="stretch", disabled=taken_over):
                if locks.status(f"block:{block_id}", month, owner).state != "mine":
                    st.error("다른 사람이 이 블록을 이어받았습니다. 내용을 복사해 두고 다시 편집하세요.")
                else:
                    images = list(block.get("images", []))
                    for item in uploaded or []:
                        images.append(save_image(month, item.name, item.getvalue()))

                    tables = list(block.get("tables", []))
                    if pasted and pasted.strip():
                        tables.append(pasted)

                    report_blocks.mutate(month, lambda d: report_blocks.update_block(
                        d, report_blocks.SLOT_NEXT_STEP, block_id,
                        title=title_value, comment=draft_markdown or "",
                        images=images, tables=tables,
                        image_max_height=image_max_height,
                    ))
                    st.session_state.pop(f"attach_nonce_{block_id}", None)
                    locks.release(f"block:{block_id}", month, owner)
                    clear_editor_state(block_id)
                    st.rerun()

            attachments = list(block.get("images", [])) + list(block.get("tables", []))
            if attachments:
                st.markdown(
                    f'<div class="ns-label">첨부된 항목 {len(attachments)}개</div>',
                    unsafe_allow_html=True,
                )
                with st.container(border=True):
                    for stored in list(block.get("images", [])):
                        thumb, label, action = st.columns(
                            [1, 2.9, 1.6], vertical_alignment="center"
                        )
                        uri = image_data_uri(stored)
                        if uri:
                            thumb.markdown(
                                f'<img src="{uri}" class="ns-thumb">', unsafe_allow_html=True
                            )
                        # 저장할 때 붙인 접두사(월_타임스탬프_)를 떼고 원래 파일명만 보여준다
                        label.markdown(
                            f'<div class="ns-att">{stored.split("_", 2)[-1]}</div>',
                            unsafe_allow_html=True,
                        )
                        if action.button("삭제", key=f"del_img_{block_id}_{stored}",
                                         width="stretch"):
                            delete_image(stored)
                            remaining_images = [i for i in block["images"] if i != stored]
                            report_blocks.mutate(
                                month, lambda d: report_blocks.update_block(
                                    d, report_blocks.SLOT_NEXT_STEP, block_id,
                                    images=remaining_images,
                                ))
                            st.rerun()

                    for index in range(len(block.get("tables", []))):
                        label, action = st.columns([3.9, 1.6], vertical_alignment="center")
                        label.markdown(
                            f'<div class="ns-att">표 {index + 1}</div>', unsafe_allow_html=True
                        )
                        if action.button("삭제", key=f"del_tbl_{block_id}_{index}",
                                         width="stretch"):
                            remaining = [t for i, t in enumerate(block["tables"]) if i != index]
                            report_blocks.mutate(
                                month, lambda d: report_blocks.update_block(
                                    d, report_blocks.SLOT_NEXT_STEP, block_id,
                                    tables=remaining,
                                ))
                            st.rerun()
    else:
        if block.get("comment"):
            # 에디터가 HTML을 돌려준다. 예전에 저장한 마크다운도 같은 호출로 문제없이 렌더된다.
            # note-body로 감싸서 줄간격·목록 여백을 리포트 톤에 맞춘다(Quill 기본값은 너무 성기다).
            st.markdown(
                f'<div class="note-body">{to_preview_html(block["comment"])}</div>',
                unsafe_allow_html=True,
            )
        else:
            status_row("neutral", "아직 작성된 내용이 없습니다", "편집 모드에서 입력한 뒤 저장하세요.")

        # 이미지는 st.image 대신 HTML로 넣는다 — 그래야 '높이 상한' CSS를 걸 수 있다.
        # (st.image의 width는 가로로 긴 이미지까지 좁혀버린다)
        max_height = int(block.get("image_max_height") or DEFAULT_IMAGE_MAX_HEIGHT)
        for stored in block.get("images", []):
            uri = image_data_uri(stored)
            if uri:
                # 이미지는 코멘트 본문과 달리 왼쪽 라인·배경을 두르지 않는다 — 첨부마다
                # 초록 바가 반복되면 리포트가 시끄러워진다.
                st.markdown(
                    f'<div class="note-figure">'
                    f'<img src="{uri}" style="max-height:{max_height}px;width:auto;">'
                    f"</div>",
                    unsafe_allow_html=True,
                )

        for raw_table in block.get("tables", []):
            table = parse_pasted_table(raw_table)
            if not table.empty:
                st.dataframe(table, width="stretch", hide_index=True)


next_step_blocks = page_blocks[report_blocks.SLOT_NEXT_STEP]

section("7", "NEXT STEP")
if not next_step_blocks:
    st.caption("아직 작성된 내용이 없습니다.")

if edit_mode:
    insert_block_row(report_blocks.SLOT_NEXT_STEP, 0, "note", "다음 달 액션")
for index, block in enumerate(list(next_step_blocks)):
    render_note_block(block, month, edit_mode)
    if edit_mode:
        insert_block_row(report_blocks.SLOT_NEXT_STEP, index + 1, "note", "다음 달 액션")

footnote(
    "지표 정확도 — 소진액·노출·클릭·설치·열람·코인은 Media_RAW 원본 합계(정확). "
    "CTR/CPC/CPI/CVR은 그 합계에서 계산한 값(정확). "
    "기존 시트 피벗의 'D0 read CVR' 값과는 차이가 있을 수 있습니다 "
    "(시트 쪽 분모가 원본으로 재현되지 않음 — 분자·분모 자체는 원본과 일치)."
)
