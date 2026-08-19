"""대시보드 디자인 시스템 — 네이버웹툰 브랜드 기준.

고객사(네이버웹툰 대만)에 직접 공유하는 리포트라, 장식보다 **정보 위계와 가독성**을 우선한다.
- 브랜드 그린(#00DC64)은 강조 한 곳에만 쓰고 나머지는 중성 회색조로 간다(액센트 1개 원칙).
- 숫자는 전부 tabular-nums로 자릿수를 맞춘다 — 표가 많은 화면이라 이게 인상을 좌우한다.
- 섹션/카드에 이모지를 쓰지 않는다. 번호와 타이포 위계로 구분한다.
"""

from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

import streamlit as st

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "webtoon_logo.png"

BRAND = "#00DC64"

# 상태 색 — 브랜드 그린과 부딪히지 않게 채도를 낮춘 계열로만 쓴다.
TONES = {
    "neutral": ("#d4d8dd", "#f7f8f9", "#1a1d21"),
    "good": ("#00b855", "#eefaf3", "#04703a"),
    "warn": ("#d9a021", "#fdf8ec", "#8a5d05"),
    "bad": ("#d95757", "#fdf1f1", "#9b2c2c"),
    "info": ("#5b7083", "#f2f5f8", "#2b3a45"),
}


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    return f"data:image/png;base64,{encoded}"


CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');

:root {
  --brand: #00DC64;
  --brand-deep: #00A94C;
  --ink: #14171a;
  --ink-2: #3d4650;
  --muted: #6b7681;
  --faint: #97a1ac;
  --line: #e6e9ec;
  --line-soft: #f0f2f4;
  --surface: #ffffff;
  --bg: #ffffff;
}

html, body, [class*="css"], .stApp {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont,
               'Segoe UI', 'Malgun Gothic', sans-serif;
  font-feature-settings: 'tnum' 1, 'case' 1;
}

.stApp { background: var(--bg); }
.block-container {
  padding-top: 1.1rem; padding-bottom: 5rem;
  max-width: 1560px;
}
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

/* 숫자는 전부 자릿수 고정 — 표가 많은 화면이라 정렬감이 인상을 좌우한다 */
[data-testid="stDataFrame"], .kpi-v, .meta-v { font-variant-numeric: tabular-nums; }

/* ------------------------------------------------------------ 리포트 헤더 */
.rpt-head {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 26px 30px 26px 30px;
  margin-bottom: 22px;
  box-shadow: 0 2px 6px rgba(20, 23, 26, .07);
}
.rpt-top { display: flex; align-items: flex-start; gap: 22px; }
.rpt-logo { width: 42px; height: 42px; flex: 0 0 42px; margin-top: 2px; }
.rpt-logo img { width: 100%; height: 100%; object-fit: contain; display: block; }
.rpt-titles { flex: 1 1 auto; min-width: 0; }
.rpt-kicker {
  font-size: 11.5px; font-weight: 700; letter-spacing: .13em;
  color: var(--brand-deep); text-transform: uppercase; margin-bottom: 7px;
}
.rpt-h1 {
  font-size: 27px; font-weight: 800; color: var(--ink);
  letter-spacing: -.035em; line-height: 1.25; margin: 0;
}
.rpt-sub {
  font-size: 13px; color: var(--muted); margin-top: 8px;
  line-height: 1.65; max-width: 78ch;
}
.rpt-stamp { flex: 0 0 auto; text-align: right; padding-top: 2px; }
.rpt-stamp-k {
  font-size: 10.5px; font-weight: 700; color: var(--faint);
  letter-spacing: .1em; text-transform: uppercase; margin-bottom: 5px;
}
.rpt-stamp-v {
  font-size: 14px; font-weight: 700; color: var(--ink-2);
  font-variant-numeric: tabular-nums; letter-spacing: -.01em;
}
.rpt-stamp-v + .rpt-stamp-k { margin-top: 13px; }

/* 아젠다 — 제목 바로 아래, 장식 없이 번호 + 문구만 */
.rpt-agenda { display: flex; flex-wrap: wrap; gap: 20px; margin-top: 12px; }
.rpt-agenda-item { display: flex; align-items: baseline; gap: 7px; }
.rpt-agenda-n {
  font-size: 12px; font-weight: 800; color: var(--brand-deep);
  font-variant-numeric: tabular-nums;
}
.rpt-agenda-t { font-size: 13.5px; font-weight: 600; color: var(--ink-2); }

/* ------------------------------------------------------------ 섹션 헤더 */
.sec {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 20px; margin: 40px 0 18px 0; padding-bottom: 11px;
  border-bottom: 1px solid var(--ink);
}
.sec-l { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
/* 번호는 제목과 같은 급으로 키우되 무게는 낮춰서 — 작고 굵으면 얼룩처럼 보인다.
   가는 세로선으로 제목과 갈라 편집 디자인의 챕터 표기처럼 읽히게 한다. */
.sec-n {
  font-size: 16px; font-weight: 500; color: var(--brand-deep);
  font-variant-numeric: tabular-nums; letter-spacing: 0; flex: 0 0 auto;
  display: flex; align-items: center; gap: 12px;
}
.sec-n::after {
  content: ""; width: 1px; height: 13px; background: var(--line);
  display: inline-block;
}
.sec-t {
  font-size: 18px; font-weight: 650; color: var(--ink); letter-spacing: -.022em;
}
.sec-badge {
  flex: 0 0 auto; font-size: 11.5px; font-weight: 600; color: var(--ink-2);
  background: var(--line-soft); border-radius: 3px; padding: 4px 10px;
}
.sec-d {
  font-size: 12.5px; color: var(--muted); line-height: 1.65;
  margin: 0 0 16px 0; max-width: 96ch;
}
/* 섹션 설명을 매번 노출하는 대신 "?" 아이콘 뒤에 숨긴다(hint=True인 섹션용).
   커스텀 어두운 카드 툴팁 — 네이티브 title 속성은 지연·기본폰트라 리포트 톤과 안 맞아서
   순수 CSS(:hover)로 직접 그린다(참고 레퍼런스 스타일). */
.sec-hint-wrap { position: relative; display: inline-flex; }
.sec-hint {
  display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%; border: 1px solid var(--faint);
  color: var(--faint); font-size: 10px; font-weight: 700; cursor: help;
  flex: 0 0 auto; user-select: none;
}
.sec-hint-wrap:hover .sec-hint { border-color: var(--brand-deep); color: var(--brand-deep); }
.sec-hint-pop {
  position: absolute; left: 0; top: calc(100% + 10px); z-index: 30;
  width: max-content; max-width: 300px;
  background: #1c2024; color: #f3f5f7; font-size: 12px; font-weight: 500;
  line-height: 1.6; letter-spacing: -.005em; padding: 10px 13px;
  border-radius: 7px; box-shadow: 0 8px 20px rgba(20, 23, 26, .2);
  opacity: 0; visibility: hidden; transform: translateY(-4px);
  transition: opacity .14s ease, transform .14s ease; pointer-events: none;
}
.sec-hint-pop::before {
  content: ""; position: absolute; top: -4px; left: 11px;
  width: 8px; height: 8px; background: #1c2024; transform: rotate(45deg);
  border-radius: 1.5px;
}
.sec-hint-wrap:hover .sec-hint-pop {
  opacity: 1; visibility: visible; transform: translateY(0);
}
/* 섹션 안 표 하나를 소개하는 작은 제목 — 섹션 헤더(밑줄)와 같은 위계 언어를
   한 단계 축소해 쓴다. 왼쪽 브랜드 바로 "표 제목"임을 표시한다. */
.tbl-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 13.5px; font-weight: 700; color: var(--ink);
  letter-spacing: -.01em; margin: 22px 0 10px 0;
}
.tbl-title-bar {
  width: 3px; height: 13px; border-radius: 1px;
  background: var(--brand); flex: 0 0 auto;
}

/* ------------------------------------------------------------ KPI */
.kpis {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 0; background: var(--surface);
  border: 1px solid var(--line); border-radius: 4px; overflow: hidden;
  margin-bottom: 8px;
  box-shadow: 0 2px 6px rgba(20, 23, 26, .07);
}
.kpi {
  padding: 17px 20px 18px 20px;
  border-right: 1px solid var(--line-soft);
  border-top: 2px solid transparent;
}
.kpi:last-child { border-right: 0; }
.kpi.is-primary { border-top-color: var(--brand); }
.kpi-l {
  font-size: 11px; color: var(--muted); font-weight: 700;
  letter-spacing: .05em; margin-bottom: 8px;
}
.kpi-v {
  font-size: 24px; font-weight: 800; color: var(--ink);
  line-height: 1.1; letter-spacing: -.04em;
}
.kpi-s { font-size: 11px; color: var(--faint); margin-top: 7px; }

/* ------------------------------------------------------------ 상태 행 */
.row {
  display: flex; align-items: flex-start; gap: 11px;
  border-left: 3px solid var(--accent); background: var(--soft);
  border-radius: 0 3px 3px 0; padding: 11px 15px; margin-bottom: 7px;
}
.row-t { font-size: 12.5px; font-weight: 700; color: var(--ink); }
.row-d { font-size: 12px; color: var(--ink-2); margin-top: 3px; line-height: 1.6; }
.row-d code { background: rgba(0,0,0,.05); padding: 1px 4px; border-radius: 2px; }

/* NEXT STEP 본문 — Quill이 뱉는 <p>는 기본 여백이 커서 줄바꿈마다 크게 벌어진다 */
/* 코멘트 본문 — 표(데이터)와 성격이 다른 '사람이 쓴 해석'이라는 게 드러나야 한다.
   배경에 그냥 얹으면 표 아래 텍스트와 구분이 안 된다는 피드백을 받아, 왼쪽 브랜드 라인과
   아주 옅은 배경으로 위계만 준다(리포트 톤을 해치지 않을 만큼만). */
/* 코멘트 본문 — 표(데이터)와 성격이 다른 '사람이 쓴 해석'이라는 게 드러나야 한다.
   왼쪽 라인 방식 대신 다른 카드(kpi 등)와 같은 표면 규칙(흰 배경+테두리+그림자)의
   카드로 통일한다 — 리포트 안에서 카드가 하나의 일관된 언어로 읽히게 하기 위해서다. */
.note-body {
  font-size: 13.5px; color: var(--ink-2); line-height: 1.65;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 4px; padding: 15px 18px; margin: 12px 0;
}
.note-body p { margin: 0 0 3px 0; }
.note-body p:has(> br:only-child) { margin: 0; height: 9px; }  /* 빈 줄은 작은 간격으로 */
.note-body h1, .note-body h2 { font-size: 16.5px; font-weight: 800; color: var(--ink);
  margin: 16px 0 6px 0; letter-spacing: -.02em; }
.note-body h3 { font-size: 14.5px; font-weight: 800; color: var(--ink); margin: 13px 0 5px 0; }
.note-body ul, .note-body ol { margin: 4px 0 8px 0; padding-left: 1.15em; }
.note-body li { margin: 1px 0; }
.note-body blockquote {
  border-left: 3px solid var(--brand); background: #f7fdfa;
  margin: 8px 0; padding: 7px 12px; color: var(--ink-2);
}
.note-body pre, .note-body code {
  background: #f2f5f8; border-radius: 3px; font-size: 12.5px; padding: 1px 5px;
}
.note-body a { color: var(--brand-deep); }
/* 이미지는 폭이 아니라 높이로 제한한다 — 세로로 긴 그림이 화면을 잡아먹는 걸 막으면서,
   가로로 긴 레퍼런스는 폭을 다 쓰게 둔다. 높이 값은 NEXT STEP 편집 탭에서 직접 조절 가능. */
.note-body img, .note-figure img { max-width: 100%; height: auto; border-radius: 3px;
  display: block; margin: 8px 0; }

/* NEXT STEP 편집 영역 — 컨트롤이 흩어져 보이지 않게 라벨·첨부 목록을 정돈한다 */
.ns-label {
  font-size: 11px; font-weight: 800; color: var(--faint);
  letter-spacing: .1em; text-transform: uppercase;
  margin: 2px 0 7px 0;
}
.ns-att {
  font-size: 12px; color: var(--ink-2); font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ns-thumb {
  width: 38px; height: 38px; object-fit: cover;
  border-radius: 3px; border: 1px solid var(--line); display: block;
}
/* 소재 조회 조건 바 — 기본 위젯을 그대로 쌓으면 여백이 뜨고 라벨이 둔탁하다 */
/* 블록 사이 삽입 자리 — 점선 박스로 "여기에 넣는다"를 분명히 한다. 아이콘만 옅게 두면
   섹션 구분선에 붙어 잘린 것처럼 보였다(실제 피드백). 위아래 여백으로 블록과 떼어 놓는다. */
[class*="st-key-insert_analysis_"], [class*="st-key-insert_next_step_"] {
  margin: 14px 0 !important;
}
[class*="st-key-insert_analysis_"] button, [class*="st-key-insert_next_step_"] button {
  border: 1px dashed var(--line) !important; background: transparent !important;
  color: var(--faint) !important; border-radius: 4px !important;
  min-height: 34px !important; font-size: 12px !important; font-weight: 500 !important;
}
[class*="st-key-insert_analysis_"] button:hover, [class*="st-key-insert_next_step_"] button:hover {
  border-color: var(--brand) !important; color: var(--brand-deep) !important;
  background: #f6fdfa !important;
}
.st-key-drill_panel {
  background: #fbfcfd; border-color: var(--line) !important;
  padding: 10px 14px 8px !important; margin-top: 4px;
}
.st-key-drill_panel [data-testid="stVerticalBlock"] { gap: 4px !important; }
/* 조건 행마다 얇은 구분선 — 마지막 줄(조건 추가/조회)에는 넣지 않는다 */
.st-key-drill_panel [data-testid="stHorizontalBlock"] {
  border-bottom: 1px solid var(--line-soft); padding-bottom: 5px;
}
.st-key-drill_panel [data-testid="stHorizontalBlock"]:last-of-type {
  border-bottom: none; padding-bottom: 0;
}
/* 섹션 제목과 조회 결과가 한 덩어리로 읽히도록 패널 앞뒤 여백을 줄인다 */
.st-key-drill_panel + div [data-testid="stElementContainer"] { margin-top: 2px; }
/* 조건 행 컨트롤 자체도 낮춘다 — 기본 높이(40px)면 두 줄만 돼도 패널이 길어진다 */
.st-key-drill_panel [data-baseweb="select"] > div { min-height: 32px !important; }
.st-key-drill_panel [data-testid="stElementContainer"] { margin: 0 !important; }
.st-key-drill_panel .stButton button { min-height: 30px !important; }
/* 행 삭제(✕)와 조건 추가는 보조 동작이라 테두리 없이 흐리게 */
[class*="st-key-drill_drop_"] button, .st-key-drill_add button {
  border: none !important; background: transparent !important;
  color: var(--muted) !important; padding: 2px 6px !important; min-height: 28px !important;
}
[class*="st-key-drill_drop_"] button:hover { color: var(--ink) !important; }
.st-key-drill_add button { color: var(--brand-deep) !important; font-weight: 600 !important; }
.st-key-drill_panel [data-baseweb="select"] > div {
  background: #fff !important; border-radius: 3px !important;
}
/* 값 선택 칩은 구분자 칩보다 한 단계 약하게 — 위계가 보이도록 */
[class*="st-key-drill_values_"] [data-baseweb="tag"] {
  background: #eef1f3 !important; color: var(--ink) !important;
}
/* 블록 헤더 — 제목 + 얇은 밑줄, 오른쪽은 잠금 상태 자리 */
/* 보기/편집 모드 스위치 — 헤더 바로 아래 우측, 항상 눈에 띄어야 하는 컨트롤이라
   선택된 "편집" 쪽만 브랜드 그린으로 채운다(액센트 1곳 원칙 — 나머지 UI는 중성색 유지) */
/* 4번 비교 지표 세그먼트도 같은 규칙을 쓴다 — Streamlit 기본 선택색(빨강)이 리포트의
   액센트 1색 원칙을 깨기 때문에 브랜드 그린으로 덮는다. */
.st-key-mode_toggle button[role="radio"][aria-checked="true"],
.st-key-sec4_metric button[role="radio"][aria-checked="true"] {
  background: var(--brand) !important; border-color: var(--brand) !important;
}
.st-key-mode_toggle button[role="radio"][aria-checked="true"] p,
.st-key-sec4_metric button[role="radio"][aria-checked="true"] p {
  color: #fff !important;
}

/* 조건 패널 — "이 조건이 무엇에 걸리는지"가 편집 중에도 바로 보이게 라벨·실시간 요약을 붙인다 */
.cp-label {
  font-size: 11px; font-weight: 700; color: var(--muted);
  letter-spacing: .04em; margin-bottom: 8px;
}
.cp-summary {
  font-size: 12.5px; color: var(--ink-2); margin: 10px 0 2px 0;
}
.cp-summary b { color: var(--brand-deep); font-variant-numeric: tabular-nums; }
.cp-hint {
  font-size: 11.5px; color: var(--faint); margin-top: 4px;
}

/* 셀렉트박스 옆에 나란히 놓는 수동 분류 expander 정렬용 — 셀렉트박스 라벨 높이만큼 비워
   expander 상자 윗변이 selectbox 입력 상자와 같은 줄에 맞게 한다. */
.cp-override-spacer { height: 1.7rem; }

.nh {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--line-soft);
  margin: 6px 0 10px 0;
}
.nh-t { font-size: 16.5px; font-weight: 600; color: var(--ink); letter-spacing: -.02em; }
.nh-right { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.nh-badge { font-size: 11.5px; border-radius: 3px; padding: 3px 9px; white-space: nowrap; }
.nh-badge.is-mine { background: #e7f9f0; color: #0f6e56; }
.nh-badge.is-other { background: #faeeda; color: #854f0b; }
.nh-badge.is-info { background: var(--line-soft); color: var(--ink-2); }
/* 첨부 삭제 버튼: 우측 레일이 좁아 기본 버튼은 글자가 세로로 접힌다 */
[class*="st-key-del_img_"] button, [class*="st-key-del_tbl_"] button {
  white-space: nowrap !important; padding: 2px 6px !important;
  min-height: 26px !important; font-size: 11.5px !important;
}
/* 기본 업로더 드롭존은 리포트 화면에서 혼자 크고 둔탁하다 — 높이를 줄인다 */
[data-testid="stFileUploaderDropzone"] {
  padding: 10px 12px !important; min-height: 0 !important;
  background: #f7f9fa !important; border-color: var(--line) !important;
  border-radius: 3px !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] span { font-size: 11.5px !important; }
[data-testid="stFileUploaderDropzoneInstructions"] small { display: none !important; }
/* 슬라이더 기본색이 빨강이라 브랜드와 부딪힌다 */
.stSlider [data-baseweb="slider"] div[role="slider"] { background-color: var(--brand) !important; }
.stSlider [data-testid="stSliderTickBarMin"],
.stSlider [data-testid="stSliderTickBarMax"] { font-size: 10.5px !important; }
.stSlider [data-testid="stThumbValue"] { color: var(--brand-deep) !important; font-weight: 800; }

/* Quill 에디터 테두리를 다른 카드와 같은 규칙으로 */
.ql-toolbar.ql-snow, .ql-container.ql-snow { border-color: var(--line) !important; }
.ql-toolbar.ql-snow { border-radius: 3px 3px 0 0; background: #f7f9fa; }
.ql-container.ql-snow { border-radius: 0 0 3px 3px; }

/* ------------------------------------------------------------ 칩 */
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 12px 0; }
.chip {
  font-size: 11.5px; font-weight: 600; padding: 4px 9px; border-radius: 3px;
  background: var(--surface); color: var(--ink-2); border: 1px solid var(--line);
}

/* ------------------------------------------------------------ 표 / 차트 */
div[data-testid="stDataFrame"] {
  border: 1px solid var(--line); border-radius: 4px;
  overflow: hidden; background: var(--surface);
}
div[data-testid="stDataFrame"] th {
  background: #f5f7f8 !important; font-weight: 700 !important;
  color: var(--ink-2) !important; font-size: 11.5px !important;
  letter-spacing: .01em;
}
div[data-testid="stDataFrame"] td { font-size: 12px !important; }

.stPlotlyChart {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 4px; padding: 6px;
}

/* Streamlit 기본 알림이 브랜드 팔레트와 부딪혀서 톤을 낮춘다 */
div[data-testid="stAlert"] {
  border-radius: 3px; border-left-width: 3px; font-size: 12.5px;
}

h6 {
  font-size: 12px !important; font-weight: 800 !important;
  color: var(--ink-2) !important; letter-spacing: .02em;
  margin: 22px 0 8px 0 !important;
}

/* ------------------------------------------------------------ 위젯 */
section[data-testid="stSidebar"] {
  background: var(--surface); border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] h2 {
  font-size: 10.5px !important; font-weight: 800 !important;
  color: var(--faint) !important; letter-spacing: .12em;
  text-transform: uppercase; margin-top: 22px !important;
}
/* 사이드바 접기/펼치기 버튼 — Streamlit 기본값은 hover해야 나타나서 있는 줄도 모른다.
   항상 보이는 버튼으로 고정한다(접었을 때 다시 여는 버튼도 같이). */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] {
  visibility: visible !important;
  opacity: 1 !important;
  display: flex !important;
}
.stApp [data-testid="stSidebarCollapseButton"] button[data-testid="stBaseButton-headerNoPadding"],
.stApp [data-testid="stSidebarCollapsedControl"] button[data-testid="stBaseButton-headerNoPadding"] {
  background-color: #ffffff !important;
  border-width: 1px !important;
  border-style: solid !important;
  border-color: #e6e9ec !important;
  border-radius: 3px !important;
  color: var(--ink-2) !important;
  width: 30px !important; height: 30px !important;
  box-shadow: 0 1px 2px rgba(20, 23, 26, .06) !important;
  transition: border-color .18s ease, background-color .18s ease, color .18s ease;
}
.stApp [data-testid="stSidebarCollapseButton"] button[data-testid="stBaseButton-headerNoPadding"]:hover,
.stApp [data-testid="stSidebarCollapsedControl"] button[data-testid="stBaseButton-headerNoPadding"]:hover {
  border-color: #00DC64 !important;
  background-color: #f2fdf7 !important;
  color: #00A94C !important;
}
/* 접힌 상태에서 다시 여는 버튼은 본문 위에 떠 있으므로 조금 더 눈에 띄게 */
[data-testid="stSidebarCollapsedControl"] { z-index: 20; }

.sb-brand {
  display: flex; align-items: center; gap: 9px;
  padding-bottom: 14px; border-bottom: 1px solid var(--line); margin-bottom: 4px;
}
.sb-brand img { width: 26px; height: 26px; object-fit: contain; }
.sb-brand-t { font-size: 13px; font-weight: 800; color: var(--ink); letter-spacing: -.02em; }
.sb-brand-s { font-size: 11px; color: var(--muted); margin-top: 1px; }

/* 사이드바 metric(구글 파일 수) 크기는 아래 데이터 카드 규칙에서 한 번에 정한다 —
   여기서 또 지정하면 셀렉터가 더 구체적이라 카드 규칙을 눌러버린다(실제로 그랬다). */

/* 사이드바 카드 — 성격이 다른 것들(매번 만지는 컨트롤 / 출처 정보)을 카드로 갈라 놓는다.
   한 줄로 이어 놓으면 헤더·metric·caption이 뒤섞여 금방 산만해진다(실제 피드백). */
.st-key-sb_controls, .st-key-sb_data {
  background: #f7f9fa; border: 1px solid var(--line-soft) !important;
  border-radius: 6px; padding: 12px 12px 4px 12px !important; margin-bottom: 10px;
}
.st-key-sb_controls [data-testid="stVerticalBlock"],
.st-key-sb_data [data-testid="stVerticalBlock"] { gap: 4px !important; }
/* 카드 안의 입력은 흰색으로 띄워 배경과 구분한다 */
.st-key-sb_data [data-baseweb="input"], .st-key-sb_data [data-baseweb="base-input"] {
  background: #fff !important;
}
/* 라벨 표기를 한 가지로 통일한다 — 예전엔 header/metric/caption이 제각각이었다 */
.sb-lab {
  font-size: 10.5px; font-weight: 700; color: var(--muted);
  letter-spacing: .06em; margin: 6px 0 4px 0;
}
.sb-card-t {
  font-size: 11px; font-weight: 700; color: var(--ink-2);
  letter-spacing: .04em; margin-bottom: 8px;
}
.sb-sub {
  font-size: 10.5px; font-weight: 700; color: var(--muted); letter-spacing: .06em;
  margin: 14px 0 4px 0; padding-top: 10px; border-top: 1px solid var(--line);
}
/* 카드 안 위젯 라벨·캡션·metric을 sb-lab과 같은 급으로 낮춘다 — 크기가 제각각이면
   카드로 묶어도 여전히 산만해 보인다 */
.st-key-sb_controls [data-testid="stWidgetLabel"] p,
.st-key-sb_data [data-testid="stWidgetLabel"] p {
  font-size: 10.5px !important; font-weight: 700 !important;
  color: var(--muted) !important; letter-spacing: .06em;
}
.st-key-sb_data [data-testid="stCaptionContainer"] p {
  font-size: 10.5px !important; color: var(--faint) !important;
}
.st-key-sb_data [data-testid="stMetricValue"] {
  font-size: 15px !important; font-weight: 700 !important;
}
.st-key-sb_data [data-testid="stMetricLabel"] p {
  font-size: 10.5px !important; font-weight: 700 !important;
  color: var(--muted) !important; letter-spacing: .06em;
}
.st-key-sb_data input, .st-key-sb_data [data-testid="stExpander"] summary p {
  font-size: 12px !important;
}
/* "다시 불러오기" 류 — 사이드바에서 항상 눈에 띄어야 하는 필터·모드 토글과 달리
   가끔 누르는 보조 동작이라, 검은 글씨의 진한 기본 버튼 대신 옆 입력창과 같은 옅은
   회색 배경 + 중간톤 글자로 조용하게 앉힌다. 호버 시에만 브랜드 그린으로 살아난다
   (전역 .stButton button:hover 규칙 그대로 사용). */
.st-key-sb_data .stButton button {
  font-size: 12px !important; font-weight: 600 !important; min-height: 30px !important;
  background: var(--line-soft) !important; border-color: var(--line-soft) !important;
  color: var(--muted) !important;
}
.st-key-sb_data .stButton button:hover {
  background: #fff !important; border-color: var(--brand) !important;
  color: var(--brand-deep) !important;
}
/* 메인 필터 셀렉트만 크고 또렷하게 (Streamlit이 key로 붙여주는 st-key-* 클래스로 지정) */
.st-key-report_month .react-aria-ComboBox > div {
  border: 1.5px solid var(--brand) !important;
  background: #fff !important;
  border-radius: 3px !important;
}
.st-key-report_month .react-aria-ComboBox input {
  font-size: 14px !important; font-weight: 700 !important;
  color: var(--ink) !important; padding: 7px 11px !important;
}

.stButton button {
  border-radius: 3px !important; font-weight: 700 !important;
  font-size: 12.5px !important; border-color: var(--line) !important;
  transition: background .18s ease, border-color .18s ease;
}
.stButton button:hover {
  border-color: var(--brand) !important; color: var(--brand-deep) !important;
}
/* 기본 primary 버튼이 빨강이라 브랜드 팔레트와 부딪힌다 — 그린으로 덮어쓴다 */
.stApp .stButton button[kind="primary"],
.stApp .stButton button[data-testid="stBaseButton-primary"] {
  background-color: var(--brand) !important;
  border-color: var(--brand) !important;
  color: #04331b !important;
  padding: 6px 20px !important;
}
.stApp .stButton button[kind="primary"]:hover,
.stApp .stButton button[data-testid="stBaseButton-primary"]:hover {
  background-color: var(--brand-deep) !important;
  border-color: var(--brand-deep) !important;
  color: #ffffff !important;
}

/* 조건 패널(st.container(border=True)) — 다른 카드와 같은 표면 규칙으로 맞춘다.
   Streamlit 기본값은 8px radius + 반투명 회색 테두리라 이 화면에서 혼자 튄다. */
.stApp div[data-testid="stVerticalBlock"][class*="st-emotion"] {
  border-radius: 4px;
}
.stApp div[data-testid="stVerticalBlock"][style*="border"],
.stApp div[data-testid="stVerticalBlock"]:has(> div [data-testid="stBaseButton-primary"]) {
  border-color: var(--line) !important;
  background: var(--surface);
  border-radius: 4px !important;
  padding: 18px 20px 6px 20px;
}
.stTextArea textarea, .stTextInput input {
  border-radius: 3px !important; font-size: 12.5px !important;
}
[data-baseweb="tag"] { background: var(--brand-deep) !important; border-radius: 3px !important; }

.foot {
  margin-top: 38px; padding: 15px 18px; border-radius: 4px;
  background: var(--surface); border: 1px solid var(--line);
  border-left: 3px solid var(--line);
  font-size: 11.5px; color: var(--muted); line-height: 1.75;
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def _e(text) -> str:
    return html.escape(str(text))


def report_header(
    kicker: str,
    title: str,
    subtitle: str = "",
    meta: list[tuple[str, str]] | None = None,
    agenda: list[str] | None = None,
) -> None:
    """리포트 표지 헤더 — 로고 락업 + 제목 (+ 선택적으로 설명·메타·아젠다)."""
    logo = logo_data_uri()
    logo_block = (
        f'<div class="rpt-logo"><img src="{logo}" alt="LINE WEBTOON"></div>' if logo else ""
    )
    subtitle_block = f'<div class="rpt-sub">{_e(subtitle)}</div>' if subtitle else ""
    stamp_items = "".join(
        f'<div class="rpt-stamp-k">{_e(k)}</div><div class="rpt-stamp-v">{_e(v)}</div>'
        for k, v in (meta or [])
    )
    stamp_block = f'<div class="rpt-stamp">{stamp_items}</div>' if stamp_items else ""

    agenda_items = "".join(
        f'<div class="rpt-agenda-item"><span class="rpt-agenda-n">{index}</span>'
        f'<span class="rpt-agenda-t">{_e(text)}</span></div>'
        for index, text in enumerate(agenda or [], start=1)
    )
    agenda_block = f'<div class="rpt-agenda">{agenda_items}</div>' if agenda_items else ""

    st.markdown(
        f'<div class="rpt-head"><div class="rpt-top">{logo_block}'
        f'<div class="rpt-titles"><div class="rpt-kicker">{_e(kicker)}</div>'
        f'<h1 class="rpt-h1">{_e(title)}</h1>'
        f"{subtitle_block}{agenda_block}</div>{stamp_block}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def sidebar_brand(title: str, subtitle: str) -> None:
    logo = logo_data_uri()
    image = f'<img src="{logo}" alt="">' if logo else ""
    st.sidebar.markdown(
        f'<div class="sb-brand">{image}<div>'
        f'<div class="sb-brand-t">{_e(title)}</div>'
        f'<div class="sb-brand-s">{_e(subtitle)}</div></div></div>',
        unsafe_allow_html=True,
    )


def _hint_icon(text: str) -> str:
    """어두운 카드형 커스텀 툴팁 "?" 아이콘 하나. 순수 CSS(:hover)로 뜬다.

    네이티브 title 속성은 지연·기본폰트라 리포트 톤과 안 맞아서 직접 그린다.
    """
    pop_html = _e(text).replace("\n", "<br>")
    return (
        '<span class="sec-hint-wrap">'
        '<span class="sec-hint">?</span>'
        f'<span class="sec-hint-pop">{pop_html}</span>'
        '</span>'
    )


def section(
    number: str, title: str, description: str = "", badge: str | None = None,
    hint: bool = False, extra_hint: str | None = None,
) -> None:
    """섹션 헤더. description은 기본적으로 제목 아래 한 줄로 풀어 보여준다.

    hint=True면 대신 제목 옆 "?" 아이콘에 넣어, 커서를 올렸을 때만 보이게 한다 —
    매달 보는 사람에게는 매번 눈에 밟히는 설명 줄보다 필요할 때만 여는 쪽이 낫다.

    extra_hint는 description과 별개로, 항상 아이콘 형태로만 붙는 두 번째 참고 정보다
    (예: "이 데이터를 어디서 읽었는지" 같은 진단용 정보 — 매번 보일 필요는 없지만
    본문 설명과 섞으면 안 되는 것).
    """
    chip = f'<span class="sec-badge">{_e(badge)}</span>' if badge else ""
    tip = _hint_icon(description) if description and hint else ""
    tip2 = _hint_icon(extra_hint) if extra_hint else ""
    st.markdown(
        f'<div class="sec"><div class="sec-l">'
        f'<span class="sec-n">{_e(number)}</span>'
        f'<span class="sec-t">{_e(title)}</span>{tip}{tip2}</div>{chip}</div>',
        unsafe_allow_html=True,
    )
    if description and not hint:
        # 줄바꿈은 이스케이프 이후에 <br>로 바꾼다 — 사용자 입력 자체에 태그가 섞여 들어갈
        # 걱정 없이(먼저 이스케이프했으므로) 여러 줄 설명(예: 본문 + "*OO 기준" 각주)을 쓸 수 있다.
        html = _e(description).replace("\n", "<br>")
        st.markdown(f'<div class="sec-d">{html}</div>', unsafe_allow_html=True)


def table_title(text: str) -> None:
    """섹션 안에서 표 하나를 소개하는 작은 부제목 — 왼쪽 브랜드 바 + 진한 텍스트.

    예전엔 st.markdown("###### ...")로 찍어 리포트 디자인 시스템과 동떨어져 보였다.
    """
    st.markdown(
        f'<div class="tbl-title"><span class="tbl-title-bar"></span>{_e(text)}</div>',
        unsafe_allow_html=True,
    )


def note_header(title: str, badge: tuple[str, str] | None = None, info: str | None = None) -> None:
    """블록의 소제목 줄. badge는 (tone, text)이며 tone은 "mine" | "other".

    info는 잠금 상태와 무관하게 항상 보여줄 중립 배지다(예: 이 블록의 조건 요약) —
    "이 조건이 무엇에 걸리는지 표 캡션에 있어 눈에 안 띈다"는 피드백을 받아 제목 옆으로 옮겼다.
    조작 버튼은 Streamlit 위젯이라 여기서 그리지 않고 대시보드가 다음 줄에 배치한다.
    """
    chips = ""
    if info:
        chips += f'<span class="nh-badge is-info">{_e(info)}</span>'
    if badge:
        tone, text = badge
        chips += f'<span class="nh-badge is-{_e(tone)}">{_e(text)}</span>'
    st.markdown(
        f'<div class="nh"><span class="nh-t">{_e(title)}</span>'
        f'<span class="nh-right">{chips}</span></div>',
        unsafe_allow_html=True,
    )


def kpi_cards(cards: list[dict]) -> None:
    """cards: [{label, value, sub, primary}] — primary=True인 카드에만 브랜드 액센트."""
    blocks = []
    for card in cards:
        klass = "kpi is-primary" if card.get("primary") else "kpi"
        blocks.append(
            f'<div class="{klass}">'
            f'<div class="kpi-l">{_e(card["label"])}</div>'
            f'<div class="kpi-v">{_e(card["value"])}</div>'
            f'<div class="kpi-s">{_e(card.get("sub", ""))}</div></div>'
        )
    st.markdown(f'<div class="kpis">{"".join(blocks)}</div>', unsafe_allow_html=True)


def status_row(tone: str, title: str, detail: str = "") -> None:
    border, soft, _ink = TONES.get(tone, TONES["neutral"])
    body = f'<div class="row-d">{_e(detail)}</div>' if detail else ""
    st.markdown(
        f'<div class="row" style="--accent:{border};--soft:{soft};">'
        f'<div><div class="row-t">{_e(title)}</div>{body}</div></div>',
        unsafe_allow_html=True,
    )


def chips(items: list[str]) -> None:
    if not items:
        return
    body = "".join(f'<span class="chip">{_e(i)}</span>' for i in items)
    st.markdown(f'<div class="chips">{body}</div>', unsafe_allow_html=True)


def footnote(text: str) -> None:
    st.markdown(f'<div class="foot">{_e(text)}</div>', unsafe_allow_html=True)
