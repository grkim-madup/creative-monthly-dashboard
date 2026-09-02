"""먼슬리 크리에이티브 성과 리포트 대시보드 (네이버웹툰-대만).

기존 구글시트 피벗 리포트를 대체한다. 원본 `Media_RAW` 탭을 읽기 전용으로 가져와
TOP 소재 / 소재 속성별 성과 / 작품별 성과를 매달 같은 절차로 재생산한다.

실행: run_creative_dashboard.bat  (localhost:8502 — ASA 대시보드 8501과 충돌 방지)
"""

from __future__ import annotations

import copy
import datetime as dt
import html
import math
from pathlib import Path
from uuid import uuid4

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import auth
import blocks as report_blocks
import drive_materials
import youtube_thumbs
import dropbox_source
import google_sheets_writer
import google_snapshot
import highlights
import locks
import overrides as manual_overrides
import prefetch
from creative_data import (
    delta_direction,
    DISPLAY_COLUMNS,
    display_columns,
    comparison_window,
    delta_label,
    relative_change,
    scope_to_day,
    add_derived_metrics,
    aggregate_by,
    aggregate_by_axis,
    chart_frame,
    compare_periods,
    dumbbell_frame,
    explode_extra_info,
    metric_benchmark,
    month_options,
    pick_best_worst,
    normalize_rows,
    pivot_frame,
    DIMENSION_COLUMNS,
    METRIC_COLUMNS,
    DEFAULT_PIVOT_ROWS,
    DEFAULT_PIVOT_VALUES,
    spend_pool,
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
from ui import (
    LOGO_PATH,
    footnote,
    inject_css,
    kpi_cards,
    note_header,
    report_header,
    report_table,
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
# 배포판이 **어느 커밋으로 떠 있는지**를 화면에서 확인할 수 있게 숨긴 마커로 내보낸다.
# 눈에 보이는 요소가 아니다(display:none). "고쳤는데 배포판이 그대로인가?"를 추측하지
# 않으려고 넣었다 — 2026-09-01에 같은 질문으로 두 번 헤맸다.
_build_file = Path(__file__).resolve().parent / "BUILD.txt"
_build = _build_file.read_text(encoding="utf-8").strip() if _build_file.exists() else "dev"
st.markdown(
    f'<span data-build="{_build}" style="display:none"></span>',
    unsafe_allow_html=True,
)

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

# 컬럼 헤더에 붙일 도움말. 헤더에 "(마크업 포함)" 같은 괄호 설명을 넣으면 그 컬럼만
# 넓어져 표 전체가 밀린다 — 물음표 아이콘으로 옮겨 커서를 올렸을 때만 보이게 한다
# (2026-08-28). column_config는 서식이 Styler보다 우선하지만, 여기서는 label/help만
# 주고 format은 건드리지 않으므로 우수/저조 행 색칠과 숫자 포맷은 그대로 유지된다.
COLUMN_HELP = {
    "소진액": "마크업 포함",
    "CPI": "소진액 ÷ 인스톨",
    "CTR": "클릭 ÷ 노출",
    "D0 Read CVR": "D0 Read ÷ 인스톨",
    "D0 Coin CVR": "D0 Coin ÷ 인스톨",
}


# 총계 표(매체 × OS 요약)의 지표 순서. st.dataframe에서 컬럼을 끌어 옮긴 순서는
# 새로고침하면 사라지므로, 화면에서 맞춰둔 순서를 여기에 고정한다(2026-08-28).
# 규칙: 식별(매체·os) → 규모(소진·노출·클릭) → 효율(CTR·CPC) → 전환 규모(설치·Read·Coin)
# → 전환 효율(CPI·CVR). 없는 컬럼은 그냥 빠진다.
SUMMARY_COLUMN_ORDER = [
    "매체", "os",
    "소진액", "노출", "클릭",
    "CTR", "CPC",
    "설치", "CPI",
    "D0 Read", "D0 Coin",
    "D0 Read CVR", "D0 Coin CVR",
    "D7 coin", "D7 coin CVR",
]


# 지표 묶음이 바뀌는 지점 — 이 컬럼 왼쪽에만 세로 구분선을 넣어 "규모"와 "효율"을
# 눈으로 가른다. 컬럼이 없으면 그냥 무시된다.
GROUP_START_COLUMNS = {"소진액", "CTR"}


def format_cell(label: str, value) -> str:
    """표 셀 하나를 문자열로. 서식은 FORMATS(한글 라벨 키까지 등록돼 있음)를 따른다.

    빈 값은 "-"로 찍는다. 예전에는 float만 검사해서 pandas의 pd.NA가 그대로 통과했고,
    pd.NA는 어떤 서식 지정자를 줘도 "<NA>"를 돌려주기 때문에 화면에 "₩<NA>"가 나왔다
    (2026-08-29 구글 표 인앱 CPA에서 발견). 스칼라면 종류를 가리지 않고 검사한다.
    """
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except (TypeError, ValueError):
        pass  # 배열 등 스칼라가 아닌 값은 아래에서 문자열로 처리한다
    fmt = FORMATS.get(label)
    if fmt:
        try:
            return fmt.format(value)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


# 가운데 정렬에서 빼는 컬럼. 소재명은 길고 앞부분(작품코드·작품명)으로 훑게 되므로
# 시작점이 고정돼야 읽힌다.
LEFT_ALIGNED_COLUMNS = {"소재명", "소재 링크"}


def column_help_config(df):
    """표의 컬럼 설정 — 전부 가운데 정렬하고, 지정된 컬럼에만 물음표 도움말을 단다.

    정렬은 컬럼마다 따로 주지 않으면 텍스트는 좌측, 숫자는 우측으로 갈려 표가 들쭉날쭉
    보인다(2026-08-28 요청). Styler의 text-align은 st.dataframe이 캔버스로 그려서
    무시되므로, column_config의 alignment가 유일한 수단이다.

    예외는 소재명이다 — 값이 길어 가운데 정렬하면 행마다 시작점이 달라져 훑기가 어렵다.
    """
    return {
        str(name): st.column_config.Column(
            str(name),
            help=COLUMN_HELP.get(str(name)),
            alignment="left" if str(name) in LEFT_ALIGNED_COLUMNS else "center",
        )
        for name in df.columns
    }


# 행 높이는 Streamlit 기본값(35px)을 쓴다. 22px까지 줄여봤지만 행이 서로 붙어
# 오히려 답답해 보인다는 피드백을 받아 되돌렸다(2026-08-28) — 밀도를 높이는 것보다
# 숨 쉴 여백이 리포트 톤에 맞다. 다시 줄이자는 이야기가 나오면 이 기록을 먼저 볼 것.
TABLE_ROW_HEIGHT = None

COLUMN_LABELS = {
    "ad": "소재명",
    "media": "매체",
    "cost": "소진액",
    "impression": "노출",
    "click": "클릭",
    "total install": "설치",
    "D0 read": "D0 Read",
    "D0 coin": "D0 Coin",
    "D0 read CVR": "D0 Read CVR",
    "D0 coin CVR": "D0 Coin CVR",
}

# 퍼센트가 아닌 값은 전부 소수점 없이. 퍼센트만 소수 2자리.
MONEY_COLUMNS = ("cost", "cost_raw", "CPC", "CPI", "인앱 CPA")
COUNT_COLUMNS = (
    "impression", "click", "total install", "D0 read", "D7 read",
    "D0 coin", "D7 coin", "in_app_action",
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
    "total install": "설치", "D0 read": "D0 Read", "D0 coin": "D0 Coin",
    "D0 read CVR": "D0 Read CVR", "D0 coin CVR": "D0 Coin CVR",
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


# 편집 모드(st.dataframe)용. 캔버스라 Styler의 border가 무시돼 배경색으로 표시할 수밖에 없다.
HIGHLIGHT_STYLE = "background-color: #ffd93d; font-weight: 700;"

# 보기 모드(HTML 표)용 — 원래 하려던 "굵은 테두리" 표시다(2026-08-29).
#
# outline이 아니라 border를 쓴다. outline은 셀마다 따로 그려져 강조 셀이 나란히 붙으면
# 경계에 선이 두 줄로 겹친다. 표가 border-collapse: collapse라 border는 맞닿은 변이
# 한 줄로 합쳐진다.
#
# 나아가 **붙어 있는 강조 셀들은 하나의 사각형으로 보여야 한다**(사용자 요청) — 칸마다
# 네모가 그려지면 무엇을 묶어서 강조했는지가 안 읽힌다. 그래서 이웃도 강조돼 있는 변은
# 아예 지운다. 지울 때는 0이 아니라 `hidden`을 쓴다: collapse 표에서 인접 셀의 1px
# 행 구분선과 충돌하면 굵은 쪽이 이기는데, `hidden`만이 그 규칙을 이기고 선을 없앤다.
HIGHLIGHT_BORDER = "2px solid #00A94C"


def highlight_cell_style(saved_cells: set, headers: list[str], position: int, column: str) -> str:
    """강조 셀 하나의 테두리 스타일. 이웃한 강조 셀과는 변을 공유해 한 덩어리로 보인다."""
    def on(row_offset: int, column_offset: int) -> bool:
        index = headers.index(column) + column_offset
        if not 0 <= index < len(headers):
            return False
        return (position + row_offset, headers[index]) in saved_cells

    sides = {
        "top": "hidden" if on(-1, 0) else HIGHLIGHT_BORDER,
        "bottom": "hidden" if on(1, 0) else HIGHLIGHT_BORDER,
        "left": "hidden" if on(0, -1) else HIGHLIGHT_BORDER,
        "right": "hidden" if on(0, 1) else HIGHLIGHT_BORDER,
    }
    parts = [f"border-{side}: {value};" for side, value in sides.items()]
    return " ".join(parts) + " font-weight: 700;"


def rerun_local() -> None:
    """가능하면 **지금 있는 fragment만** 다시 그린다(2026-08-29).

    블록 목록은 fragment로 감싸 두었는데, 그 안에서 st.rerun()을 부르면 기본값이
    "앱 전체"라 표 7개와 카드까지 통째로 다시 그려진다 — 감싼 의미가 사라진다.
    같은 함수가 fragment 밖에서도 쓰이므로(예: 사이드바 경로) 범위를 지정할 수 없는
    상황이면 종전대로 전체를 다시 그린다.
    """
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


def render_html_table(
    renamed: pd.DataFrame, color_columns: list[str], saved_cells: set,
) -> None:
    """보기 모드용 HTML 표. 히트맵과 저장된 셀 강조를 그대로 옮겨 칠한다."""
    headers = list(renamed.columns)
    rows = [
        [format_cell(name, value) for name, value in zip(headers, record)]
        for record in renamed.itertuples(index=False, name=None)
    ]

    styles: list[dict[str, str]] = [{} for _ in range(len(renamed))]
    for column in color_columns:
        if column not in renamed.columns:
            continue
        for position, style in enumerate(performance_colors(renamed[column])):
            if style:
                styles[position][column] = style
    # 저장된 강조가 히트맵을 덮는다 — 사람이 일부러 칠한 셀이 우선이다.
    # 히트맵 배경은 남기고 테두리만 얹어 "왜 칠했는지"와 "어떤 값인지"를 둘 다 보인다.
    marked = {(int(p), c) for p, c in saved_cells}
    for position, column in marked:
        if 0 <= position < len(styles) and column in headers:
            styles[position][column] = (
                styles[position].get(column, "")
                + highlight_cell_style(marked, headers, position, column)
            )

    report_table(
        rows, headers,
        left_columns=LEFT_ALIGNED_COLUMNS,
        group_starts=GROUP_START_COLUMNS,
        cell_styles=styles,
    )


def render_table(
    df: pd.DataFrame, color_columns: list[str] | None = None,
    highlight_key: str | None = None, month: int | None = None,
    column_order: list[str] | None = None,
) -> None:
    """표를 그린다. highlight_key를 주면 셀을 클릭·드래그해 그때그때 강조할 수 있다.

    st.dataframe은 캔버스라 Styler의 border는 무시하지만(실측 확인) background-color·
    font-weight는 반영된다 — "굵은 선" 대신 이 조합으로 강조한다. 강조는 월 단위로
    저장해 새로고침·재접속 후에도 남는다. 드래그로 여러 셀을 한 번에 잡을 수 있고,
    같은 범위를 다시 잡으면 취소된다.
    """
    renamed = df.rename(columns=COLUMN_LABELS)
    if column_order:
        # 지정한 순서를 먼저 놓고, 목록에 없는 컬럼은 뒤에 원래 순서로 붙인다 —
        # 새 지표가 생겼을 때 조용히 사라지지 않게 한다.
        ordered = [c for c in column_order if c in renamed.columns]
        renamed = renamed[ordered + [c for c in renamed.columns if c not in ordered]]
    colors = [COLUMN_LABELS.get(c, c) for c in (color_columns or [])]

    # 보기 모드에서는 HTML로 그린다 — st.dataframe은 헤더를 가운데 정렬하거나 굵게 할
    # 수 없고 지표 묶음 구분선도 못 넣는다(2026-08-28). 대신 셀 클릭·드래그 강조는
    # HTML에서 파이썬으로 이벤트를 돌려받을 방법이 없어 편집 모드에만 남긴다.
    # 강조는 원래 편집 모드에서만 바꿀 수 있으므로 보기 모드에서 잃는 기능은 없다.
    if not edit_mode:
        saved = highlights.load(month, highlight_key) if (highlight_key and month) else set()
        render_html_table(renamed, colors, saved)
        return

    styler = style_table(renamed, colors)

    if not highlight_key or month is None:
        st.dataframe(
            styler, width="stretch", hide_index=True, row_height=TABLE_ROW_HEIGHT,
            column_config=column_help_config(renamed),
        )
        return

    # 셀 강조 조작 방식(2026-08-29 확정)
    #
    # st.dataframe의 선택은 **이벤트가 아니라 상태**다. "같은 셀을 다시 눌러 해제"는 값이
    # 그대로라 신호가 되지 않고, 프론트엔드 그리드의 선택 상태는 session_state를 지워도
    # 남는다. 위젯 키를 매번 바꿔 강제로 새로 그려봤지만 리마운트 경합으로 더 심하게
    # 씹혔다(피드백 두 번). 그래서 선택을 곧바로 저장으로 잇지 않는다.
    #
    # 저장은 사람이 누를 때만 일어난다. 처음엔 모달(st.dialog)로 물었는데 화면을 덮고
    # 배경까지 어두워져 이 정도 조작에는 과했다 — 물음표 도움말처럼 **작게 떠 있는 칩**
    # 하나로 줄였다. 선택이 있을 때만 표 오른쪽 아래에 얹힌다.
    widget_key = f"hl_table_{highlight_key}_{month}"

    # 이 표만 fragment로 감싼다 — 셀을 눌러도 화면 전체가 아니라 이 표만 다시 돈다.
    # 바깥에서 계산해 둔 renamed/colors는 클로저로 그대로 쓴다. 데이터 자체가 바뀌는
    # 조작(월·필터·정렬 기준)은 fragment 밖이라 종전대로 전체가 다시 돈다.
    @st.fragment
    def _highlight_table() -> None:
        saved = set(highlights.load(month, highlight_key))

        def paint_selected(row):
            position = renamed.index.get_loc(row.name)
            return [
                HIGHLIGHT_STYLE if (position, col) in saved else ""
                for col in row.index
            ]

        # styler는 매번 새로 만든다 — 바깥에서 만든 것을 재사용하면 fragment가 다시 돌 때
        # 이전 강조가 겹쳐 쌓인다(Styler는 apply를 누적한다).
        painted = style_table(renamed, colors).apply(paint_selected, axis=1)
        # 표와 칩을 같은 컨테이너에 넣는다 — 이 컨테이너가 칩의 좌표 기준점이다.
        # 기준을 잡아주지 않으면 칩이 훨씬 위쪽 블록을 기준으로 삼아 엉뚱한 자리
        # (섹션 필터 옆)에 뜬다(2026-08-29 실제 발생).
        box = st.container(key=f"hlbox_{highlight_key}_{month}")
        with box:
            event = st.dataframe(
                painted, width="stretch", hide_index=True, row_height=TABLE_ROW_HEIGHT,
                column_config=column_help_config(renamed),
                on_select="rerun", selection_mode="multi-cell", key=widget_key,
            )

        picked = {tuple(cell) for cell in event["selection"]["cells"]}
        if not picked:
            return

        # 칩은 **표 제목 줄 오른쪽**에 띄운다(2026-08-29 확정).
        #
        # 처음엔 선택한 행 옆에 띄웠는데, 이 표들은 가로로 꽉 차 있어 어느 칸이든 반드시
        # 데이터를 가렸다(실제로 D7 coin CVR 값이 칩에 덮였다). 제목 줄은 늘 비어 있어
        # 무엇도 가리지 않고, 자리가 고정이라 눈으로 찾을 필요도 없다.
        chip_key = f"hlchip_{highlight_key}_{month}"

        # 선택한 칸이 이미 전부 강조돼 있으면 '해제'만, 하나도 없으면 '강조'만 띄운다.
        show_on = not picked <= saved
        show_off = bool(picked & saved)
        with box, st.container(key=chip_key):
            slots = st.columns(2 if (show_on and show_off) else 1)
            index = 0
            if show_on:
                if slots[index].button(
                    "강조", key=f"hl_on_{highlight_key}_{month}",
                    help="선택한 셀을 강조합니다",
                ):
                    ok, reason = highlights.apply(
                        month, highlight_key, add=picked
                    )
                    if not ok:
                        st.error(
                            "강조를 저장하지 못했습니다 — "
                            + google_sheets_writer.friendly_error(reason)
                        )
                    else:
                        st.rerun(scope="fragment")
                index += 1
            if show_off:
                if slots[index].button(
                    "해제", key=f"hl_off_{highlight_key}_{month}",
                    help="선택한 셀의 강조를 지웁니다",
                ):
                    ok, reason = highlights.apply(
                        month, highlight_key, remove=picked
                    )
                    if not ok:
                        st.error(
                            "강조를 저장하지 못했습니다 — "
                            + google_sheets_writer.friendly_error(reason)
                        )
                    else:
                        st.rerun(scope="fragment")

    _highlight_table()


# 행 전체 강조용 색 (기존 시트의 파랑=우수 / 빨강=저조 컨벤션)
ROW_GOOD = "background-color: #e7f9f0; color: #04703a; font-weight: 700;"
ROW_BAD = "background-color: #fdf1f1; color: #9b2c2c; font-weight: 700;"


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



def render_google_material_cards(df: pd.DataFrame) -> None:
    """구글 우수·저조 소재를 메타/틱톡과 같은 카드로 보여준다(2026-08-29).

    예전에는 여기에 "전체 평균(벤치마크)" 한 줄짜리 표가 있었다. 같은 자리에 표가 두 개
    붙어 어느 쪽이 소재이고 어느 쪽이 기준인지 헷갈렸고, 정작 **어떤 그림의 소재인지**는
    볼 수 없었다.

    구글은 Drive 파일명 매칭이 안 되지만(식별자가 URL), URL 자체에서 그림을 얻을 수 있다 —
    YouTube는 영상 ID로 썸네일 주소를 조합하고, 이미지 애셋은 URL이 곧 그림이다.
    광고주 Drive를 뒤지지 않으므로 메타/틱톡 카드보다 오히려 빠르다.
    """
    best, worst = pick_best_worst(df, [("CPI", False), ("인앱 CPA", False)])
    if not best and not worst:
        return

    # 썸네일 비율을 미리(병렬로) 확인해 둔다 — 카드마다 따로 받으면 지연이 누적된다.
    # 한 번 확인한 영상은 디스크에 남아 다음부터는 네트워크를 타지 않는다.
    youtube_thumbs.prefetch(
        [str(df.loc[index, "asset"]) for index in list(best) + list(worst)]
    )

    cards = []
    for index, column in list(best.items()) + list(worst.items()):
        row = df.loc[index]
        is_good = index in best
        state_class = "is-good" if is_good else "is-bad"
        raw_value = row.get(column)
        try:
            value_label = FORMATS.get(column, "{}").format(raw_value) if pd.notna(raw_value) else "-"
        except (TypeError, ValueError):
            value_label = str(raw_value)

        title_kr = str(row.get("title_kr") or "")
        title_html = (
            f'<div class="mat-title">{html.escape(title_kr)}</div>'
            if title_kr and title_kr != "nan" else ""
        )
        detail = " · ".join(
            str(row.get(key)) for key in ("asset_type", "objective", "direction")
            if row.get(key) and str(row.get(key)) != "nan"
        )
        meta = (
            f'<div class="mat-meta">'
            f'<div class="mat-cap"><b>{"우수" if is_good else "저조"}</b> · '
            f'{html.escape(COLUMN_LABELS.get(column, column))}</div>'
            f'<div class="mat-value">{html.escape(value_label)}</div>'
            f'{title_html}'
            f'<div class="mat-name">{html.escape(detail)}</div>'
            f'</div>'
        )
        asset = str(row.get("asset") or "")
        # 방향 컬럼은 쓰지 않는다 — iOS 보고서에는 그 컬럼이 아예 비어 있어(실측 55건 전부)
        # 세로 소재가 가로로 취급됐다. 대신 원본 비율 썸네일을 실제로 받아본 결과로 정한다.
        thumb_url, fill = youtube_thumbs.resolve(asset)
        thumb_class = "mat-thumb is-fill" if fill else "mat-thumb"
        thumb = (
            f'<img src="{html.escape(thumb_url, quote=True)}" alt="" loading="lazy">'
            if thumb_url else '<div class="mat-noimg">썸네일 없음</div>'
        )
        if asset.startswith("http"):
            cards.append(
                f'<a class="mat-card {state_class}" href="{html.escape(asset, quote=True)}" '
                f'target="_blank" rel="noopener">'
                f'<span class="mat-ext" aria-hidden="true">&#8599;</span>'
                f'<div class="{thumb_class}">{thumb}</div>{meta}</a>'
            )
        else:
            cards.append(
                f'<div class="mat-card {state_class} is-dead">'
                f'<div class="{thumb_class}">{thumb}</div>{meta}</div>'
            )

    st.markdown(f'<div class="mat-cards">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_google_table(df: pd.DataFrame, highlight: bool = True, link_column: bool = True):
    """구글 표 — 소재 식별자가 URL이라 링크 컬럼이 필요해서 별도 렌더러를 쓴다.

    강조 규칙은 매체별 TOP 소재와 동일하게 우수/저조 행 단위. 다만 구글은 Coin CVR이 없어
    CPI와 인앱 CPA를 기준으로 뽑는다.
    """
    view = df[[c for c in GOOGLE_COLUMNS if c in df.columns]].copy()
    best, worst = pick_best_worst(view, [("CPI", False), ("인앱 CPA", False)]) if highlight else ({}, {})
    # 예전에는 여기서 CTR에 100을 곱했다 — st.dataframe의 NumberColumn '%.2f%%'가 값을
    # 그대로 찍기 때문이었다. HTML 렌더는 FORMATS의 '{:.2%}'를 쓰므로 비율 그대로 둔다.
    # (곱한 채로 넘기면 3.01%가 301%로 나온다.)

    renamed = view.rename(columns={**COLUMN_LABELS, **GOOGLE_LABELS})

    # 구글 표도 다른 표와 같은 HTML 렌더를 쓴다(2026-08-29) — st.dataframe으로는 헤더를
    # 가운데 정렬하거나 굵게 할 수 없다. 이 표는 셀 클릭 강조를 쓰지 않아 잃는 게 없다.
    # 소재 식별자가 URL이라 '소재 링크'만 실제 링크로 심는다.
    headers = list(renamed.columns)
    rows = [
        [format_cell(name, value) for name, value in zip(headers, record)]
        for record in renamed.itertuples(index=False, name=None)
    ]
    row_classes = [
        "is-good" if idx in best else "is-bad" if idx in worst else ""
        for idx in renamed.index
    ]
    report_table(
        rows, headers,
        left_columns=LEFT_ALIGNED_COLUMNS,
        group_starts=GROUP_START_COLUMNS,
        row_classes=row_classes,
        link_columns={"소재 링크"} if link_column else None,
    )
    if highlight:
        note = shared_pick_note(view, best, worst, "asset", "objective")
        if note:
            status_row("info", "동일 소재 중복 선정", note)


@st.cache_data(ttl=3600, show_spinner="소재 목록 불러오는 중…")
def _drive_material_index():
    files = drive_materials.list_shared_drive_files()
    return drive_materials.build_index(files)


def _drive_material_thumbnails(specs: tuple[tuple[str, str, str], ...]) -> dict[str, str]:
    """카드에 쓸 썸네일을 만든다 — 아직 없는 것만 병렬로 받는다.

    카드마다 따로 호출하면 다운로드 지연이 그대로 누적되므로 묶어서 병렬 처리한다
    (실측 49초 → 16초). 캐시는 `drive_materials` 안에서 **소재(파일 id) 단위**로
    걸린다 — 여기에 `st.cache_data`를 묶음 단위로 걸면 정렬 기준을 바꿔 4개 중 1개만
    달라져도 4개를 전부 다시 뽑는다(실제로 그래서 느렸다).
    """
    missing = sum(1 for spec in specs if not drive_materials.has_thumbnail(spec[0]))
    if not missing:
        return drive_materials.material_thumbnails(list(specs))
    with st.spinner(f"소재 썸네일 만드는 중… ({missing}개)"):
        return drive_materials.material_thumbnails(list(specs))


# 사이드바 버튼에서 개별로 비울 수 있어야 해서, 캐시 래퍼는 사이드바보다 위에 둔다.
# 아래에 두면 버튼을 누르는 순간 아직 정의되지 않아 NameError가 난다.
@st.cache_data(show_spinner="Media_RAW 불러오는 중…")
def _load(sid: str) -> pd.DataFrame:
    return load_media_raw(sid)


@st.cache_data(show_spinner="구글 애셋 보고서 읽는 중…")
def _google(folder: str, markup: float) -> pd.DataFrame:
    return load_google_ads_folder(folder, cost_markup=markup)


def render_material_cards(df: pd.DataFrame, best: dict, worst: dict) -> None:
    """우수·저조 하이라이트 소재를 광고주 Drive의 실제 영상 링크·썸네일 카드로 잇는다.

    표(st.dataframe)는 셀 안에 커스텀 링크를 못 심으므로, 클릭해서 영상으로 넘어가는
    진입점은 표가 아니라 이 카드가 전담한다(2026-08-24 도입).
    """
    if not best and not worst:
        return
    try:
        exact, flat = _drive_material_index()
    except Exception as error:  # noqa: BLE001 - Drive 조회 실패로 리포트 전체를 막지 않는다
        status_row("warn", "Drive 소재 조회 실패", f"카드 없이 표만 표시합니다: {error}")
        return

    # 1단계: 카드에 필요한 정보와 Drive 매칭 결과를 먼저 모은다.
    entries = []
    for idx, column in list(best.items()) + list(worst.items()):
        is_good = idx in best
        raw_value = df.loc[idx, column]
        value_format = FORMATS.get(column, "{}")
        try:
            value_label = value_format.format(raw_value) if pd.notna(raw_value) else "-"
        except (TypeError, ValueError):
            value_label = str(raw_value)
        metric_label = COLUMN_LABELS.get(column, column)
        matches = drive_materials.find_matches(df.loc[idx, "ad"], exact, flat)
        title_kr = str(df.loc[idx, "title_kr"]) if "title_kr" in df.columns else ""
        entries.append({
            "ad_name": str(df.loc[idx, "ad"]),
            "title_kr": title_kr if title_kr and title_kr != "nan" else "",
            "is_good": is_good,
            "metric_label": metric_label,
            "value_label": value_label,
            "match": matches[0] if matches else None,
        })

    # 2단계: 썸네일은 카드별로 따로 받지 말고 한 번에 병렬로 만든다(지연 누적 방지).
    specs = tuple(
        (e["match"].get("id", ""), e["match"].get("name", ""),
         e["match"].get("thumbnailLink", ""))
        for e in entries if e["match"]
    )
    thumbnails = _drive_material_thumbnails(specs) if specs else {}

    cards = []
    for entry in entries:
        state_class = "is-good" if entry["is_good"] else "is-bad"
        cap_word = "우수" if entry["is_good"] else "저조"
        title_html = (
            f'<div class="mat-title">{html.escape(entry["title_kr"])}</div>'
            if entry["title_kr"] else ""
        )
        meta = (
            f'<div class="mat-meta">'
            f'<div class="mat-cap"><b>{cap_word}</b> · {html.escape(entry["metric_label"])}</div>'
            f'<div class="mat-value">{html.escape(entry["value_label"])}</div>'
            f'{title_html}'
            f'<div class="mat-name">{html.escape(entry["ad_name"])}</div>'
            f'</div>'
        )
        match = entry["match"]
        if match:
            thumb_uri = thumbnails.get(match.get("id", ""), "")
            thumb = (f'<img src="{thumb_uri}" alt="">' if thumb_uri
                     else '<div class="mat-noimg">썸네일 없음</div>')
            url = html.escape(match.get("webViewLink", ""), quote=True)
            cards.append(
                f'<a class="mat-card {state_class}" href="{url}" target="_blank" rel="noopener">'
                f'<span class="mat-ext" aria-hidden="true">&#8599;</span>'
                f'<div class="mat-thumb">{thumb}</div>{meta}</a>'
            )
        else:
            cards.append(
                f'<div class="mat-card {state_class} is-dead">'
                f'<div class="mat-thumb"><div class="mat-noimg">Drive에 없음</div></div>'
                f'{meta}</div>'
            )

    st.markdown(f'<div class="mat-cards">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_table_best_worst(
    df: pd.DataFrame, metrics: list[tuple[str, bool]], link_materials: bool = False,
    rank_metric: str | None = None,
):
    """지표별 히트맵 대신, 우수 2행·저조 2행만 행 전체를 색칠한다(시트 컨벤션).

    link_materials=True면 하이라이트된 소재를 광고주 Drive 영상과 잇는 카드를 표 아래에 붙인다
    (2번 메타/틱톡 전용 — 3번 구글은 소재 식별자가 URL이라 이 네이밍 매칭이 원리적으로 안 된다).
    """
    best, worst = pick_best_worst(df, metrics)
    # 표에는 지표 컬럼만 보여준다 — title_kr처럼 카드 전용으로 딸려온 컬럼은 여기서 뺀다
    # (소재명 컬럼과 내용이 겹쳐 표를 어지럽힌다).
    display_df = df[display_columns(df, rank_metric)]
    renamed = display_df.rename(columns=COLUMN_LABELS)

    # 이 표는 셀 클릭 강조를 쓰지 않으므로 HTML로 직접 그린다 — st.dataframe으로는
    # 헤더를 가운데 정렬하거나 굵게 할 수 없고 지표 묶음 구분선도 못 넣는다.
    headers = list(renamed.columns)
    rows = [
        [format_cell(name, value) for name, value in zip(headers, record)]
        for record in renamed.itertuples(index=False, name=None)
    ]
    row_classes = [
        "is-good" if idx in best else "is-bad" if idx in worst else ""
        for idx in renamed.index
    ]
    report_table(
        rows, headers,
        left_columns=LEFT_ALIGNED_COLUMNS,
        group_starts=GROUP_START_COLUMNS,
        row_classes=row_classes,
    )

    if link_materials:
        render_material_cards(df, best, worst)

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
        # 시트만 다시 읽는다. 예전에는 st.cache_data.clear()로 드롭박스·Drive 목록·
        # 썸네일까지 통째로 날려서, 시트만 갱신하고 싶어도 1분 넘게 기다려야 했다
        # (2026-08-28 분리). 각 소스는 자기 버튼으로만 갱신한다.
        _load.clear()
        _google.clear()
        load_media_raw(sheet_id, refresh=True)
        st.rerun()

    stamp = cache_timestamp(sheet_id)
    if stamp:
        # 배포 컨테이너(python:3.12-slim)에는 시간대 설정이 없어 서버 시각이 UTC다.
        # 라벨 없이 그대로 찍으면 한국 사용자에게는 9시간 전으로 보이고, 날짜까지
        # 하루 전으로 나온다 — 실제로 "다시 불러와도 날짜가 안 바뀐다"는 오해를 낳았다
        # (2026-09-02). KST로 환산해 찍고, 시간대와 경과 시간을 함께 보여준다.
        # 한국은 서머타임이 없어 고정 +9 오프셋이 정확하다(slim 이미지에 tzdata가
        # 없을 수 있어 zoneinfo 대신 이 방식을 쓴다).
        synced = dt.datetime.fromtimestamp(stamp, dt.timezone.utc)
        minutes = (dt.datetime.now(dt.timezone.utc) - synced).total_seconds() / 60
        if minutes < 60:
            ago = f"{int(minutes)}분 전"
        elif minutes < 60 * 48:
            ago = f"{int(minutes // 60)}시간 전"
        else:
            ago = f"{int(minutes // 1440)}일 전"
        local = synced.astimezone(dt.timezone(dt.timedelta(hours=9)))
        st.caption(f"마지막 동기화: {local:%Y-%m-%d %H:%M} KST ({ago})")


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
# 블록 저장소를 못 읽은 상태에서는 아래에서 편집 모드를 강제로 끈다(blocks_unavailable).

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
        if st.button("Dropbox에서 다시 불러오기", key="google_refetch", width="stretch"):
            st.session_state["_google_cache_bust"] = (
                st.session_state.get("_google_cache_bust", 0) + 1
            )
            _google.clear()
    st.markdown('<div class="sb-sub">소재 영상 (광고주 Drive)</div>', unsafe_allow_html=True)
    drive_files_slot = st.container()
    if st.button("소재 목록 새로고침", key="drive_refetch", width="stretch"):
        drive_materials.clear_file_list_cache()
        _drive_material_index.clear()
        st.rerun()

    cost_markup = st.number_input(
        "구글 비용 마크업 배율",
        min_value=1.0, max_value=2.0, value=DEFAULT_COST_MARKUP, step=0.001, format="%.4f",
        help="보고서의 '비용'은 원가입니다. 리포트 시트의 'cost (마크업 포함)' 기준에 맞추려면 "
             "이 배율을 곱합니다(2026-07 실측 1.0830).",
    )
    # 고정 여부에 따라 완전히 다른 톤(강조 vs 조용함)으로 그려야 해서, 데이터 카드
    # 맨 아래에 독립된 블록으로 뺀다 — 자리만 먼저 잡아두고 내용은 아래에서 채운다.
    #
    # container가 아니라 empty를 쓴다: 실제 내용은 구글 데이터(드롭박스 동기화 + 파싱)가
    # 끝난 뒤에야 채워지는데, 콜드 스타트에서는 그게 리포트 본문보다 10초쯤 늦다(실측).
    # 그 동안 이 자리가 비어 있으면 "블록이 아예 없다"로 읽혀서, 편집 모드를 눌러 캐시가
    # 채워지면 갑자기 생기는 것처럼 보였다. empty는 나중에 내용을 덮어쓸 수 있어서
    # 로딩 자리표시자를 먼저 띄웠다가 준비되면 교체할 수 있다.
    freeze_slot = st.empty()
    with freeze_slot.container(key="google_freeze_loading", border=True):
        st.markdown(
            '<div class="freeze-cta-title freeze-cta-title--muted">'
            '<span class="freeze-cta-dot freeze-cta-dot--muted"></span>'
            '구글 데이터 확인 중</div>'
            '<div class="freeze-cta-body">고정 상태를 불러오고 있어요</div>'
            '<div class="freeze-cta-bar" aria-hidden="true"><i></i></div>',
            unsafe_allow_html=True,
        )

google_folder = _synced_google_folder(st.session_state.get("_google_cache_bust", 0))

def _apply_base_filters(frame):
    """매체·OS·UA·포맷 기본 필터. 전월 비교도 **똑같은 조건**을 통과해야 한다 —
    한쪽에만 필터가 걸리면 델타가 조용히 틀린다."""
    if media_selection:
        frame = frame[frame["media"].isin(media_selection)]
    if os_selection:
        frame = frame[frame["os"].isin(os_selection)]
    if ua_selection:
        frame = frame[frame["ua_type"].isin(ua_selection)]
    if format_selection:
        frame = frame[frame["format"].isin(format_selection) | (frame["media"] == "Google")]
    return frame


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

# 기간 비교 뷰는 **리포트 월 하나가 아니라 여러 달**을 본다. `raw`가 이미 전 월치를 들고
# 있으므로 로딩을 새로 하지 않고, 사이드바 고정 필터만 똑같이 통과시킨 프레임을 하나 더 만든다
# (한쪽에만 필터가 걸리면 두 기간 비교가 조용히 틀린다 — `_apply_base_filters`와 같은 이유).
#
# ⚠ **수동 분류 보정(`manual_overrides`)은 리포트 월에만 적용된다.** 다른 달까지 적용하려면
#    달마다 저장소를 읽어야 해서(7개월이면 리런마다 7회) 비용이 크다. 보정이 필요한 소재를
#    조건에 걸어 비교할 때는 이 점을 감안한다.
all_months = add_derived_metrics(_apply_base_filters(raw))
all_months_named = all_months[all_months["ad"] != "-"]

totals = aggregate_by(overview.assign(_all="전체"), ["_all"]).iloc[0]

# 전월 대비 델타. 리포트는 다음 달 초에 나가므로 발송 시점에는 그 달이 완결돼 있어
# 전체 월끼리 비교하는 게 맞다. 월중에 미리 열어볼 때만 같은 기간끼리로 자동 전환한다
# (8/23까지 들어온 8월을 7월 31일치와 비교하면 소진액이 -26.2%로 나온다 — 실제로는
# 같은 기간끼리 -0.4%다). 사람이 매번 올바른 쪽을 고르게 두면 언젠가 틀린다.
previous_month = month - 1
max_day = comparison_window(scope["date"], month) if "date" in scope.columns else None
previous_scope = _apply_base_filters(scope_to_day(raw, previous_month, max_day))
for _column, _selection in (
    ("media", overview_media),
    ("format", overview_format),
    ("creative_type", overview_type),
    ("size", overview_dimension),
):
    if _selection and not previous_scope.empty:
        previous_scope = previous_scope[previous_scope[_column].isin(_selection)]
if not previous_scope.empty:
    previous_scope = add_derived_metrics(previous_scope)
    previous_scope = manual_overrides.apply(previous_scope, previous_month)
previous_totals = None
if not previous_scope.empty:
    previous_totals = aggregate_by(previous_scope.assign(_all="전체"), ["_all"]).iloc[0]


# 비교 기준은 카드마다 반복하지 않고 묶음 우측 상단에 한 번만 적는다. 달이 안 끝나
# 같은 기간끼리 맞춘 경우에는 그 사실이 문구에 드러나야 한다 — 안 적으면 왜 숫자가
# 리포트의 전월 실적과 다른지 설명할 방법이 없다.
if previous_totals is None:
    comparison_note = f"{previous_month}월 데이터가 없어 전월 대비를 표시하지 않습니다"
elif max_day is not None:
    comparison_note = (
        f"전월({previous_month}월 1~{max_day}일) 대비 — "
        f"{month}월이 {max_day}일까지만 집계돼 같은 기간끼리 맞췄습니다"
    )
else:
    comparison_note = f"전월({previous_month}월) 대비"


def _kpi(label, column, value_text, fmt=None, sub="", primary=False):
    """KPI 카드 하나. sub(회색 설명)는 소진액의 '마크업 포함'처럼 값의 정의가 달라져
    오해가 생길 수 있는 곳에만 남긴다 — 나머지는 라벨만으로 충분하다(2026-08-28)."""
    card = {"label": label, "value": value_text, "sub": sub}
    if primary:
        card["primary"] = True
    if previous_totals is not None and column in previous_totals:
        change = relative_change(totals[column], previous_totals[column])
        card["delta"] = delta_label(change)
        card["delta_direction"] = delta_direction(change)
    return card


kpi_cards([
    # UA 기준이라는 사실은 최하단 각주에서 한 번만 설명한다 — 카드에도 붙였더니
    # 라벨이 길어져 지저분했다(2026-09-02 사용자 지적).
    _kpi("소진액", "cost", f"₩{totals['cost']:,.0f}", sub="마크업 포함", primary=True),
    _kpi("노출", "impression", f"{totals['impression']:,.0f}"),
    _kpi("CTR", "CTR", f"{totals['CTR']:.2%}"),
    _kpi("인스톨", "total install", f"{totals['total install']:,.0f}"),
    _kpi("CPI", "CPI", f"₩{totals['CPI']:,.0f}"),
    _kpi("D0 Read CVR", "D0 read CVR", f"{totals['D0 read CVR']:.2%}"),
], note=comparison_note)

table_title("매체 × OS 요약")
by_media_os = aggregate_by(overview, ["media", "os"])
render_table(
    by_media_os, color_columns=["CPI"], highlight_key="media_os", month=month,
    column_order=SUMMARY_COLUMN_ORDER,
)

# --------------------------------------------------------------------------- 2. TOP 소재

meta_tiktok = overview[overview["media"].isin(["Meta", "TikTok"])]

section(
    "2", "메타/틱톡 TOP 소재 성과",
    note="*앱스플라이어 코호트 데이터 기준",
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
        top,
        metrics=[("CPI", False), ("D0 coin CVR", True)],
        link_materials=True,
        rank_metric=rank_metric,
    )

# OS(AOS/iOS)마다 똑같이 반복되던 우수/저조 기준 설명을 섹션 하단에 한 번만 남긴다.
# st.caption 기본 크기가 리포트 톤(정보 위계 절제)에 비해 도드라져 보인다는 피드백을 받아,
# 우측 구석에 붙는 옅은 각주 한 줄로 낮춘다 — 굳이 안 읽어도 되는 보조 정보로 취급.
st.markdown(
    '<div class="sec-legend">'
    f"녹색 = 우수 · 붉은색 = 저조 — 위 표에 보이는 소재 중 "
    f"{html.escape(METRIC_LABELS.get('CPI', 'CPI'))} · "
    f"{html.escape(METRIC_LABELS.get('D0 coin CVR', 'D0 coin CVR'))} "
    f"기준 각 1개씩 선정 · 최소 소진 ₩{min_cost:,.0f} 이상"
    "</div>",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- 3. 구글


# 고정 여부·시각은 시트 메타데이터만 읽는 가벼운 호출이라 짧게만 캐시한다. 1시간을
# 걸었다가, 다른 세션(또는 다른 사람 브라우저)에서 고정한 스냅샷을 이 세션이 최대 1시간
# 동안 못 보고 "아직 고정 안 됨"을 계속 띄우는 문제가 실제로 났다 — st.cache_data.clear()는
# 버튼을 누른 그 세션에만 듣기 때문이다.
_SNAPSHOT_META_TTL = 60


@st.cache_data(ttl=_SNAPSHOT_META_TTL, show_spinner=False)
def _snapshot_exists(month: int) -> bool:
    # 캐시가 아예 없으면 위젯 하나 건드릴 때마다 API를 다시 불러 눈에 띄게 느려진다(실측 수 초).
    return google_snapshot.exists(month)


@st.cache_data(ttl=_SNAPSHOT_META_TTL, show_spinner=False)
def _snapshot_frozen_at(month: int) -> str | None:
    return google_snapshot.frozen_at(month)


@st.cache_data(ttl=3600, show_spinner="구글 스냅샷 읽는 중…")
def _load_snapshot(month: int, markup: float, frozen_at: str | None) -> pd.DataFrame:
    """스냅샷 행 전체를 읽는 무거운 호출이라 길게 캐시한다.

    `frozen_at`은 함수 안에서 쓰지 않지만 캐시 키에 넣는다 — 재고정으로 값이 바뀌면
    키가 달라져 자동으로 다시 읽는다(TTL을 기다리지 않고도 최신 스냅샷이 반영된다).
    """
    return google_snapshot.load(month, markup)


# 리포트 히스토리 보존: 스냅샷이 있는 달은 무조건 스냅샷만 본다 — 담당자가 드롭박스
# 폴더를 다음 달 파일로 덮어써도 이미 고정해 둔 달의 숫자는 바뀌지 않는다. 자동 고정은
# 하지 않는다(사용자 결정) — 오직 아래 "지금 시점으로 고정" 버튼을 눌렀을 때만 얼린다.
# 스냅샷은 구글시트 전용 탭(설정돼 있으면) 또는 로컬 폴더 복사(폴백)로 저장된다 —
# google_snapshot이 어느 쪽인지 알아서 고른다.
has_snapshot = _snapshot_exists(month)
snapshot_frozen_at = _snapshot_frozen_at(month) if has_snapshot else None
google_source_label = google_snapshot.source_label(month) if has_snapshot else google_folder

google_all = pd.DataFrame()
google_error = None
try:
    if has_snapshot:
        google_all = _load_snapshot(month, cost_markup, snapshot_frozen_at)
    else:
        google_all = _google(google_folder, cost_markup)
        if not google_all.empty:
            google_all = google_all[google_all["month"] == month]
except Exception as error:
    google_error = str(error)

google = pd.DataFrame()
if not google_all.empty:
    google = creative_assets(google_all)

# 사이드바에 '이번 달 실제로 읽은 파일'을 채운다(위에서 자리만 잡아둔 곳).
with google_files_slot:
    if google_error:
        st.metric("애셋 보고서 파일", "읽기 실패", help=f"출처: {google_source_label}")
        st.caption(google_error[:120])
    elif google_all.empty:
        st.metric("애셋 보고서 파일", "0개", help=f"출처: {google_source_label}")
        st.caption(f"{month}월분 보고서가 폴더에 없습니다.")
    else:
        used_files = sorted(google_all["source_file"].dropna().unique())
        source_detail = "" if has_snapshot else " (하위 폴더까지 모두 읽습니다)"
        st.metric(
            "애셋 보고서 파일", f"{len(used_files)}개",
            help=f"출처: {google_source_label}{source_detail}",
        )
        if not has_snapshot:
            st.caption(f"{month}월 데이터로 사용 중 (실시간 연동)")
        with st.expander("읽은 파일 보기"):
            st.markdown("\n".join(f"- `{name}`" for name in used_files))

# 다음 달로 넘어가기 전에 미리 확정해 두고 싶을 때를 위한 수동 고정 — 최신 달에도 쓸 수
# 있다. 항상 "지금 라이브 상태"를 기준으로 얼리므로, 이미 고정된 달이라도 다시 누르면
# 그 시점 값으로 재고정된다. 고정 전에는 놓치면 안 되는 일이라 눈에 띄게, 고정 후에는
# 평소엔 신경 쓸 필요 없는 상태라 조용하게 — 언제 고정됐는지만 작게 남긴다.
live_source_available = dropbox_source.configured() or Path(google_folder).exists()
# empty에 다시 쓰면 위에서 띄운 로딩 자리표시자가 이 내용으로 교체된다.
with freeze_slot.container():
    if has_snapshot:
        with st.container(key="google_freeze_done"):
            done_cols = st.columns([3, 1.4], vertical_alignment="center")
            done_cols[0].caption(f"🔒 {month}월 데이터 고정됨 · {snapshot_frozen_at}")
            if live_source_available:
                if done_cols[1].button("다시 고정", key="google_freeze", width="stretch"):
                    try:
                        google_snapshot.save(month, google_folder)
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as error:  # noqa: BLE001 - 시트 API 오류까지 화면에 보여준다
                        st.error(
                            "고정 실패: "
                            + google_sheets_writer.friendly_error(str(error))
                        )
    elif live_source_available and not google_all.empty:
        with st.container(key="google_freeze_pending", border=True):
            st.markdown(
                '<div class="freeze-cta-title">아직 고정 안 됨</div>'
                '<div class="freeze-cta-body">드롭박스 폴더가 다음 달 파일로 바뀌면 '
                '지금 이 숫자는 사라집니다.</div>',
                unsafe_allow_html=True,
            )
            if st.button("지금 고정하기", key="google_freeze", type="primary", width="stretch"):
                try:
                    google_snapshot.save(month, google_folder)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as error:  # noqa: BLE001 - 시트 API 오류까지 화면에 보여준다
                    st.error(
                        "고정 실패: " + google_sheets_writer.friendly_error(str(error))
                    )
    else:
        # 안 고정됐고 라이브에도 이 달 데이터가 없는 경우 — 담당자가 드롭박스 폴더를
        # 이미 다른 달 파일로 덮어썼거나, 애초에 구글 데이터가 없는 달이다. 캡션 한 줄은
        # 너무 눈에 안 띄어서 놓치기 쉬웠다 — 독립된 박스로 뺀다(강조는 아니고 중립 톤).
        with st.container(key="google_freeze_nodata", border=True):
            st.markdown(
                '<div class="freeze-cta-title freeze-cta-title--muted">'
                '<span class="freeze-cta-dot freeze-cta-dot--muted"></span>'
                '이 달은 고정할 데이터 없음</div>'
                '<div class="freeze-cta-body">구글 라이브 폴더에 이 달 파일이 없어요</div>',
                unsafe_allow_html=True,
            )

# "이 데이터를 어디서 읽었는지"는 매달 볼 필요는 없는 진단 정보라 헤더의 "?" 아이콘으로
# 옮긴다 — 성공적으로 읽었을 때만 채워진다(실패·데이터 없음은 아래 경고로 바로 보여준다).
google_read_hint = None
if not google_error and not google.empty:
    google_read_hint = (
        ("이 달은 고정된 스냅샷입니다.\n" if has_snapshot else "구글 광고 애셋 보고서를 직접 읽었습니다.\n")
        + f"{google_source_label} · 원가에 마크업 ×{cost_markup:.4f} 적용 · "
        f"캠페인 {google['source_file'].nunique()}개 파일"
    )

section(
    "3", "구글 TOP 소재 성과",
    note="*매체 대시보드 데이터 기준",
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

        render_google_material_cards(g_top)
        st.markdown(
            '<div class="tbl-note">영상·이미지 소재만 포함하며, 텍스트 애셋은 제외했습니다.</div>',
            unsafe_allow_html=True,
        )

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
                ok, reason = manual_overrides.save(month, pasted, {
                    "creative_type": creative_type or "",
                    "format": fmt or "",
                    "producer_group": producer or "",
                    "extra_info": extra_info or "",
                    "usp": usp or "",
                })
                if ok:
                    st.rerun()
                else:
                    # 저장 실패를 삼키면 화면에는 분류된 것처럼 보이고 시트에는 없다.
                    st.error(
                        "분류를 저장하지 못했습니다 — "
                        + google_sheets_writer.friendly_error(reason)
                    )


# 드롭다운 후보는 총괄 필터가 걸리기 전의 이 달 전체(scope)에서 뽑는다 — 1번에서 Creative
# Type을 하나로 좁혀 보는 중이라고 해서 분류 후보까지 그 하나로 줄어들면 안 된다.
override_choices = override_options(scope[scope["ad"] != "-"])

# ------------------------------------------------- 5. 소재 분석 (블록 목록)


def clear_editor_state(block_id: str) -> None:
    """편집을 끝낸(또는 놓친) 블록의 임시 위젯 상태를 비운다.

    조건 행(cond_*) 상태는 위젯이라 잠금을 놓아도 세션에 그대로 남는다. 그냥 두면 취소한
    선택이 다음에 블록을 열 때 되살아나고, 그대로 저장하면 실제로 반영돼 버린다.
    """
    # 조건 행·뷰 위젯은 키에 `<block_id>_<view_id>`가 섞여 있어 접두사만으로는 못 잡는다
    # — 블록 id가 포함된 키를 통째로 비운다. 블록 id는 uuid4 앞 6자라 다른 블록을
    # 건드릴 일이 없다.
    prefixes = (f"cond_rows_{block_id}", f"cond_field_{block_id}_",
                f"cond_values_{block_id}_", f"cond_panel_{block_id}",
                f"title_{block_id}", f"blocktitle_{block_id}", f"comment_{block_id}", f"insight_{block_id}",
                f"views_{block_id}", f"next_step_md_{block_id}")
    for key in [k for k in list(st.session_state)
                if k.startswith(prefixes) or f"_{block_id}_" in k
                or k.endswith(f"_{block_id}")]:
        del st.session_state[key]
    st.session_state.pop(f"held_{block_id}", None)


def commit_blocks(month: int, fn, expect: dict | None = None) -> bool:
    """블록 변경을 저장하고, 실패하면 그 이유를 화면에 드러낸다.

    저장이 거부되는 건 정상 동작이다 — 그 사이 다른 사람이 같은 블록을 고쳤다는 뜻이고,
    조용히 덮어써서 남의 글을 지우는 것보다 낫다. 실패를 삼키면 사용자는 저장된 줄 알고
    화면을 떠나므로, 반드시 눈에 보이게 알린다.
    """
    ok, reason = report_blocks.mutate(month, fn, expect=expect)
    if ok:
        return True
    if reason == "conflict":
        st.error(
            "다른 사람이 방금 이 블록을 수정했습니다. 저장하지 않았습니다 — "
            "작성 중이던 내용을 복사해 두고 새로 고친 뒤 다시 저장해 주세요."
        )
    elif reason == "deleted":
        st.error("이 블록이 방금 삭제되었습니다. 저장하지 않았습니다 — 새로 고쳐 확인해 주세요.")
    else:
        st.error(
            "저장하지 못했습니다. 내용을 복사해 두세요 — "
            + google_sheets_writer.friendly_error(reason)
        )
    return False


def editor_taken_over(block_id: str, month: int) -> bool:
    """내가 잡고 있던 잠금을 남이 가져갔는지."""
    owner = st.session_state["editor_token"]
    if not st.session_state.get(f"held_{block_id}"):
        return False
    # 저장 버튼을 살릴지 판단하는 값이라 캐시로 충분하다(매 리런 읽으면 쿼터가 샌다).
    return locks.status(f"block:{block_id}", month, owner).state != "mine"


def lock_gate(
    block_id: str, month: int, title: str, edit_mode: bool, info: str | None = None,
    menu=None, editable_title: bool = False,
) -> bool:
    """블록 헤더와 잠금 조작을 그리고, 편집 UI를 그려도 되는지 돌려준다.

    info는 잠금 상태와 무관하게 제목 옆에 항상 보여줄 중립 배지(예: 조건 요약)다.

    menu는 조작 버튼(편집하기/위·아래/삭제)을 그리는 콜백이다. 제목 아래 별도 줄에
    두면 제목과 표 사이가 벌어져 무슨 블록의 버튼인지 눈이 한 번 더 찾아야 해서,
    제목과 같은 행 오른쪽에 붙인다. 경고·잠금 해제 UI는 좁은 컬럼에 넣으면 문구가
    접히므로 그대로 전체 폭에 그린다.

    edit_mode가 꺼져 있으면 이 블록의 잠금이 내 것이든 남의 것이든 상관없이
    순수 리포트 헤더만 그리고 False를 돌려준다 — 배지·저장 버튼·잠금 해제 UI를
    전부 숨기고, touch도 호출하지 않는다(편집 모드를 끄고 나간 사람의 잠금은
    스스로 만료되도록 그냥 둔다).
    """
    owner = st.session_state["editor_token"]
    kind = f"block:{block_id}"

    def draw_title(badge: tuple[str, str] | None, editable: bool) -> None:
        """편집권을 쥔 동안에는 제목 **그 자리**가 입력칸이 된다.

        예전에는 헤더에 제목을 보여주고 그 아래 `주제 제목` 입력란을 또 뒀다. 같은 값이
        두 번 나와 어느 쪽이 진짜인지 헷갈렸고, 편집 화면이 위젯 더미처럼 보였다.
        입력칸을 제목과 같은 서체·크기로 맞춰(`ui.py`의 `.st-key-blocktitle_` 규칙)
        겉보기를 유지한다.
        """
        if not editable:
            note_header(title, badge, info=info)
            return
        st.text_input(
            "주제 제목", value=title, key=f"blocktitle_{block_id}",
            label_visibility="collapsed", placeholder="주제 제목을 입력하세요",
        )
        if badge or info:
            note_header("", badge, info=info)

    def header(badge: tuple[str, str] | None = None, with_menu: bool = False,
               editable: bool = False) -> None:
        if not (with_menu and menu is not None):
            draw_title(badge, editable)
            return
        left, right = st.columns([2.4, 1.6], vertical_alignment="center")
        with left:
            draw_title(badge, editable)
        with right:
            menu()

    if not edit_mode:
        header()
        return False

    state = locks.status(kind, month, owner)

    if state.state == "mine":
        # 이 세션이 이 블록을 잡고 있다는 사실을 남겨둔다 — 나중에 잠금을 빼앗겼을 때
        # '원래 편집 중이던 사람'인지 구분하는 유일한 근거다.
        st.session_state[f"held_{block_id}"] = True
        header(("mine", "편집 중 · 나"), editable=editable_title)
        # 완료 버튼은 폼 맨 아래(저장 버튼과 합쳐서 하나)에 둔다 — 예전엔 여기 위에서
        # "작성 완료"를 먼저 누르면 저장 없이 잠금만 풀려서, 폼 아래 "저장"을 안 누르고
        # 나가면 방금 쓴 내용이 그대로 날아갔다. 완료 = 저장이 되도록 폼 쪽에서 처리한다.
        locks.touch(kind, month, owner)
        return True

    if st.session_state.get(f"held_{block_id}"):
        # 잠금을 빼앗긴 경우. 여기서 False를 돌려주면 작성 중이던 에디터가 통째로 사라져
        # 입력하던 글이 아무 말 없이 날아간다 — 저장만 막고 화면은 그대로 둔다.
        header(("other", "다른 사람이 이어받음"))
        st.error("다른 사람이 이 블록을 이어받았습니다. 작성 중이던 내용을 복사해 두세요.")
        if st.button("확인했습니다", key=f"ack_{block_id}"):
            clear_editor_state(block_id)
            rerun_local()
        return True

    if state.state == "other":
        # 잠긴 동안에는 조작 버튼(편집·이동·삭제)을 감춘다(2026-08-29, 3안).
        # 예전에는 버튼을 그대로 두고 그 아래 전체 폭 경고를 띄워, 알럿이 폭을 다 먹고
        # 버튼이 두 줄로 접혀 어느 블록 것인지 알기 어려웠다. 지금은 "무엇이 막혔는지"와
        # "어떻게 푸는지"만 제목 줄에 남긴다.
        def locked_menu() -> None:
            with st.container(
                key=f"blocklock_{block_id}", horizontal=True,
                horizontal_alignment="right", vertical_alignment="center", gap="small",
            ):
                if state.held_minutes < locks.STEAL_AFTER_MINUTES:
                    st.markdown(
                        '<span class="lock-hint">잠시 뒤 잠금을 해제할 수 있습니다</span>',
                        unsafe_allow_html=True,
                    )
                    return
                if st.session_state.get(f"steal_{block_id}"):
                    st.markdown(
                        '<span class="lock-hint">작성 중일 수 있습니다. 해제할까요?</span>',
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "해제", key=f"steal_yes_{block_id}",
                        on_click=lambda: (
                            locks.force_release(kind, month),
                            st.session_state.__setitem__(f"steal_{block_id}", False),
                        ),
                    )
                    # 삭제 확인과 같은 이유로 콜백을 쓴다 — 상태 검사가 버튼보다 위에 있어,
                    # 클릭 결과로 상태를 켜면 두 번 눌러야 화면이 바뀐다(2026-08-29).
                    st.button(
                        "취소", key=f"steal_no_{block_id}",
                        on_click=lambda: st.session_state.__setitem__(f"steal_{block_id}", False),
                    )
                else:
                    st.button(
                        "잠금 해제", key=f"steal_btn_{block_id}",
                        on_click=lambda: st.session_state.__setitem__(f"steal_{block_id}", True),
                    )

        saved_menu = menu
        menu = locked_menu
        header(
            ("other", f"다른 창에서 편집 중 · {int(state.held_minutes)}분째"),
            with_menu=True,
        )
        menu = saved_menu
        return False

    header(with_menu=True)
    return False


def block_menu(slot: str, block_id: str, month: int, owner: str) -> None:
    """블록 하나의 조작 버튼을 한 줄에 그린다.

    편집 모드 자체가 사이드바 스위치 뒤에 숨어 있으므로, 이미 편집 모드에 들어온 다음에
    또 팝오버를 열어야 하는 건 불필요한 한 단계였다 — 버튼을 그대로 늘어놓는다.
    """
    confirm_key = f"confirm_del_{block_id}"
    if st.session_state.get(confirm_key):
        # 확인 줄. 묻는 말은 **누를 버튼 바로 왼쪽**에 붙인다(2026-08-29 확정) —
        # 예전에는 문구가 왼쪽 멀리 떨어져 있어 어느 버튼에 대한 말인지 안 읽혔다.
        # 문구도 "코멘트·조건이 사라집니다"에서 "이 블록을 삭제할까요?"로 바꿨다.
        # 블록을 지우면 그 안의 내용이 사라지는 건 당연해서, 설명보다 무엇을 하려는지
        # 묻는 쪽이 직관적이다.
        #
        # 제목 옆 좁은 폭이라 컬럼으로 나누면 "삭 제"처럼 글자가 세로로 접힌다 —
        # horizontal 컨테이너로 내용 폭만 쓰게 하고 오른쪽에 붙인다.
        # 컨테이너 키를 평상시 버튼 줄과 **같게** 둔다. 키가 다르면 Streamlit이 새 요소로
        # 취급해, 리런이 끝나기 전까지 옛 줄과 새 줄이 함께 보인다("삭제"가 둘로 보이던
        # 원인, 2026-08-29). 같은 키면 그 자리를 교체한다.
        with st.container(
            key=f"blockmenu_{block_id}", horizontal=True,
            horizontal_alignment="right", vertical_alignment="center", gap="small",
        ):
            st.markdown(
                '<span class="del-ask">이 블록을 삭제할까요?</span>',
                unsafe_allow_html=True,
            )
            # 되돌릴 수 없는 쪽만 빨강으로 채워 취소와 확실히 구분한다.
            if st.button("삭제", key=f"del_yes_{block_id}"):
                if commit_blocks(
                    month, lambda d: report_blocks.remove_block(d, slot, block_id)
                ):
                    locks.force_release(f"block:{block_id}", month)
                    st.session_state.pop(confirm_key, None)
                    rerun_local()
            # 취소도 같은 이유로 콜백을 쓴다(한 번 클릭에 바로 원래 줄로 돌아온다).
            st.button(
                "취소", key=f"del_no_{block_id}",
                on_click=lambda: st.session_state.__setitem__(confirm_key, False),
            )
        return

    # 조건 배지(정보)와 성격이 갈리게: 편집은 텍스트 링크처럼, 이동·삭제는 정사각 아이콘
    # 버튼으로 위계를 나눈다. 컬럼 대신 horizontal 컨테이너를 써서 버튼이 내용 폭만
    # 차지하게 하고(컬럼은 남는 폭을 균등 분배해 버튼 사이가 벌어진다) 오른쪽에 붙인다.
    with st.container(
        key=f"blockmenu_{block_id}", horizontal=True,
        horizontal_alignment="right", vertical_alignment="center", gap="small",
    ):
        if st.button("편집하기", key=f"edit_{block_id}"):
            if locks.acquire(f"block:{block_id}", month, owner):
                rerun_local()
            else:
                # 전체 폭 알럿은 버튼 줄을 아래로 밀어 레이아웃을 무너뜨린다 — 작게 알린다.
                st.markdown(
                    '<span class="lock-hint">방금 다른 창에서 편집을 시작했습니다</span>',
                    unsafe_allow_html=True,
                )
        if st.button("▲", key=f"up_{block_id}", help="위로"):
            if commit_blocks(
                month, lambda d: report_blocks.move_block(d, slot, block_id, -1)
            ):
                rerun_local()
        if st.button("▼", key=f"down_{block_id}", help="아래로"):
            if commit_blocks(
                month, lambda d: report_blocks.move_block(d, slot, block_id, 1)
            ):
                rerun_local()
        # on_click 콜백으로 상태를 켠다(2026-08-29).
        #
        # 이 함수는 맨 위에서 confirm 상태를 검사하는데, 버튼은 그 아래에서 그려진다.
        # 클릭 결과로 상태를 켜면 그 검사는 이미 지나간 뒤라 같은 화면에 반영되지 않아
        # **두 번 눌러야** 확인 줄이 떴다. 그렇다고 st.rerun을 부르면 리런이 두 번 돌아
        # 옛 버튼 줄과 겹쳐 보인다("삭제"가 둘로 보이던 문제).
        # 콜백은 리런 **전에** 실행되므로, 이어지는 한 번의 리런에서 검사 시점에 이미
        # 상태가 켜져 있다 — 한 번 클릭 + 리런 한 번으로 끝난다.
        st.button(
            "삭제", key=f"del_{block_id}",
            on_click=lambda: st.session_state.__setitem__(confirm_key, True),
        )


def insert_block_row(slot: str, position: int, block_type: str, default_title: str) -> None:
    """블록과 블록 사이에 얇은 '+' 줄을 둔다 — 항상 맨 끝이 아니라 원하는 자리에 끼워 넣는다."""
    label = "＋ 분석 블록 추가" if block_type == "creative_query" else "＋ 노트 블록 추가"
    with st.container(key=f"insert_{slot}_{position}"):
        if st.button(label, key=f"insert_btn_{slot}_{position}",
                     help="이 자리에 블록을 추가합니다", width="stretch"):
            if commit_blocks(month, lambda d: report_blocks.add_block(
                    d, slot, block_type, default_title, position=position)):
                rerun_local()


def condition_editor(block_id: str, conditions: dict,
                     exclude: set[str] | None = None) -> dict:
    """조건 행 UI + 실시간 결과 요약. 조건 dict를 돌려준다.

    `block_id`는 이제 블록 id가 아니라 **뷰 단위 키**(`<block_id>_<view_id>`)다 —
    한 블록에 표가 여러 개라, 블록 id를 그대로 쓰면 표끼리 위젯 상태가 섞인다.

    이 조건이 "무엇에 걸리는지" 편집 중에 바로 보이지 않는다는 피드백을 받아, 조건과
    결과 요약(소재 수·소진액)과 표 노출 토글을 한 패널 안에 묶는다. 표를 꺼 두면 이 조건이
    아직 리포트에 반영되지 않는다는 걸 알 수 있게 흐린 안내를 덧붙인다.

    블록의 저장된 조건에서 시작하고, 위젯 키에는 반드시 block_id를 섞어 블록 간
    상태가 섞이지 않게 한다.
    """
    # 축으로 쓰는 구분자는 여기서 못 고르게 한다 — 축 값은 축 옆에서만 정한다.
    # 그러면 축(GROUP BY)과 조건(WHERE)이 겹치는 화면이 원리적으로 안 나온다.
    exclude = set(exclude or ())
    fields = [f for f in PIVOT_FIELDS if f not in exclude]

    rows_key = f"cond_rows_{block_id}"
    if rows_key not in st.session_state:
        st.session_state[rows_key] = [
            f for f in conditions if f in fields] or [fields[0]]

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
            '<div class="cp-label">이 표에 걸리는 조건</div>',
            unsafe_allow_html=True,
        )
        for position, field in enumerate(rows):
            label_col, value_col, drop_col = st.columns(
                [1.5, 4.2, 0.5], vertical_alignment="center"
            )
            # 같은 구분자를 두 줄에 걸 이유가 없으니 다른 줄이 쓰는 것은 선택지에서 뺀다
            taken = set(rows) - {field}
            available = [f for f in fields if f not in taken]
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
        unused = [f for f in fields if f not in active_rows]
        add_clicked = add_col.button(
            "+ 조건 추가", key=f"cond_add_{block_id}", disabled=not unused
        )

        if dropped is not None:
            active_rows.pop(dropped)
            # 줄이 당겨지면 뒤쪽 구분자 위젯 상태가 옛 값을 물고 있으므로 같이 비운다
            for index in range(len(rows)):
                st.session_state.pop(f"cond_field_{block_id}_{index}", None)
            st.session_state[rows_key] = active_rows
            rerun_local()
        if add_clicked:
            st.session_state[rows_key] = active_rows + [unused[0]]
            rerun_local()

        st.session_state[rows_key] = active_rows

        # 실시간 요약 — 저장 전에도 "지금 조건이 몇 개·얼마를 걸러내는지"가 바로 보여야
        # 조건이 표에 걸리는 필터라는 게 체감된다. 결과 계산은 render_view와
        # 완전히 같은 match_conditions()를 써서 표와 어긋나지 않게 한다.
        _, live_count = match_conditions(result)
        st.markdown(
            f'<div class="cp-summary">이 조건에 맞는 소재 <b>{live_count:,}개</b></div>',
            unsafe_allow_html=True,
        )

    return result


def match_conditions(conditions: dict,
                     across_months: bool = False) -> tuple[pd.DataFrame, int]:
    """조건에 맞는 소재를 찾는다. (매칭된 원본 스코프, 소재 수)를 돌려준다.

    condition_editor의 실시간 요약과 render_view의 표가 같은 매칭 결과를 써야
    "이 조건이 무엇에 걸리는지"가 편집 중에도 어긋나지 않는다 — 로직을 한 곳에 둔다.

    `across_months=True`면 리포트 월이 아니라 **전 기간**에서 찾는다(기간 비교 뷰 전용).
    """
    named = all_months_named if across_months else named_overview
    whole = all_months if across_months else overview

    # 소재명 규칙 파싱이 있어야 조건이 의미가 있다 — 구글은 소재 단위 태깅이 없어 제외한다.
    # 조건 매칭도 태그를 쓰면 펼친 프레임에서 해야 한다.
    base = explode_extra_info(named) if "extra_info_tag" in conditions else named

    matched = base
    for field, values in conditions.items():
        matched = matched[matched[field].astype(str).isin(values)]
    matched_ads = matched["ad"].unique()

    # 집계는 펼치기 전 원본에서 한다 — 태그를 여러 개 고르면 펼친 프레임에선 같은 소재가 겹친다.
    scope_of_match = whole[whole["ad"].isin(matched_ads)]
    return scope_of_match, len(matched_ads)


COMPARE_METRICS = ["cost", "CPI", "CTR", "D0 read CVR", "D0 coin CVR", "CPC"]

#: 빈 뷰를 만들 때의 기본값. 저장된 뷰에 없는 키는 여기서 채운다 — 나중에 필드를
#: 늘려도 예전에 저장된 뷰가 KeyError로 화면을 죽이지 않는다.
VIEW_DEFAULTS = {
    "label": "",
    # 표 종류는 이제 `pivot`(행/값/필터) 또는 `compare`(기간 비교) 둘뿐이다.
    # 예전의 `aggregate`/`list` 구분은 사라졌다 — 행에 소재명을 넣으면 목록,
    # 빼면 집계표다. 별도 드롭다운으로 고를 필요가 없다.
    "kind": "pivot",
    #: 행 = 묶는 기준. `[{"field": ..., "values": [...]}]`.
    #: 값을 지정하면 그 축에서 그 값들만 보여준다(비우면 전체).
    "rows": [],
    #: 값 = 보여줄 지표. 비우면 기본 세트 — 빈 목록을 '0개'로 읽으면 표가 사라진다.
    "values": [],
    #: 필터 = 표에 담을 범위. **값을 좁히는 자리는 여기 하나뿐이다** — 행에도 값
    #: 선택을 붙였더니 하는 일이 같아져서 "왜 두 군데서 좁히나"가 됐다.
    #: 행으로 쓰는 구분자도 여기서 고를 수 있다(시트 피벗도 그렇다).
    "filters": {},
    #: 필터 결과에 **더할** 소재. 필터를 두 개 걸면 교집합이라 "이 조건에 맞는 소재
    #: + 손으로 고른 소재"는 필터로 표현할 수 없다. 실제 리포트도 대상 소재를
    #: 파일명으로 나열하는 칸을 따로 둔다(8월 시트 148~175행).
    "include_ads": [],
    "chart_kind": "", "metric": "CPI", "top_n": 0,
    # 기간 비교 뷰용
    "periods": [], "metrics": [],
}

#: 예전 형식의 필드 — 지우지 않는다. 되돌리려면 코드만 되돌리면 되게 남겨 둔다.
LEGACY_VIEW_FIELDS = ("axis", "axis_values", "conditions", "columns", "chart",
                      "show_table")


def migrate_view(view: dict) -> dict:
    """예전 뷰(`axis`/`conditions`/`columns`)를 행/값/필터로 옮긴다.

    **읽을 때만 변환하고 저장된 원본은 건드리지 않는다** — `promote_views`와 같은 방식.
    다음 저장 때 새 형식으로 굳는다.
    """
    if view.get("rows") or view.get("kind") == "compare":
        return view

    legacy_kind = view.get("kind")
    if legacy_kind not in ("aggregate", "list"):
        return view

    columns = list(view.get("columns") or [])
    conditions = dict(view.get("conditions") or {})
    axis = view.get("axis") or "creative_type"

    # 행: 목록이면 소재명, 집계면 축. 매체는 예전에 컬럼 선택이 결정했다
    # (컬럼을 안 고르면 기본 세트에 매체가 있었으므로 나뉘어 있었다).
    head = "ad" if legacy_kind == "list" else axis
    rows = [{"field": head}]
    if "media" in (columns or DEFAULT_PIVOT_ROWS):
        rows.append({"field": "media"})

    values = [c for c in columns if c in METRIC_COLUMNS]
    # 예전 축 값은 이제 **필터**로 간다 — 좁히는 자리가 하나뿐이므로.
    filters = dict(conditions)
    narrowed = list(view.get("axis_values") or conditions.get(axis) or [])
    if legacy_kind == "aggregate" and narrowed:
        filters[axis] = narrowed

    moved = dict(view)
    moved.update({"kind": "pivot", "rows": rows, "values": values,
                  "filters": filters, "include_ads": []})
    return moved


def empty_periods() -> list[dict]:
    return [{"label": "", "months": []}, {"label": "", "months": []}]


def view_with_defaults(view: dict) -> dict:
    merged = copy.deepcopy(VIEW_DEFAULTS)
    source = migrate_view(dict(view or {}))
    merged.update({k: v for k, v in source.items()
                   if v is not None and k not in LEGACY_VIEW_FIELDS})
    merged["rows"] = normalize_rows(merged["rows"])
    if not merged.get("id"):
        merged["id"] = uuid4().hex[:6]
    # 예전 뷰는 차트가 켜짐/꺼짐 두 가지뿐이었다. 켜져 있었으면 기본 차트로 올린다.
    if (view or {}).get("chart") and not merged.get("chart_kind"):
        merged["chart_kind"] = "ranking"
    if merged["chart_kind"] not in CHART_KINDS:
        merged["chart_kind"] = ""
    return merged


#: 행·필터에 쓸 수 있는 구분자와 그 이름. `PIVOT_FIELDS`와 같은 어휘를 쓰되
#: 피벗의 행으로 넣을 수 있는 것만 남긴다(소재명이 추가된다 — 넣으면 소재 목록이 된다).
FIELD_LABELS = {
    "ad": "소재명", "media": "매체", "os": "OS", "title_kr": "작품",
    "creative_type": "Creative Type", "format": "Creative Format",
    "size": "Dimension", "orientation": "사이즈 방향",
    "producer_group": "제작 주체", "usp": "USP",
    "extra_info_tag": "Extra Info (태그별)",
}


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, COLUMN_LABELS.get(field, field))


CHART_KINDS = {
    "": "없음",
    "ranking": "랭킹 막대 + 기준선",
    "quadrant": "효율 × 볼륨",
    "dumbbell": "매체 대비",
}

#: 차트 공통 서식. 표와 같은 회색조를 쓰고 격자·눈금은 뒤로 물린다(액센트 1색 원칙).
CHART_INK, CHART_MUTED, CHART_FAINT, CHART_GRID = "#14171a", "#6b7681", "#97a1ac", "#e6e9ec"
#: 소진 비중이 이 값보다 작으면 흐리게 그린다. 없애지는 않는다 — 합계가 안 맞으면
#: 광고주가 표와 대조할 때 어긋난다.
LOW_VOLUME_SHARE = 0.02


def chart_layout(fig, height: int = 380):
    """대시보드 톤앤매너 — Pretendard, 흰 배경, 그림자 없음, 회색조 축."""
    fig.update_layout(
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        margin=dict(l=10, r=10, t=26, b=10), height=height,
        font=dict(size=12, family="Pretendard, sans-serif", color=CHART_MUTED),
        showlegend=False, hoverlabel=dict(font_family="Pretendard, sans-serif"),
    )
    fig.update_xaxes(gridcolor=CHART_GRID, zeroline=False, linecolor=CHART_GRID,
                     tickfont=dict(color=CHART_FAINT, size=10))
    fig.update_yaxes(gridcolor=CHART_GRID, zeroline=False, linecolor=CHART_GRID,
                     tickfont=dict(color=CHART_MUTED, size=11))
    return fig


def media_color(media: str) -> str:
    return MEDIA_COLORS.get(str(media), MEDIA_COLOR_FALLBACK)


def metric_axis_format(metric: str) -> str:
    if metric in ("CTR", "D0 read CVR", "D0 coin CVR", "D7 coin CVR"):
        return ".1%"
    return ",.0f"


def benchmark_note(value: float | None, metric: str, month: int) -> str:
    """기준선이 무엇인지 표 아래에 글로도 남긴다 — 선만 있으면 무엇의 평균인지 모른다."""
    if value is None:
        return ""
    shown = f"{value:.2%}" if metric_axis_format(metric) == ".1%" else f"₩{value:,.0f}"
    return (f'<div class="tbl-note">점선 = {month}월 전체 성과 {shown} '
            "(조건을 걸지 않은 그 달 같은 매체 전체). "
            "흐린 막대는 소진 비중 2% 미만입니다.</div>")


def ranking_chart(frame: pd.DataFrame, axis: str, metric: str, benchmark: float | None):
    """A안 — 좋은 순으로 정렬한 가로 막대. 기준선 하나.

    예전 그룹 막대의 문제는 **가장 큰 막대가 노이즈**였다는 것이다(8월 Visual·Meta
    CPI ₩29,373 = 설치 19건). 정렬하면 그게 맨 끝으로 가고, 흐리게 칠하면 결론처럼
    보이지 않는다.
    """
    labels = [f"{row[axis]} · {row['media']}" if "media" in frame.columns else str(row[axis])
              for _, row in frame.iterrows()]
    colors = [media_color(row["media"]) if "media" in frame.columns else MEDIA_COLOR_FALLBACK
              for _, row in frame.iterrows()]
    opacity = [0.35 if bool(row["_low_volume"]) else 0.95 for _, row in frame.iterrows()]

    fig = go.Figure(go.Bar(
        x=frame["_rank_value"], y=labels, orientation="h",
        marker=dict(color=colors, opacity=opacity),
        customdata=frame[["cost", "total install"]].to_numpy(),
        hovertemplate=("%{y}<br>" + METRIC_LABELS.get(metric, metric) + " %{x:,.0f}"
                       "<br>소진 ₩%{customdata[0]:,.0f}"
                       "<br>설치 %{customdata[1]:,.0f}건<extra></extra>"),
    ))
    # 좋은 것이 위로 오게. plotly의 가로 막대는 첫 항목을 아래에 놓는다.
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(tickformat=metric_axis_format(metric),
                     title_text=METRIC_LABELS.get(metric, metric))
    if benchmark is not None:
        fig.add_vline(x=benchmark, line=dict(color=CHART_INK, width=1, dash="dot"))
    return chart_layout(fig, height=max(240, 26 * len(frame) + 90))


def wide_spread(values: pd.Series, ratio: float = 8.0) -> bool:
    """최댓값이 최솟값의 `ratio`배를 넘는가 — 넘으면 선형 축에서 작은 값들이 뭉개진다."""
    numbers = pd.to_numeric(values, errors="coerce").dropna()
    numbers = numbers[numbers > 0]
    if len(numbers) < 3:
        return False
    return float(numbers.max()) / float(numbers.min()) > ratio


def quadrant_chart(frame: pd.DataFrame, axis: str, metric: str, benchmark: float | None):
    """B안 — 가로 소진액(규모) × 세로 지표(효율), 원 크기 = 설치.

    "효율이 좋다"와 "규모가 있다"를 한 화면에서 본다. 다음 달 제작 방향을 정할 때
    실제로 필요한 건 그 둘의 교집합인데, 막대 하나로는 절대 안 보인다.
    """
    installs = frame["total install"].fillna(0).clip(lower=0)
    sizes = (installs ** 0.5)
    sizes = (sizes / sizes.max() * 34 + 8) if sizes.max() > 0 else pd.Series(12, index=frame.index)

    fig = go.Figure()
    for media, part in frame.groupby("media", sort=False) if "media" in frame.columns \
            else [("전체", frame)]:
        fig.add_trace(go.Scatter(
            x=part["cost"], y=part["_rank_value"], mode="markers+text",
            text=part[axis].astype(str), textposition="middle right",
            textfont=dict(size=10, color=CHART_MUTED),
            marker=dict(size=sizes.loc[part.index], color=media_color(media),
                        opacity=0.55, line=dict(width=1.2, color=media_color(media))),
            customdata=part[["total install"]].to_numpy(),
            hovertemplate=("%{text} · " + str(media) + "<br>소진 ₩%{x:,.0f}<br>"
                           + METRIC_LABELS.get(metric, metric) + " %{y:,.0f}"
                           "<br>설치 %{customdata[0]:,.0f}건<extra></extra>"),
        ))
    # 값 범위가 넓으면 **이상치 하나가 축을 독차지한다.** 실측(2026-08): Visual·Meta가
    # CPI ₩29,373(설치 19건)이라 y축이 3만까지 늘어나고 나머지 20개가 바닥에 눌렸다.
    # 점을 빼면 합계가 안 맞고 조용히 숨기는 셈이라, 대신 로그 축으로 펼친다.
    log_x = wide_spread(frame["cost"])
    log_y = wide_spread(frame["_rank_value"])
    fig.update_xaxes(title_text="소진액" + (" (로그)" if log_x else ""),
                     type="log" if log_x else "linear",
                     tickformat=",.0f" if not log_x else "~s")
    fig.update_yaxes(title_text=METRIC_LABELS.get(metric, metric) + (" (로그)" if log_y else ""),
                     type="log" if log_y else "linear",
                     tickformat=metric_axis_format(metric) if not log_y else "~s")
    if benchmark is not None and benchmark > 0:
        fig.add_hline(y=math.log10(benchmark) if log_y else benchmark,
                      line=dict(color=CHART_INK, width=1, dash="dot"))
    return chart_layout(fig, height=400)


def dumbbell_chart(pairs: pd.DataFrame, axis: str, metric: str):
    """C안 — 같은 유형이 매체마다 얼마나 다른지. 선 길이가 곧 격차."""
    fig = go.Figure()
    names = pairs[axis].tolist()
    for position, row in pairs.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["value_a"], row["value_b"]], y=[names[position]] * 2,
            mode="lines", line=dict(color=CHART_GRID, width=3), hoverinfo="skip",
        ))
    for side in ("a", "b"):
        fig.add_trace(go.Scatter(
            x=pairs[f"value_{side}"], y=names, mode="markers",
            marker=dict(size=11, color=[media_color(m) for m in pairs[f"media_{side}"]]),
            customdata=pairs[[f"media_{side}"]].to_numpy(),
            hovertemplate=("%{y} · %{customdata[0]}<br>"
                           + METRIC_LABELS.get(metric, metric)
                           + " %{x:,.0f}<extra></extra>"),
        ))
    fig.update_xaxes(title_text=METRIC_LABELS.get(metric, metric),
                     tickformat=metric_axis_format(metric))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return chart_layout(fig, height=max(240, 30 * len(pairs) + 90))


def media_legend(medias) -> str:
    dots = "".join(
        f'<span class="chart-key"><i style="background:{media_color(m)}"></i>{html.escape(str(m))}</span>'
        for m in medias
    )
    return f'<div class="chart-legend">{dots}</div>'


def render_axis_chart(view: dict, table: pd.DataFrame, axis: str,
                      month: int, key: str) -> None:
    """집계표 위에 차트를 그린다. 종류는 뷰가 고른다.

    **기준선은 표 안의 평균이 아니라 그 달 전체 성과**다. 실제 리포트 시트도
    `TikTok 신규유형 총계` 바로 아래 `6월 틱톡 AOS 베너 소재 총 성과`를 붙여 놓고
    눈으로 대조한다 — 조건을 건 표의 자기 평균과 비교하면 "이 조건이 좋은가"를
    자기 자신에게 묻는 셈이라 아무것도 알 수 없다.
    """
    metric = view["metric"] if view["metric"] in COMPARE_METRICS else "CPI"
    kind = view["chart_kind"]

    # 그 달 전체(조건 없음) — 단, 표에 있는 매체로만 좁힌다. 표가 틱톡만 담고 있는데
    # 메타가 섞인 전체와 비교하면 기준선이 엉뚱해진다.
    whole = named_overview
    if "media" in table.columns:
        whole = whole[whole["media"].isin(table["media"].unique())]
    benchmark = metric_benchmark(whole, metric)
    if metric not in table.columns:
        # 값 목록에서 그 지표를 빼면 그릴 수가 없다 — 조용히 빈 그래프를 그리지 않는다.
        status_row("warn", f"{METRIC_LABELS.get(metric, metric)}가 표에 없습니다",
                   "값 칩에 그 지표를 추가하면 그래프가 그려집니다.")
        return

    if kind == "dumbbell":
        pairs = dumbbell_frame(table, axis, metric)
        if len(pairs) < 2:
            status_row("warn", "매체 대비를 그릴 수 없습니다",
                       "두 매체에 모두 있는 값이 2개 이상이어야 선을 그을 수 있습니다.")
            return
        st.plotly_chart(dumbbell_chart(pairs, axis, metric), width="stretch",
                        key=f"chart_{key}")
        st.markdown(media_legend(sorted({*pairs["media_a"], *pairs["media_b"]})),
                    unsafe_allow_html=True)
        return

    frame = chart_frame(table, axis, metric,
                        low_volume_share=LOW_VOLUME_SHARE, benchmark=benchmark)
    if frame.empty:
        return
    if kind == "ranking" and view["top_n"]:
        # 정렬이 끝난 뒤에 자른다 — "상위 N개"는 좋은 순으로 N개라는 뜻이다.
        frame = frame.head(int(view["top_n"]))

    figure = (ranking_chart(frame, axis, metric, benchmark) if kind == "ranking"
              else quadrant_chart(frame, axis, metric, benchmark))
    st.plotly_chart(figure, width="stretch", key=f"chart_{key}")
    if "media" in frame.columns:
        st.markdown(media_legend(sorted(frame["media"].unique())),
                    unsafe_allow_html=True)
    st.markdown(benchmark_note(benchmark, metric, month), unsafe_allow_html=True)


def render_compare_view(view: dict) -> None:
    """기간 비교표 — 행이 지표, 열이 기간 + 증감.

    다른 표와 축이 반대이고 값이 문자열이라, **셀 강조·CPI 히트맵은 붙이지 않는다**
    (같은 강조 저장소를 쓰면 키가 꼬인다).

    ⚠ 증감 단위는 지표마다 다르다 — 비율은 `%p`(차이), 나머지는 `%`(변화율).
      판단은 `creative_data.delta_unit`이 하고 여기서는 표기만 한다. 광고주가 숫자를
      잘못 읽지 않도록 **단위를 숫자 옆에 항상 함께 찍는다.**
    """
    periods = [dict(p) for p in (view.get("periods") or [])]
    if len(periods) != 2 or not all(p.get("months") for p in periods):
        status_row("warn", "비교할 기간 두 개를 골라 주세요",
                   "편집 모드에서 기간마다 라벨과 월을 지정합니다.")
        return

    scope_of_match, matched_count = match_conditions(view["conditions"],
                                                     across_months=True)
    if scope_of_match.empty:
        status_row("warn", "조건에 맞는 소재가 없습니다", "조건을 완화해 보세요.")
        return

    available = set(month_options(raw))
    missing = sorted({int(m) for p in periods for m in p["months"]} - available)
    if missing:
        # 조용히 빈 칸으로 두면 "집행을 안 했다"로 읽힌다 — 이 프로젝트의 사고는
        # 대부분 에러 없이 조용히 틀린다.
        status_row("warn", f"데이터가 없는 달이 있습니다: {', '.join(map(str, missing))}월",
                   "그 달의 값은 표에 '-'로 나옵니다.")

    table = compare_periods(scope_of_match, periods, view.get("metrics") or None)
    period_columns = [c for c in table.columns if c not in ("지표", "증감", "단위")]

    rows = []
    for _, line in table.iterrows():
        ratio = line["단위"] == "%p"
        cells = [str(line["지표"])]
        for column in period_columns:
            value = line[column]
            cells.append("-" if pd.isna(value)
                         else (f"{value:.2%}" if ratio else f"{value:,.0f}"))
        delta = line["증감"]
        cells.append("-" if pd.isna(delta)
                     else (f"{delta:+.2f}%p" if ratio else f"{delta:+.1%}"))
        rows.append(cells)

    report_table(rows, ["지표"] + period_columns + ["증감"], left_columns={"지표"})
    st.markdown(
        f'<div class="tbl-note">소재 {matched_count:,}개 · '
        "비율 지표(CTR·CVR)의 증감은 <b>%p</b>(차이), 나머지는 <b>%</b>(변화율)입니다.</div>",
        unsafe_allow_html=True,
    )


def render_view(view: dict, month: int, key_prefix: str,
                editing: bool = False) -> None:
    """뷰 하나(기준 라벨 + 편집기 + 표 [+ 그래프])를 그린다.

    강조 키에 **뷰 id를 섞는다** — 안 그러면 한 블록 안 두 표가 강조 상태를 공유해서,
    첫 표의 셀을 칠하면 둘째 표의 같은 자리가 함께 칠해진다.
    """
    view = view_with_defaults(view)
    view_key = f"{block_id_of(key_prefix)}_{view['id']}"
    if editing:
        view = table_editor(view, view_key)
    elif view["label"]:
        st.markdown(
            f'<div class="view-basis">* {html.escape(view["label"])}</div>',
            unsafe_allow_html=True,
        )

    if view["kind"] == "compare":
        render_compare_view(view)
        return

    highlight_key = f"{key_prefix}_{view['id']}"
    table = pivot_frame(named_overview, view["rows"], view["values"],
                        filters=view["filters"], min_cost=min_cost,
                        include_ads=view["include_ads"])
    if table.empty:
        status_row("warn", "조건에 맞는 소재가 없습니다",
                   "필터를 완화하거나 행 값을 늘려 보세요.")
        return

    fields = [r["field"] for r in view["rows"]]
    # 그래프는 소재명이 아닌 첫 행을 축으로 쓴다 — 소재 300개를 막대로 그리면 못 읽는다.
    axis = next((f for f in fields if f != "ad"), None)
    if view["chart_kind"] and axis:
        render_axis_chart(view, table, axis, month, highlight_key)

    render_table(
        table.rename(columns={f: field_label(f) for f in fields}),
        color_columns=["CPI"], highlight_key=highlight_key, month=month,
    )
    st.markdown(
        f'<div class="tbl-note">{" · ".join(field_label(f) for f in fields)} 기준 '
        f"{len(table):,}줄. 행에서 구분을 빼면 그 축을 합쳐 다시 집계합니다.</div>",
        unsafe_allow_html=True,
    )


VIEW_KINDS = {"pivot": "피벗 표", "compare": "기간 비교"}
QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"header": [2, 3, False]}],
    [{"list": "ordered"}, {"list": "bullet"}],
    [{"color": []}, {"background": []}],
    ["link", "blockquote", "code-block"],
    ["clean"],
]


def clear_view_state(block_id: str, view_id: str) -> None:
    """지운 표가 남긴 위젯 상태를 지운다."""
    view_key = f"{block_id}_{view_id}"
    for key in [k for k in list(st.session_state) if view_key in k]:
        del st.session_state[key]


def view_from_widgets(view: dict, view_key: str) -> dict:
    """저장할 뷰를 **화면 위젯의 현재 값**으로 조립한다.

    편집기는 표 바로 위(`render_view`)에서 그리는데 저장 버튼은 그보다 위에 있다.
    Streamlit 위젯 값은 세션에 남아 있으므로, 저장 시점에 그 세션 값을 읽으면
    순서에 상관없이 항상 화면과 같은 것이 저장된다.
    """
    merged = view_with_defaults(view)
    session = st.session_state

    def take(key, fallback):
        value = session.get(key)
        return fallback if value is None else value

    merged["label"] = take(f"vlabel_{view_key}", merged["label"])
    merged["kind"] = take(f"vkind_{view_key}", merged["kind"])
    merged["chart_kind"] = take(f"vchart_{view_key}", merged["chart_kind"])
    merged["metric"] = take(f"vmetric_{view_key}", merged["metric"])
    merged["top_n"] = int(take(f"vtop_{view_key}", merged["top_n"]) or 0)

    row_fields = take(f"pvrows_{view_key}", [r["field"] for r in merged["rows"]])
    merged["rows"] = normalize_rows([{"field": f} for f in row_fields])
    merged["values"] = list(take(f"pvvals_{view_key}", merged["values"]))
    merged["include_ads"] = list(take(f"pvads_{view_key}", merged["include_ads"]))

    filter_fields = take(f"pvfilters_{view_key}", list(merged["filters"] or {}))
    merged["filters"] = {
        f: list(take(f"pvfval_{view_key}_{f}", (merged["filters"] or {}).get(f) or []))
        for f in filter_fields
        if take(f"pvfval_{view_key}_{f}", (merged["filters"] or {}).get(f) or [])
    }
    return merged


def period_editor(view_key: str, periods: list[dict]) -> list[dict]:
    """기간 비교 뷰의 기간 두 개(라벨 + 월 여러 개)를 편집한다.

    월을 여러 개 고르면 그 기간의 **누적**이다 — 실제 리포트의
    `방영 전 (4월 누적)` vs `방영 후 (6월 누적)` 같은 표가 그 형태다.
    선택지는 데이터에 실제로 있는 달만 보여준다(없는 달을 고르면 표가 '-'가 된다).
    """
    saved = list(periods or [])
    saved += [{"label": "", "months": []}] * (2 - len(saved))
    choices = month_options(raw)

    with st.container(border=True, key=f"period_box_{view_key}"):
        st.markdown('<div class="cp-label">비교할 기간 두 개</div>',
                    unsafe_allow_html=True)
        result = []
        for index, side in enumerate(("A", "B")):
            label_col, months_col = st.columns([2, 3], vertical_alignment="center")
            current = saved[index] if isinstance(saved[index], dict) else {}
            label = label_col.text_input(
                f"기간 {side} 이름", value=str(current.get("label") or ""),
                key=f"vperiod_label_{view_key}_{index}",
                placeholder="예: 넷플릭스 방영 전 (4월 누적)",
            )
            months = months_col.multiselect(
                f"기간 {side} 월 (여러 개 = 누적)", choices,
                default=[m for m in (current.get("months") or []) if m in choices],
                format_func=lambda m: f"{m}월",
                key=f"vperiod_months_{view_key}_{index}",
            )
            result.append({"label": label, "months": [int(m) for m in months]})
    return result


def field_value_options(field: str) -> list[str]:
    """그 구분자에 이 달 실제로 있는 값들. 없는 값을 고르면 빈 표가 된다."""
    frame = explode_extra_info(named_overview) if field == "extra_info_tag" else named_overview
    if field not in frame.columns:
        return []
    return sorted(frame[field].dropna().astype(str)
                  .replace("", pd.NA).dropna().unique())


def value_popover(view_key: str, slot: str, fields: list[str], saved: dict) -> dict:
    """고른 구분자마다 값 선택을 하나씩 담은 팝오버. `{필드: [값...]}`을 돌려준다.

    구분자 선택(멀티셀렉트)과 값 선택(팝오버)을 나눈 이유: 한 줄에 다 펼치면 구분자
    수만큼 위젯이 늘어나 다시 컨트롤 벽이 된다. 칩을 눌러 값만 손보는 흐름이 짧다.
    """
    if not fields:
        return {}
    picked = {f: [v for v in (saved.get(f) or [])] for f in fields}
    summary = ", ".join(
        f"{field_label(f)}={','.join(picked[f])}" if picked[f] else field_label(f)
        for f in fields
    )
    with st.popover(f"값 지정 · {summary[:34]}", use_container_width=True):
        for field in fields:
            choices = field_value_options(field)
            picked[field] = st.multiselect(
                f"{field_label(field)} (비우면 전체)", choices,
                default=[v for v in picked[field] if v in choices],
                key=f"pv{slot}val_{view_key}_{field}",
            )
    return picked


def drop_view(view_key: str, view_id: str) -> None:
    """표 하나를 지운다. 목록은 블록 단위 세션에 있다."""
    block_id = view_key.rsplit("_", 1)[0]
    state_key = f"views_{block_id}"
    remaining = [v for v in st.session_state.get(state_key, [])
                 if v.get("id") != view_id]
    st.session_state[state_key] = remaining
    clear_view_state(block_id, view_id)
    rerun_local()


def block_id_of(key_prefix: str) -> str:
    """`sec5_<block_id>` 에서 블록 id만 꺼낸다."""
    return key_prefix.split("_", 1)[-1]


def table_editor(view: dict, view_key: str) -> dict:
    """표 하나의 설정 전체 — 기준 라벨 · 그래프 · 행/값/필터. **표 바로 위**에 그린다.

    예전에는 블록 상단 `설정` 아코디언 안에 모여 있었다. 표가 2~6개 붙는 구조라,
    어느 표의 설정인지 눈으로 한 번 더 찾아야 했다. 고치려는 표를 보면서 만지게 한다.
    """
    with st.container(key=f"te_{view_key}"):
        head = st.columns([4, 2, 2, 0.7], vertical_alignment="bottom")
        label = head[0].text_input(
            "기준 라벨", value=view["label"], key=f"vlabel_{view_key}",
            placeholder="예: 틱톡 AOS / 앱스플라이어 코호트 기준",
        )
        kinds = list(VIEW_KINDS)
        kind = head[1].selectbox(
            "표 종류", kinds,
            index=kinds.index(view["kind"]) if view["kind"] in VIEW_KINDS else 0,
            format_func=lambda k: VIEW_KINDS[k], key=f"vkind_{view_key}",
        )
        chart_kinds = list(CHART_KINDS)
        chart_kind = view["chart_kind"]
        if kind == "pivot":
            chart_kind = head[2].selectbox(
                "그래프", chart_kinds,
                index=chart_kinds.index(chart_kind) if chart_kind in CHART_KINDS else 0,
                format_func=lambda k: CHART_KINDS[k], key=f"vchart_{view_key}",
            )
        # ⚠ `st.button`은 눌린 **그 리런에서만** True다. 예전에는 이 값을 `완료` 누를
        #    때 읽어서 삭제하려 했는데, 그때는 이미 False라 영영 삭제가 안 됐다.
        #    그 자리에서 세션 목록을 고치고 리런한다.
        if head[3].button("✕", key=f"vdrop_{view_key}", help="이 표 삭제"):
            drop_view(view_key, view["id"])

        if kind == "pivot" and chart_kind:
            metric_col, top_col = st.columns([3, 1], vertical_alignment="bottom")
            metric_col.segmented_control(
                "그래프 지표", COMPARE_METRICS,
                default=view["metric"] if view["metric"] in COMPARE_METRICS else "CPI",
                key=f"vmetric_{view_key}",
                format_func=lambda m: METRIC_LABELS.get(m, m),
            )
            if chart_kind == "ranking":
                top_col.number_input(
                    "상위 N개 (0=전체)", min_value=0, max_value=50,
                    value=int(view["top_n"] or 0), step=5, key=f"vtop_{view_key}",
                )

        view = {**view, "label": label, "kind": kind, "chart_kind": chart_kind}
        if kind == "compare":
            view = {**view, "periods": period_editor(view_key, view["periods"])}
        else:
            view = pivot_editor(view, view_key)
    return view


def pivot_editor(view: dict, view_key: str) -> dict:
    """행 / 값 / 필터 / 소재 추가. 표 **바로 위**에 둔다.

    구글 시트 피벗 편집기와 같은 모델이다(사용자가 그 화면을 참고로 지목했다).
    중요한 것은 **역할이 한 자리씩만 있다는 점**이다:

      행        = 무엇으로 묶을까. 빼면 그 축을 합쳐 **다시 집계**된다.
      값        = 어떤 지표를 보여줄까.
      필터      = 무엇을 **좁힐까**. 좁히는 자리는 여기 하나뿐이다.
      소재 추가 = 무엇을 **더할까**. 필터는 교집합이라 합집합을 표현할 수 없다.

    처음에는 행마다 값 선택을 붙였는데, 그러면 행과 필터가 같은 일을 해서
    "왜 두 군데서 좁히나"가 됐다(사용자 지적). 시트 피벗도 행에는 값 선택기가 없다.
    그래서 행 필드를 필터에서 빼지 않는다 — 자리가 하나면 겹치는 게 아니라 그게
    유일한 방법이 된다.

    **위젯만으로 만든다.** 버튼으로 중간 상태를 옮기는 방식은 이 프로젝트에서 위젯
    상태와 저장 상태가 엇갈리는 버그를 반복해서 만들었다. 멀티셀렉트 하나가
    추가·삭제·순서를 다 해결한다(선택 순서가 곧 행 순서다).
    """
    saved_rows = [r["field"] for r in view["rows"]]

    with st.container(key=f"pv_{view_key}"):
        st.markdown('<div class="pv-lab">행 <span>묶는 기준 · 빼면 합쳐서 다시 계산</span>'
                    "</div>", unsafe_allow_html=True)
        row_fields = st.multiselect(
            "행", DIMENSION_COLUMNS,
            default=[f for f in (saved_rows or DEFAULT_PIVOT_ROWS)
                     if f in DIMENSION_COLUMNS],
            format_func=field_label, key=f"pvrows_{view_key}",
            label_visibility="collapsed", placeholder="묶을 구분을 고르세요",
        )

        st.markdown('<div class="pv-lab">값 <span>보여줄 지표 · 순서는 고정</span></div>',
                    unsafe_allow_html=True)
        metrics = st.multiselect(
            "값", METRIC_COLUMNS,
            default=[c for c in (view["values"] or DEFAULT_PIVOT_VALUES)
                     if c in METRIC_COLUMNS],
            format_func=lambda c: COLUMN_LABELS.get(c, c),
            key=f"pvvals_{view_key}", label_visibility="collapsed",
            placeholder="기본 지표 사용",
        )

        left, right = st.columns([5, 3], vertical_alignment="center")
        left.markdown('<div class="pv-lab">필터 <span>좁히기 · 여러 개면 모두 만족'
                      "</span></div>", unsafe_allow_html=True)
        filter_fields = left.multiselect(
            "필터", DIMENSION_COLUMNS,
            default=[f for f in (view["filters"] or {}) if f in DIMENSION_COLUMNS],
            format_func=field_label, key=f"pvfilters_{view_key}",
            label_visibility="collapsed", placeholder="필터 없음 · 전체 소재",
        )
        with right:
            st.markdown('<div class="pv-lab">&nbsp;</div>', unsafe_allow_html=True)
            filter_values = value_popover(view_key, "f", filter_fields,
                                          dict(view["filters"] or {}))

        # **값을 안 고른 필터는 아무것도 걸지 않는다.** 그런데 칩은 그대로 남아 있어서
        # 필터가 걸린 것처럼 보인다(실제로 `Extra Info` 칩이 있는데 표에 epn·6s·new가
        # 다 나오는 화면을 받았다). 무엇이 실제로 걸렸는지 한 줄로 적는다.
        idle = [f for f in filter_fields if not filter_values.get(f)]
        active = [f for f in filter_fields if filter_values.get(f)]
        if active or idle:
            parts = [f"{field_label(f)} <b>{html.escape(', '.join(filter_values[f]))}</b>"
                     for f in active]
            parts += [f'<span class="pv-idle">{field_label(f)} 값 없음 — '
                      "아무것도 걸지 않습니다</span>" for f in idle]
            st.markdown(f'<div class="pv-state">{" · ".join(parts)}</div>',
                        unsafe_allow_html=True)

        st.markdown('<div class="pv-lab">소재 추가 <span>더하기 · 필터 결과에 합친다'
                    "</span></div>", unsafe_allow_html=True)
        include = st.multiselect(
            "소재 추가", ad_options(),
            default=[a for a in (view["include_ads"] or []) if a in set(ad_options())],
            key=f"pvads_{view_key}", label_visibility="collapsed",
            placeholder="필터 결과만 사용 · 손으로 더할 소재가 있으면 고르세요",
        )

    filters = {f: list(filter_values[f]) for f in filter_fields
               if filter_values.get(f)}
    return {**view, "rows": [{"field": f} for f in row_fields],
            "values": list(metrics), "filters": filters,
            "include_ads": list(include)}


@st.cache_data(show_spinner=False)
def _ad_options(month: int, count: int) -> list[str]:
    """소재 이름 목록. 이 달 소재는 300개대라 매 리런마다 정렬하지 않게 캐시한다."""
    return sorted(named_overview["ad"].dropna().astype(str).unique())


def ad_options() -> list[str]:
    return _ad_options(month, len(named_overview))


def views_editor(block_id: str, views: list[dict]) -> list[dict]:
    """이 주제가 담을 표의 목록. 표별 설정은 **표 바로 위**에서 그린다(`render_view`).

    여기서는 표 추가와 기준 라벨만 다룬다.
    """
    state_key = f"views_{block_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = [view_with_defaults(v) for v in views]

    result = [view_with_defaults(v) for v in st.session_state[state_key]]
    st.session_state[state_key] = result
    return result


def add_view_button(block_id: str) -> None:
    """표를 추가한다. **표들이 끝나는 자리**에 그린다 — 새 표가 생기는 곳이 여기다.

    예전에는 이 버튼이 표보다 위에 있어서, 누르면 화면 아래쪽에 표가 생겼다.
    Tableau·시트 편집기도 추가 컨트롤을 삽입 지점에 둔다.
    """
    state_key = f"views_{block_id}"
    if st.button("＋ 표 추가", key=f"vadd_{block_id}"):
        st.session_state[state_key] = (
            list(st.session_state.get(state_key, [])) + [view_with_defaults({})])
        rerun_local()


def merged_note_html(block: dict) -> str:
    """`comment`와 `insight`를 하나의 HTML로 잇는다.

    텍스트 칸을 둘로 나눠 둘 이유가 없다는 피드백을 받아 하나로 합쳤다(2026-09-02).
    **이미 두 칸에 나눠 쓴 내용이 있으므로 버리지 않고 이어 붙인다** — 코멘트 유실은
    이 프로젝트에서 복구 경로가 없는 실패다.

    각 칸을 따로 `to_preview_html`에 통과시킨 뒤 잇는다. 한쪽은 Quill HTML이고 다른
    쪽은 예전 `text_area`의 순수 텍스트일 수 있어서, 먼저 이어 붙이면 그 판별이 깨진다.
    """
    parts = [to_preview_html(block.get(field) or "")
             for field in ("comment", "insight") if (block.get(field) or "").strip()]
    return "".join(parts)


def render_block_kpis(views: list[dict], month: int) -> None:
    """주제 전체의 요약 카드. 표들보다 **위**에 온다.

    카드가 무엇의 합인지가 가장 헷갈리기 쉬운 지점이다 — 이 주제가 담은 표들이 각각
    다른 조건을 걸 수 있으므로, **표들이 다루는 소재의 합집합**으로 계산한다.
    소재 이름으로 합집합을 만든 뒤 원본에서 한 번만 집계하므로 겹쳐도 두 번 세지 않는다.

    기간 비교 뷰는 리포트 월이 아닌 달을 보므로 제외한다 — 섞으면 카드가 어느 기간의
    숫자인지 알 수 없다.
    """
    ads: set[str] = set()
    for view in views:
        if view["kind"] == "compare":
            continue
        # 카드는 **그 주제의 표들이 다루는 소재의 합집합**이다. 표마다 필터가 다를 수
        # 있으므로 소재 이름으로 합집합을 만든 뒤 원본에서 한 번만 집계한다.
        matched = pivot_frame(named_overview, ["ad"], ["cost"],
                              filters=view["filters"],
                              include_ads=view["include_ads"])
        if not matched.empty:
            ads |= set(matched["ad"].unique())
    if not ads:
        return

    scope_of_block = overview[overview["ad"].isin(ads)]
    if scope_of_block.empty:
        return
    summary = aggregate_by(scope_of_block.assign(_all="합계"), ["_all"]).iloc[0]
    kpi_cards([
        {"label": "소재 수", "value": f"{len(ads):,}개",
         "sub": "이 주제가 다루는 소재", "primary": True},
        {"label": "소진액", "value": f"₩{summary['cost']:,.0f}", "sub": "마크업 포함"},
        {"label": "CTR", "value": f"{summary['CTR']:.2%}", "sub": "클릭 ÷ 노출"},
        {"label": "인스톨", "value": f"{summary['total install']:,.0f}", "sub": "Total install"},
        {"label": "CPI", "value": f"₩{summary['CPI']:,.0f}", "sub": "소진 ÷ 인스톨"},
        {"label": "D0 Read CVR", "value": f"{summary['D0 read CVR']:.2%}",
         "sub": "D0 Read ÷ 인스톨"},
    ])


def save_block(block: dict, month: int, views: list[dict], owner: str) -> None:
    """지금 화면의 값으로 이 블록을 저장하고 잠금을 놓는다.

    **모든 값을 위젯 세션에서 읽는다.** `완료` 버튼이 헤더(맨 위)에 있고 편집기는
    표마다 아래에 흩어져 있어서, 반환값으로 모으면 순서에 묶인다. 세션을 읽으면
    어디서 눌러도 화면과 같은 것이 저장된다.
    """
    block_id = block["id"]
    if locks.status(f"block:{block_id}", month, owner, fresh=True).state != "mine":
        st.error("다른 사람이 이 블록을 이어받았습니다. 내용을 복사해 두고 다시 편집하세요.")
        return
    saved = commit_blocks(
        # 화면이 들고 있는 스냅샷이 아니라 저장소의 최신 상태에 이 블록만 덮어쓴다.
        # expect(내가 보고 있던 rev)를 함께 넘겨, 그 사이 같은 블록이 바뀌었으면
        # 덮어쓰지 않고 거부한다.
        month,
        lambda d: report_blocks.update_block(
            d, report_blocks.SLOT_ANALYSIS, block_id,
            title=st.session_state.get(f"blocktitle_{block_id}",
                                       block.get("title", "")),
            views=[view_from_widgets(v, f"{block_id}_{v['id']}") for v in views],
            comment=st.session_state.get(f"comment_{block_id}") or "",
            # 텍스트 칸을 하나로 합쳤으므로 `insight`는 비운다. 필드는 남겨 둔다 —
            # 저장 형식을 지우면 코드를 되돌려도 예전 내용을 다시 못 읽는다.
            insight="",
        ),
        expect={block_id: block.get("_rev", 0)},
    )
    if saved:
        locks.release(f"block:{block_id}", month, owner)
        clear_editor_state(block_id)
        rerun_local()


def render_query_block(block: dict, month: int, edit_mode: bool) -> None:
    """주제 하나. 읽는 순서 = 숫자 → 표 → 해석.

    편집 도구는 그 순서를 깨지 않는 자리에만 놓는다:
      `완료`는 헤더 우측(표가 몇 개든 항상 보인다),
      `＋ 표 추가`는 표들이 끝나는 자리(새 표가 생기는 곳),
      표별 설정은 그 표 바로 위.
    예전에는 `완료`·`＋ 표 추가`·`인사이트`가 전부 표보다 위에 있어서,
    추가 버튼을 눌러도 표는 화면 아래에 생겼다.
    """
    block_id = block["id"]
    owner = st.session_state["editor_token"]
    saved_views = [view_with_defaults(v) for v in (block.get("views") or [])]
    editing = lock_gate(
        block_id, month, block.get("title") or "제목 없는 블록", edit_mode,
        info=f"표 {len(saved_views)}개" if saved_views else "표 없음",
        menu=lambda: block_menu(report_blocks.SLOT_ANALYSIS, block_id, month, owner),
        editable_title=True,
    )

    views = views_editor(block_id, saved_views) if editing else saved_views

    if editing:
        taken_over = editor_taken_over(block_id, month)
        # 완료 = 저장이다. 예전엔 "작성 완료"(잠금만 해제)와 "저장"(내용만 저장)이
        # 따로 있어서, 완료를 먼저 누르면 저장 안 된 글이 그대로 날아갔다.
        _, action = st.columns([6, 1.4], vertical_alignment="center")
        if action.button("완료", type="primary", key=f"save_{block_id}",
                         disabled=taken_over, use_container_width=True):
            save_block(block, month, views, owner)

    if views:
        render_block_kpis(views, month)
    for view in views:
        render_view(view, month, f"sec5_{block_id}", editing=editing)

    if editing:
        add_view_button(block_id)
        st.markdown('<div class="cp-label">인사이트</div>', unsafe_allow_html=True)
        st_quill(value=merged_note_html(block), html=True,
                 toolbar=QUILL_TOOLBAR, key=f"comment_{block_id}")
        return

    body = merged_note_html(block)
    if body:
        # 소제목을 함께 찍는다 — 편집할 때만 `인사이트` 라벨이 보이고 정작
        # 광고주가 보는 화면에는 제목 없는 본문만 떨어져 있었다.
        st.markdown('<div class="insight-head">인사이트</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="note-body">{body}</div>', unsafe_allow_html=True)


# 블록·강조·잠금을 한 번의 호출로 미리 읽어 둔다. 따로 읽으면 조작 한 번에 시트 조회가
# 2~3회 나가고, 그 곱하기 사람 수가 분당 60회 한도를 넘긴다(6명 동시 사용 시 실측 초과).
# 저장 경로는 이 캐시를 쓰지 않는다 — 늘 최신을 다시 읽고 rev를 대조한다.
prefetch.warm(month)

blocks_state = report_blocks.load_state(month, use_cache=True)
page_blocks = blocks_state.data
# 읽기 자체가 실패했으면(권한·네트워크·깨진 행) 빈 리포트를 조용히 보여주면 안 된다.
# 그 상태로 편집·저장을 허용하면 남아 있던 내용을 빈 값으로 덮어쓸 수 있다.
blocks_unavailable = blocks_state.status == "error"
# 파일이 깨져 있었다면 지우지 않고 옆에 치워둔 상태다. 조용히 빈 화면을 보여주면 사용자가
# 눈치채지 못한 채 새로 저장해서 복구 기회를 날린다.
_corrupt = report_blocks.pop_corruption(month)
analysis_blocks = page_blocks[report_blocks.SLOT_ANALYSIS]

# 편집 상태는 블록마다 자기 헤더에 이미 표시되므로(편집 중 · 나 / 다른 사람이 편집 중),
# 섹션 배지에 또 요약하지 않는다 — 중복이다.
section(
    "4", "신규 소재 유형별 성과",
    "분석 주제를 하나 만들고, 그 안에 필요한 표를 여러 개 붙입니다. 소재명 규칙"
    "(작품코드_작품명_Creative Format_제작주체_Creative Type_Dimension_USP_Extra Info)을 "
    "자동 분해해 집계하며, 규칙에 맞지 않는 소재명은 추정하지 않고 '미분류'로 남깁니다.",
    hint=True,
)

# 예전 4번 섹션에 있던 수동 분류 패널을 이리로 옮겼다. 블록별로 두면 블록이 하나도
# 없을 때 미분류를 고칠 곳이 사라진다. 저장소는 이 달 전체가 공유하므로 한 군데면 충분하다.
#
# **보기 모드에서는 감춘다** — 이 화면은 광고주에게 그대로 공유하는 리포트이고,
# 소재 분류를 고치는 도구는 리포트의 일부가 아니다. 예전에는 "분류 보정은 데이터 교정이라
# 항상 노출"로 뒀는데, 광고주 화면에 편집 도구가 보이는 게 더 큰 문제다.
# 분류가 실패한 소재가 실제로 있을 때만 보여준다.
# 실측(2026-09-02): 하이픈 파서를 고친 뒤 8월은 분류 실패가 0개, 7월은 1개다.
# 늘 펼쳐 두면 아무 할 일도 없는 패널이 섹션 맨 위를 차지한다. 그렇다고 지우면
# 소재명이 컨벤션을 벗어났을 때의 **유일한 교정 경로**가 없어진다.
CLASSIFY_COLUMNS = ["creative_type", "format", "size", "producer_group", "usp"]
_unclassified = named_overview.drop_duplicates("ad")
_unclassified = _unclassified[
    _unclassified[[c for c in CLASSIFY_COLUMNS if c in _unclassified.columns]]
    .isna().any(axis=1)
]
if edit_mode and not _unclassified.empty:
    status_row("warn", f"소재명 규칙에 맞지 않는 소재 {len(_unclassified)}개",
               "아래에서 분류를 손으로 채우면 이 달의 모든 표에 반영됩니다.")
    render_manual_override_panel(
        month, True, set(named_overview["ad"].unique()), key_prefix="sec4_override",
        options=override_choices,
    )

if blocks_unavailable:
    st.error(
        f"{month}월 블록을 읽지 못했습니다 — {blocks_state.reason}. "
        "지금은 저장하지 마세요(빈 값으로 덮어쓸 수 있습니다). 새로 고쳐 다시 시도해 주세요."
    )

if _corrupt:
    st.error(
        f"{month}월 블록 파일이 손상되어 읽지 못했습니다. 원본은 `{_corrupt}` 로 옮겨 두었으니 "
        "복구가 필요하면 이 파일을 확인해 주세요."
    )

if not analysis_blocks:
    st.caption("아직 분석 블록이 없습니다.")

# 블록 사이사이(맨 앞·맨 뒤 포함)에 얇은 "+" 줄을 둔다 — 노션처럼 원하는 자리에 바로
# 끼워 넣을 수 있게. 편집 모드가 꺼져 있으면 고객사 화면이라 아예 그리지 않는다.
if blocks_unavailable:
    edit_mode = False

# 블록 목록을 fragment로 감싼다(2026-08-29). 블록을 추가·삭제하면 Streamlit이 스크립트
# 전체를 다시 돌려 표 7개와 하이라이트 카드까지 통째로 다시 그렸다 — 저장 자체를 2.3초에서
# 1.5초로 줄여도 체감이 안 되던 이유다(실제 피드백). fragment 안의 버튼은 그 함수만 다시
# 실행한다. 월·필터처럼 데이터가 바뀌는 조작은 fragment 밖이라 종전대로 전체가 돈다.
@st.fragment
def _analysis_blocks_section() -> None:
    # fragment가 다시 돌 때는 **여기서 상태를 새로 읽어야 한다.**
    # 바깥에서 한 번 읽어둔 목록을 그대로 쓰면 각 블록의 rev가 화면 기준으로 낡아,
    # 혼자 쓰는데도 저장이 "다른 사람이 방금 수정했습니다"로 거부된다(2026-08-29 실제
    # 발생). rev 대조는 유실을 막는 장치라 끄면 안 되고, 대신 기준을 최신으로 맞춘다.
    blocks = report_blocks.load_state(month, use_cache=True).data[
        report_blocks.SLOT_ANALYSIS
    ]
    if edit_mode:
        insert_block_row(report_blocks.SLOT_ANALYSIS, 0, "creative_query", "새 분석 주제")
    for index, block in enumerate(list(blocks)):
        render_query_block(block, month, edit_mode)
        if edit_mode:
            insert_block_row(
                report_blocks.SLOT_ANALYSIS, index + 1, "creative_query", "새 분석 주제"
            )


_analysis_blocks_section()

# --------------------------------------------------------------------------- 6. 작품별

section("5", "작품별 성과")

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


def render_pasted_table(table: pd.DataFrame) -> None:
    """NEXT STEP에 붙여넣은 표를 다른 표와 같은 모양(HTML)으로 그린다.

    값은 사용자가 붙여넣은 문자열 그대로 쓴다 — 지표 서식(FORMATS)을 적용하지 않는다.
    머리글이 우연히 '소진액' 같은 이름이어도 이미 서식이 들어간 문자열이라 다시 포맷하면
    깨진다. 첫 컬럼만 좌측 정렬한다(보통 소재명·항목명이 온다).
    """
    headers = [str(name) for name in table.columns]
    rows = [
        ["" if value is None else str(value) for value in record]
        for record in table.itertuples(index=False, name=None)
    ]
    report_table(
        rows, headers,
        left_columns={headers[0]} if headers else set(),
    )


def render_note_block(block: dict, month: int, edit_mode: bool) -> None:
    """자유 노트 블록 — 5번 분석 블록과 같은 잠금·조작 UI를 두르고, 본문은 기존 NEXT STEP의
    에디터/이미지/표 UI를 그대로 옮긴다. 위젯 키는 전부 block_id를 섞어 블록끼리 상태가
    안 섞이게 한다.
    """
    block_id = block["id"]
    owner = st.session_state["editor_token"]
    editing = lock_gate(
        block_id, month, block.get("title") or "노트", edit_mode,
        menu=lambda: block_menu(report_blocks.SLOT_NEXT_STEP, block_id, month, owner),
    )

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
                # 저장 직전에는 캐시를 믿지 않는다 — 그 사이 남이 이어받았을 수 있다.
                if locks.status(
                    f"block:{block_id}", month, owner, fresh=True
                ).state != "mine":
                    st.error("다른 사람이 이 블록을 이어받았습니다. 내용을 복사해 두고 다시 편집하세요.")
                else:
                    images = list(block.get("images", []))
                    for item in uploaded or []:
                        images.append(save_image(month, item.name, item.getvalue()))

                    tables = list(block.get("tables", []))
                    if pasted and pasted.strip():
                        tables.append(pasted)

                    if commit_blocks(
                        month,
                        lambda d: report_blocks.update_block(
                            d, report_blocks.SLOT_NEXT_STEP, block_id,
                            title=title_value, comment=draft_markdown or "",
                            images=images, tables=tables,
                            image_max_height=image_max_height,
                        ),
                        expect={block_id: block.get("_rev", 0)},
                    ):
                        st.session_state.pop(f"attach_nonce_{block_id}", None)
                        locks.release(f"block:{block_id}", month, owner)
                        clear_editor_state(block_id)
                        rerun_local()

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
                            remaining_images = [i for i in block["images"] if i != stored]
                            # 먼저 블록에서 참조를 끊고, 저장이 성공했을 때만 실제 파일을
                            # 지운다. 순서를 뒤집으면 저장이 거부됐을 때 블록은 여전히
                            # 그 이미지를 가리키는데 실물이 없어 빈칸이 남는다.
                            if commit_blocks(
                                month,
                                lambda d: report_blocks.update_block(
                                    d, report_blocks.SLOT_NEXT_STEP, block_id,
                                    images=remaining_images,
                                ),
                                expect={block_id: block.get("_rev", 0)},
                            ):
                                delete_image(stored)
                                rerun_local()

                    for index in range(len(block.get("tables", []))):
                        label, action = st.columns([3.9, 1.6], vertical_alignment="center")
                        label.markdown(
                            f'<div class="ns-att">표 {index + 1}</div>', unsafe_allow_html=True
                        )
                        if action.button("삭제", key=f"del_tbl_{block_id}_{index}",
                                         width="stretch"):
                            remaining = [t for i, t in enumerate(block["tables"]) if i != index]
                            if commit_blocks(
                                month,
                                lambda d: report_blocks.update_block(
                                    d, report_blocks.SLOT_NEXT_STEP, block_id,
                                    tables=remaining,
                                ),
                                expect={block_id: block.get("_rev", 0)},
                            ):
                                rerun_local()
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
                render_pasted_table(table)


next_step_blocks = page_blocks[report_blocks.SLOT_NEXT_STEP]

section("6", "NEXT STEP")
if not next_step_blocks:
    st.caption("아직 작성된 내용이 없습니다.")

@st.fragment
def _next_step_blocks_section() -> None:
    # 5번과 같은 이유로 여기서 새로 읽는다(낡은 rev로 저장이 거부되는 것을 막는다).
    blocks = report_blocks.load_state(month, use_cache=True).data[
        report_blocks.SLOT_NEXT_STEP
    ]
    if edit_mode:
        insert_block_row(report_blocks.SLOT_NEXT_STEP, 0, "note", "다음 달 액션")
    for index, block in enumerate(list(blocks)):
        render_note_block(block, month, edit_mode)
        if edit_mode:
            insert_block_row(
                report_blocks.SLOT_NEXT_STEP, index + 1, "note", "다음 달 액션"
            )


_next_step_blocks_section()

footnote(
    "집계 기준 — 이 리포트의 모든 수치는 Media_RAW 중 UA(신규 유입) 집행분만 합산한 "
    "값입니다. 리타겟팅(non-UA)은 제외되므로 Media_RAW 전체 합계와는 다를 수 있습니다. "
    "지표 정확도 — 소진액·노출·클릭·설치·열람·코인은 그 범위의 원본 합계(정확). "
    "CTR/CPC/CPI/CVR은 그 합계에서 계산한 값(정확). "
    "기존 시트 피벗의 'D0 read CVR' 값과는 차이가 있을 수 있습니다 "
    "(시트 쪽 분모가 원본으로 재현되지 않음 — 분자·분모 자체는 원본과 일치)."
)
