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
/* "*OO 기준" 같은 데이터 출처 각주 — 예전엔 sec-d로 제목 아래 한 줄 통째로 차지해
   내용에 비해 공간을 너무 썼다(실제 피드백). 제목 옆에 작게 붙여 안내 문구처럼 낮춘다. */
.sec-note {
  font-size: 10.5px; font-weight: 400; color: var(--faint);
  margin-left: -4px; white-space: nowrap;
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
  grid-auto-rows: 1fr;  /* 두 줄로 접혔을 때 위·아래 줄의 카드 높이를 같게 */
  gap: 0; background: var(--surface);
  border: 1px solid var(--line); border-radius: 4px; overflow: hidden;
  box-shadow: 0 2px 6px rgba(20, 23, 26, .07);
}
.kpi {
  /* 아래 여백을 줄여 카드가 내용에 맞게 붙게 한다 — 예전엔 값 아래에 설명 줄이 있어
     넉넉히 잡아뒀는데, 그 줄을 라벨 옆으로 올리면서 아래가 통째로 비었다. */
  padding: 14px 16px 15px 16px;
  border-right: 1px solid var(--line-soft);
  border-top: 2px solid transparent;
  /* 여섯 칸이 두 줄로 접혀도 카드 높이가 어긋나지 않게 한다 */
  display: flex; flex-direction: column;
}
.kpi:last-child { border-right: 0; }
.kpi.is-primary { border-top-color: var(--brand); }
.kpi-l {
  font-size: 11px; color: var(--muted); font-weight: 700;
  letter-spacing: .05em; margin-bottom: 9px;
  display: flex; align-items: baseline; gap: 6px; white-space: nowrap;
}
/* 라벨에 딸린 부연 — 라벨보다 약하게 */
.kpi-sub { font-size: 10px; font-weight: 400; color: var(--faint); letter-spacing: 0; }
.kpi-v {
  font-size: 24px; font-weight: 800; color: var(--ink);
  line-height: 1.1; letter-spacing: -.04em;
}
/* 전월 대비 델타. 신호색(빨강/초록) 대신 기호로 방향을 표시한다 — 액센트를 하나로
   유지해야 리포트 톤이 흐트러지지 않는다. 색은 델타에만 두고 값에는 번지지 않게 한다. */
/* 변화율은 값 아래에 둔다(2026-08-28 확정). 값 옆에 붙이면 화면 폭에 따라 어떤 카드는
   옆에, 어떤 카드는 아래로 내려가 줄이 들쭉날쭉해진다 — 항상 아래로 고정해 여섯 칸의
   높이를 맞춘다. */
.kpi-row { display: flex; flex-direction: column; align-items: flex-start; gap: 7px; }
.kpi-d {
  font-size: 13px; font-weight: 700; color: var(--ink-2);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
/* 비교 기준은 카드마다 반복하지 않고 묶음 우측 상단에 한 번만 둔다 */
.kpis-wrap { margin-bottom: 8px; }
.kpis-note {
  font-size: 10.5px; color: var(--faint); text-align: right;
  margin-bottom: 5px; font-variant-numeric: tabular-nums;
}
/* 상승은 빨강, 하락은 파랑(국내 증시 관례 — 2026-08-28 사용자 지정).
   "액센트는 브랜드 그린 하나만" 원칙의 의도적 예외다. 전월 대비는 한눈에 방향이
   읽혀야 해서 기호만으로는 부족하다는 판단. 대신 색은 델타 줄에만 쓰고 숫자 본문
   (kpi-v)에는 번지지 않게 한다 — 카드 전체가 물들면 리포트 톤이 무너진다. */
.kpi-d.is-up { color: #c0392b; }
.kpi-d.is-down { color: #1f5fa8; }

/* 표 아래 우측에 붙는 작은 안내(예: "텍스트 애셋은 제외했습니다").
   섹션 제목 밑에 두면 본문보다 먼저 읽혀 무게가 과했다 — 표를 다 본 뒤 읽을 각주다. */
.tbl-note {
  font-size: 10.5px; color: var(--faint); text-align: right; margin: 2px 0 10px;
}

/* ------------------------------------------------- 블록 잠금 */
/* 잠긴 블록은 조작 버튼을 감추고 "무엇이 막혔는지 + 어떻게 푸는지"만 남긴다.
   안내는 전체 폭 알럿이 아니라 제목 줄에 붙는 작은 회색 문구다(2026-08-29). */
.lock-hint {
  font-size: 10.5px; color: var(--muted); white-space: nowrap;
  display: inline-flex; align-items: center;
}
[class*="st-key-blocklock_"] [data-testid="stMarkdownContainer"] { margin: 0 !important; }
[class*="st-key-blocklock_"] .stButton button {
  min-height: 24px !important; padding: 1px 10px !important;
  font-size: 10.5px !important; border-radius: 4px !important;
  white-space: nowrap !important;
}

/* ------------------------------------------------- 블록 삭제 확인 */
/* 묻는 말은 버튼 바로 옆에 붙이고, 되돌릴 수 없는 쪽(삭제)만 빨강으로 채운다. */
.del-ask {
  font-size: 11.5px; color: #a5342a; white-space: nowrap;
  display: inline-flex; align-items: center; height: 100%;
}
[class*="st-key-blockmenu_"] [data-testid="stMarkdownContainer"] { margin: 0 !important; }

/* ------------------------------------------------- 셀 강조 조작 칩 */
/* 편집 모드에서 셀을 고르면 **표 제목 줄 오른쪽**에 뜨는 작은 회색 캡슐(2026-08-29 확정).
   - 왜 제목 줄인가: 표가 가로로 꽉 차 있어 표 위에 띄우면 반드시 데이터를 가린다.
     실제로 선택 행 옆에 띄웠다가 오른쪽 컬럼 값이 덮였다.
   - 색은 본문 회색(#4b5563). 데이터 색(그린=우수/적색=저조)과 겹치지 않아 "도구"로 읽힌다.
   - 버튼에는 배경·테두리를 주지 않는다. 주면 캡슐 안에 알약이 또 들어앉아 따로 논다.
   - position:absolute라 나타나고 사라져도 표가 위아래로 밀리지 않는다. */
[class*="st-key-hlbox_"] { position: relative; }
[class*="st-key-hlchip_"] {
  position: absolute; top: -34px; right: 0; z-index: 5;
  width: fit-content;
  background: #4b5563;
  border-radius: 999px !important;
  padding: 2px !important;
  box-shadow: 0 2px 8px rgba(20, 23, 26, .20);
  overflow: hidden;
}
/* 두 버튼의 세로 기준선을 맞춘다. Streamlit 컬럼은 기본이 위쪽 정렬이라, 컬럼 높이가
   조금만 달라도 라벨이 위로 붙어 보인다(2026-08-29 실제 발생). */
[class*="st-key-hlchip_"] [data-testid="stHorizontalBlock"] {
  gap: 0 !important; align-items: center !important;
}
[class*="st-key-hlchip_"] [data-testid="stColumn"] {
  width: auto !important; flex: 0 0 auto !important; min-width: 0 !important;
  display: flex !important; align-items: center !important;
}
[class*="st-key-hlchip_"] [data-testid="stColumn"] > div,
[class*="st-key-hlchip_"] .stButton {
  display: flex !important; align-items: center !important; margin: 0 !important;
}
[class*="st-key-hlchip_"] .stButton button {
  display: inline-flex !important; align-items: center !important;
  justify-content: center !important;
}
/* 두 번째 칸 앞에만 짧은 구분선 — 위아래를 띄워 캡슐을 가로지르지 않게 한다 */
[class*="st-key-hlchip_"] [data-testid="stColumn"] + [data-testid="stColumn"] {
  border-left: 1px solid rgba(255, 255, 255, .20);
  margin: 4px 0;
}
[class*="st-key-hlchip_"] .stButton button {
  min-height: 0 !important; height: auto !important;
  padding: 3px 12px !important;
  font-size: 10.5px !important; font-weight: 500 !important; line-height: 1.5 !important;
  background: transparent !important; border: 0 !important; outline: 0 !important;
  border-radius: 999px !important; color: #fff !important;
  box-shadow: none !important;
}
[class*="st-key-hlchip_"] .stButton button:hover,
[class*="st-key-hlchip_"] .stButton button:focus {
  background: rgba(255, 255, 255, .16) !important; color: #fff !important;
}
/* 라벨 글자는 button이 아니라 그 안의 <p>가 자기 폰트를 갖는다 — button에만 지정하면
   두 버튼의 굵기·크기가 서로 달라 보인다(2026-08-29 실제 발생). 안쪽까지 못 박는다. */
[class*="st-key-hlchip_"] .stButton button * {
  font-size: 10.5px !important;
  font-weight: 500 !important;
  line-height: 1.5 !important;
  letter-spacing: 0 !important;
  color: #fff !important;
  margin: 0 !important;
  -webkit-font-smoothing: antialiased;
}

/* ------------------------------------------------- 리런 중 깜빡임 억제 */
/* Streamlit은 스크립트가 다시 도는 동안 (1) 우측 상단에 러너 아이콘을 띄우고
   (2) 다시 그려질 요소를 흐리게 처리한다. 셀 강조처럼 눈 깜짝할 사이에 끝나는
   조작에서도 화면이 한 번 흐려졌다 돌아와 "로딩 걸린다"는 인상을 준다
   (2026-08-29 피드백). 고객사에 그대로 보여주는 리포트라 더 거슬린다.

   실측으로 확인한 동작: 리런이 시작되면 stApp에 data-test-script-state가 붙고,
   다시 그릴 요소에는 data-stale="true"와 흐린 버전의 emotion 클래스가 함께 걸린다.
   클래스 이름은 배포마다 바뀌므로 data-stale 쪽을 잡아 덮는다. */
[data-testid="stStatusWidget"] { display: none !important; }

/* 대신 화면 최상단에 2px 진행 바를 띄운다(2026-08-29, A안).
   브라우저가 페이지를 불러올 때 쓰는 관습이라 설명 없이 읽히고, 화면을 가리거나
   레이아웃을 밀지 않는다. 구글 데이터 로딩 박스의 인디터미네이트 바와 같은 언어다.
   리런이 시작되면 stApp에 data-test-script-state가 붙는 것을 실측으로 확인했다. */
[data-testid="stApp"][data-test-script-state="running"]::before,
[data-testid="stApp"][data-test-script-state="rerunRequested"]::before {
  content: ""; position: fixed; top: 0; left: 0; right: 0; height: 2px;
  background: var(--line-soft); z-index: 999999;
}
[data-testid="stApp"][data-test-script-state="running"]::after,
[data-testid="stApp"][data-test-script-state="rerunRequested"]::after {
  content: ""; position: fixed; top: 0; height: 2px; width: 35%;
  background: var(--brand-deep); z-index: 1000000;
  animation: rpt-topbar 1.1s ease-in-out infinite;
}
@keyframes rpt-topbar {
  from { left: -35%; }
  to   { left: 100%; }
}
/* 모션을 줄이도록 설정한 사용자에게는 흐르지 않는 정적 바로 */
@media (prefers-reduced-motion: reduce) {
  [data-testid="stApp"][data-test-script-state="running"]::after,
  [data-testid="stApp"][data-test-script-state="rerunRequested"]::after {
    animation: none; left: 0; width: 100%; opacity: .5;
  }
}
[data-testid="stElementContainer"][data-stale="true"],
[data-stale="true"] {
  opacity: 1 !important;
  filter: none !important;
  transition: none !important;
}
/* 리런 중 앱 전체에 걸리는 페이드도 끈다 */
[data-test-script-state="running"] [data-testid="stElementContainer"],
[data-test-script-state="rerunRequested"] [data-testid="stElementContainer"] {
  opacity: 1 !important;
}

/* ------------------------------------------------- 리포트 표 (HTML 직접 렌더) */
/* st.dataframe이 캔버스라 못 바꾸는 것들(헤더 정렬·굵기·그룹 구분선)을 위해 쓰는 표.
   행 높이는 st.dataframe 기본값(35px)과 비슷한 느낌으로 맞춰 두 종류 표가 나란히
   있어도 이질감이 없게 한다. */
/* 테두리는 감싸는 상자에 준다. 표에 주면 스크롤할 때 테두리가 내용과 함께 밀려 올라가
   바닥선이 안 보인다(2026-08-29 피드백). 상자에 주면 스크롤 중에도 틀이 그대로 남는다.
   상자 안 마지막 행 아래에 보이던 띠는 빈 공간이 아니라 **가로 스크롤바**였다(실측:
   내용과 상자 사이 여백 0px) — 얇게 처리해 눈에 덜 띄게 한다. */
.rt-wrap {
  overflow: auto; margin-bottom: 8px;
  scrollbar-width: thin;
  border: 1px solid var(--line); border-radius: 3px;
  background: var(--surface);
  /* 행이 많은 표(속성별·소재 분석·작품별)가 화면을 한없이 밀어내지 않게 높이를 묶는다.
     10행 남짓이면 그대로 다 보이고, 그보다 길면 표 안에서 스크롤된다. */
  max-height: 420px;
}
.rt {
  width: 100%; border-collapse: collapse;
  font-size: 12px; font-variant-numeric: tabular-nums;
}
.rt th {
  background: #f1f4f6; color: #374151;
  font-size: 11px; font-weight: 700; letter-spacing: .01em;
  padding: 10px 10px; white-space: nowrap;
  /* 스크롤해도 지표명이 남도록 헤더를 고정한다. border-collapse 표에서는 sticky 헤더의
     테두리가 같이 스크롤돼 사라지므로, 밑선은 box-shadow로 그린다. */
  position: sticky; top: 0; z-index: 2;
  border-bottom: 0;
  box-shadow: inset 0 -1.5px 0 var(--ink);
}
.rt td {
  padding: 8px 10px; white-space: nowrap;
  border-bottom: 1px solid var(--line-soft); color: var(--ink);
}
/* 마지막 행: 테두리를 아예 없애면 그 행만 1px 낮아지고, 투명으로 두면 이번엔 표
   바닥선이 사라진다 — border-collapse 표에서는 셀 테두리가 표 자체 테두리를 이기기
   때문이다(2026-08-29, 두 번의 피드백으로 확정). 높이도 유지하고 바닥선도 남도록
   표 테두리와 같은 색으로 둔다. */
/* 마지막 행: 테두리를 아예 없애면 그 행만 1px 낮아진다. 높이는 유지하되, 상자 테두리와
   겹쳐 두 줄로 보이지 않게 투명으로 둔다(틀은 이제 상자가 그린다). */
.rt tbody tr:last-child td { border-bottom-color: transparent; }
.rt .c { text-align: center; }
.rt .l { text-align: left; }
/* 규모/효율처럼 성격이 다른 지표 묶음 사이에만 세로선 */
.rt .gs { border-left: 1px solid var(--line); }
.rt tbody tr:hover td { background: #fafbfc; }
.rt-link { color: var(--brand-deep); text-decoration: none; font-weight: 500; }
.rt-link:hover { text-decoration: underline; }
/* 우수·저조: 행 전체를 굵게 물들이면 숫자가 읽히지 않아 배경만 옅게 깔고
   소재명에만 색을 준다(시트의 파랑=우수 / 빨강=저조 컨벤션 유지). */
.rt tr.is-good td { background: #eefaf4; }
.rt tr.is-bad td { background: #fdf3f3; }
.rt tr.is-good:hover td { background: #e6f7ee; }
.rt tr.is-bad:hover td { background: #fbebeb; }
/* 우수/저조는 행 전체를 굵게 칠한다 — 예전 st.dataframe 렌더(ROW_GOOD/ROW_BAD)와 같은
   규칙이고, 시트의 파랑=우수 / 빨강=저조 컨벤션을 그대로 잇는다. 소재명만 굵게 했더니
   구글 표처럼 첫 컬럼이 링크인 표에서는 강조가 사라져 보였다(2026-08-29 피드백). */
.rt tr.is-good td { color: #0b5c38; font-weight: 700; }
.rt tr.is-bad td { color: #8c2b2b; font-weight: 700; }
.rt tr.is-good td a.rt-link { color: #0b5c38; }
.rt tr.is-bad td a.rt-link { color: #8c2b2b; }

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
/* 하이라이트(우수·저조) 소재 카드 — 표 아래에서 실제 영상으로 이어주는 진입점.
   표 자체(st.dataframe)는 셀 안에 링크를 못 심어서, 클릭 경로는 이 카드가 전담한다.
   이미지 왼쪽 + 정보 오른쪽 가로 배치 — 세로형(9:16) 소재가 대부분이라, 위아래로
   쌓고 폭에 맞춰 자르면(16:10 crop) 정작 중요한 장면이 잘려 나갔다(실제 피드백).
   가로 배치 + object-fit: contain으로 잘리는 부분 없이 이미지 전체가 다 보이게 한다. */
.mat-cards {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px; margin: 10px 0 4px;
}
/* 카드 전체가 클릭 진입점이다 — 별도 "영상 보기" 문구 없이, 좌측 색 레일(우수=그린/
   저조=레드) + hover 시 테두리·배경 변화 + 우상단 화살표만으로 클릭 가능함을 알린다.
   앵커 기본 스타일(파란 글자·밑줄)이 값·소재명에 그대로 상속돼 "검색 결과 스니펫"처럼
   보이던 문제가 있었다(실제 피드백) — 그런데 차단을 `.mat-card *`에 걸면 이 안의 캡션
   그린·소재명 회색처럼 의도적으로 준 색까지 전부 지워버린다(실제로 한 번 이렇게 깨졌다).
   Streamlit의 `a` 색 규칙을 이기기만 하면 되므로 앵커 자신에게만 !important를 걸고,
   자식 요소들의 색은 상속이 아니라 각자 명시적으로 지정해 자연스럽게 이기게 둔다. */
.mat-card, .mat-card:visited {
  text-decoration: none !important; color: var(--ink) !important;
}
.mat-card {
  position: relative; display: flex; flex-direction: row; align-items: stretch;
  /* 우수/저조 띠는 카드 위쪽에 둔다(2026-08-28 사용자 지정) — 좌측 세로 띠는
     썸네일 옆에 붙어 이미지의 일부처럼 보였다. */
  border: 1px solid var(--line); border-top: 3px solid var(--brand-deep);
  border-radius: 0; overflow: hidden; background: var(--surface);
  cursor: pointer; transition: border-color .15s, background .15s;
}
.mat-card.is-bad { border-top-color: #a32d2d; }
.mat-card:hover { border-color: var(--brand-deep); background: #f6fdfa; }
.mat-card.is-bad:hover { border-color: #a32d2d; background: #fdf6f6; }
.mat-card.is-dead {
  cursor: default; border-top-color: var(--line);
}
.mat-card.is-dead:hover { border-color: var(--line); background: var(--surface); }
.mat-ext {
  position: absolute; top: 7px; right: 8px; font-size: 12px; color: var(--faint);
  line-height: 1; transition: color .15s;
}
.mat-card:hover .mat-ext { color: var(--brand-deep); }
.mat-card.is-bad:hover .mat-ext { color: #a32d2d; }
.mat-thumb {
  flex: 0 0 96px; width: 96px; background: var(--line-soft);
  display: flex; align-items: center; justify-content: center; overflow: hidden;
}
.mat-thumb img { width: 100%; height: 100%; object-fit: contain; display: block; }
/* 세로 소재만 자리를 꽉 채운다 — 16:9 썸네일에 좌우로 깔린 배경 띠가 잘려 나가
   그림이 커진다. 가로 소재는 contain 그대로 둔다(잘라내면 자막·인물이 날아간다). */
.mat-thumb.is-fill img { object-fit: cover; }
.mat-thumb .mat-noimg { font-size: 10.5px; color: var(--faint); text-align: center; padding: 4px; }
.mat-meta {
  flex: 1 1 auto; min-width: 0; padding: 9px 24px 10px 11px;
  display: flex; flex-direction: column;
}
/* 지표명은 캡션으로 낮추고, 우수/저조만 색을 준다 — 배지 칩을 없애서 카드가 조용해진다 */
.mat-cap {
  font-size: 10px; font-weight: 500; letter-spacing: .06em; text-transform: uppercase;
  color: var(--faint);
}
.mat-cap b { font-weight: 600; color: var(--brand-deep); }
.mat-card.is-bad .mat-cap b { color: #a32d2d; }
.mat-value {
  font-size: 19px; font-weight: 600; color: var(--ink);
  font-variant-numeric: tabular-nums; line-height: 1.2; margin-top: 1px;
}
/* 작품명(국문) — 작품 단위 매칭 안 되는 소재는 이 줄 없이 소재명만 보인다 */
.mat-title {
  font-size: 12.5px; font-weight: 600; color: var(--ink); margin-top: 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* 소재명은 통째로 넣는다(구분자 태그로 쪼개지 않음) — 두 줄까지 자연스럽게 접힌다.
   썸네일이 세로형(9:16)이라 카드 높이가 이미 넉넉해, 두 줄이 돼도 카드 높이는 안 늘어난다. */
.mat-name {
  font-size: 10.5px; color: var(--muted); line-height: 1.5; margin-top: 3px;
  font-variant-numeric: tabular-nums; overflow-wrap: anywhere;
}
/* 우수/저조 선정 기준 안내 — 표·카드 아래 매번 반복되는 보조 설명이라, 본문과 같은
   비중으로 두면 화면이 산만해진다(실제 피드백). 박스 없이 우측 구석에 붙는 옅은 각주로 낮춘다. */
.sec-legend {
  text-align: right; font-size: 10.5px; color: var(--faint);
  margin: 6px 0 2px; line-height: 1.5;
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
[class*="st-key-vmetric_"] button[role="radio"][aria-checked="true"] {
  background: var(--brand) !important; border-color: var(--brand) !important;
}
.st-key-mode_toggle button[role="radio"][aria-checked="true"] p,
[class*="st-key-vmetric_"] button[role="radio"][aria-checked="true"] p {
  color: #fff !important;
}

/* 표 위 기준 라벨 — 실제 리포트 시트가 표마다 `* 틱톡 AOS`처럼 붙이는 그것. */
.view-basis {
  font-size: 12px; color: var(--ink-2); margin: 14px 0 6px 0; font-weight: 600;
}
/* 분석 코멘트 다음에 항상 오는 고정 항목. 리포트에서 이 문구가 소제목 역할을 한다. */
.insight-head {
  font-size: 12.5px; font-weight: 700; color: var(--ink); margin: 16px 0 4px 0;
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
/* 잠금 상태는 상태 색이 정보 전달의 핵심이라 칩 형태를 유지한다 */
.nh-badge.is-mine { background: #e7f9f0; color: #0f6e56; }
.nh-badge.is-other { background: #faeeda; color: #854f0b; }
/* 조건 요약은 "읽는 정보"라 칩 배경을 벗기고 점 + 평문으로 낮춘다 — 옆의 조작 버튼
   (테두리 있는 것)과 성격이 한눈에 갈려야 한다. 길어지면 말줄임으로 줄어들어
   버튼을 밀어내지 않는다. */
.nh-badge.is-info {
  background: transparent; color: var(--muted); font-size: 11px; padding: 0;
  display: inline-flex; align-items: center; gap: 6px;
  overflow: hidden; text-overflow: ellipsis; min-width: 0;
}
.nh-badge.is-info::before {
  content: ""; width: 5px; height: 5px; border-radius: 50%;
  background: var(--faint); flex: 0 0 auto;
}
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
/* 카드 맨 아래 요소(모드 토글 / 고정 CTA 블록)가 테두리에 붙어 답답해 보였다 */
.st-key-sb_controls { padding-bottom: 14px !important; }
.st-key-sb_data { padding-bottom: 14px !important; }
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
  font-size: 11px !important; font-weight: 600 !important; min-height: 28px !important;
  background: var(--line-soft) !important; border-color: var(--line-soft) !important;
  color: var(--muted) !important;
}
/* 보조 버튼 라벨은 사이드바 폭에서 두 줄로 접히지 않게 한 줄로 눌러 둔다 */
.st-key-sb_data .stButton button p { white-space: nowrap !important; }
.st-key-sb_data .stButton button:hover {
  background: #fff !important; border-color: var(--brand) !important;
  color: var(--brand-deep) !important;
}
/* 구글 데이터 고정 CTA — 박스(옅은 민트 배경 + 브랜드 테두리)는 사용자가 승인한
   원래 톤 그대로 유지한다. 문제는 버튼 쪽이었다: 글자가 좁은 사이드바 폭에서
   두 줄로 어색하게 접혔다 — 라벨을 짧게 줄이고 nowrap을 강제해 고친다. */
.st-key-google_freeze_pending {
  border: 1.5px solid var(--brand) !important;
  background: #e7f9f0 !important;
  border-radius: 6px !important;
  padding: 14px 14px 16px !important;
}
.freeze-cta-title {
  font-size: 12.5px; font-weight: 700; color: var(--brand-deep); margin-bottom: 5px;
  white-space: nowrap;  /* 좁은 폭에서 마지막 글자만 다음 줄로 떨어지는 걸 막는다 */
}
.freeze-cta-body {
  font-size: 11px; color: var(--ink-2); margin-bottom: 16px; line-height: 1.5;
}
.st-key-google_freeze_pending .stButton button[kind="primary"] {
  min-height: 36px !important; font-size: 13px !important;
  letter-spacing: -.01em !important; border-radius: 5px !important;
}
.st-key-google_freeze_pending .stButton button[kind="primary"] p {
  white-space: nowrap !important;  /* 버튼 글자가 짧은데도 두 줄로 접혀 어색했다 */
  font-weight: 700 !important;
}
/* 데이터 없음 안내 / 로딩 자리표시자 — 강조도, 경고도 아니라 중립 회색 톤으로 */
.st-key-google_freeze_loading,
.st-key-google_freeze_nodata {
  border: 1px solid var(--line) !important;
  background: var(--line-soft) !important;
  border-radius: 4px !important;
  /* 두 줄뿐인 박스라 위아래를 넉넉히 — 설명 줄이 테두리에 붙어 답답해 보였다 */
  padding: 14px !important;
}
/* Streamlit이 stMarkdownContainer에 margin-bottom: -16px(음수)를 걸어서, 박스에 준
   padding-bottom이 그대로 먹혀 텍스트가 아래 테두리에 붙어 버린다(실측 확인).
   세 CTA 박스 모두 이 음수 마진을 무효화해 위아래 여백이 대칭이 되게 한다.
   로딩 자리표시자(_loading)가 이 목록에서 빠져 있어서 글자가 박스 아래쪽으로
   쏠려 보였다(실제 피드백) — 같은 규칙에 넣어 가운데로 돌려놓는다. */
.st-key-google_freeze_loading [data-testid="stMarkdownContainer"],
.st-key-google_freeze_nodata [data-testid="stMarkdownContainer"],
.st-key-google_freeze_pending [data-testid="stMarkdownContainer"] {
  margin-bottom: 0 !important;
}
.freeze-cta-title--muted { color: var(--muted) !important; }
.freeze-cta-dot--muted { background: var(--faint) !important; }
.st-key-google_freeze_loading .freeze-cta-body,
.st-key-google_freeze_nodata .freeze-cta-body { margin-bottom: 0; }
/* 로딩 인디케이터 — 박스 하단 2px 인디터미네이트 바. 아이콘 대신 선을 쓴 이유는
   고객사 리포트 톤에서 회전 스피너가 과하게 읽혀서다(디자인 비교 후 선택).
   액센트는 브랜드 그린 하나만 쓰고 트랙은 중성 회색이다. */
.st-key-google_freeze_loading .freeze-cta-body { margin-bottom: 10px; }
.freeze-cta-bar {
  position: relative; height: 2px; border-radius: 2px;
  background: #e9ecef; overflow: hidden;
}
.freeze-cta-bar i {
  position: absolute; top: 0; height: 2px; width: 40%;
  background: var(--brand-deep);
  animation: freeze-cta-sweep 1.15s ease-in-out infinite;
}
@keyframes freeze-cta-sweep {
  from { left: -40%; }
  to   { left: 100%; }
}
/* 모션을 줄이도록 설정한 사용자에게는 흐르지 않는 정적 바로 보여준다 */
@media (prefers-reduced-motion: reduce) {
  .freeze-cta-bar i { animation: none; left: 0; width: 100%; opacity: .45; }
}
.st-key-google_freeze_done { padding: 4px 2px 0; }
.st-key-google_freeze_done [data-testid="stCaptionContainer"] p {
  font-size: 10.5px !important; color: var(--faint) !important;
}
.st-key-google_freeze_done .stButton button {
  min-height: 24px !important; padding: 1px 8px !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
}
/* 블록 조작 버튼 — 조건 배지(테두리 없는 평문)와 갈리도록 "누르는 것"은 전부 테두리를
   가진다. 편집은 초록 텍스트 링크처럼, 이동·삭제는 정사각 아이콘 버튼으로 위계를 나눈다. */
[class*="st-key-blockmenu_"] { flex: 0 0 auto !important; }
[class*="st-key-blockmenu_"] .stButton button {
  min-height: 24px !important; border-radius: 4px !important;
  background: var(--surface) !important; border: 1px solid var(--line) !important;
  color: var(--muted) !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
}
[class*="st-key-blockmenu_"] .stButton button p {
  font-size: 10.5px !important; line-height: 1 !important; white-space: nowrap !important;
}
[class*="st-key-blockmenu_"] .stButton button:hover {
  border-color: var(--brand) !important; color: var(--brand-deep) !important;
}
/* 편집하기 — 이 블록의 주요 동작이라 브랜드 그린으로 칠한다.
   앞선 `[class*="st-key-blockmenu_"] .stButton button` 규칙과 특정도가 같아야 이기므로
   (둘 다 !important) 반드시 blockmenu 스코프를 함께 쓴다. */
[class*="st-key-blockmenu_"] [class*="st-key-edit_"] button {
  background: #e7f9f0 !important; border-color: #a8e8c8 !important;
  color: var(--brand-deep) !important; padding: 1px 10px !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-edit_"] button p { font-weight: 700 !important; }
[class*="st-key-blockmenu_"] [class*="st-key-edit_"] button:hover {
  background: var(--brand) !important; border-color: var(--brand) !important;
  color: #04331b !important;
}
/* 삭제(트리거) — 되돌릴 수 없는 동작이라 붉은 톤으로 칠해 다른 버튼과 구분한다.
   확인 줄의 del_yes_/del_no_는 제외한다 — 같은 컨테이너를 쓰기 때문에 접두사만으로
   잡으면 "취소"까지 빨갛게 칠해진다(2026-08-29 실제 발생). */
[class*="st-key-blockmenu_"] [class*="st-key-del_"]:not([class*="st-key-del_yes_"]):not([class*="st-key-del_no_"]) button {
  background: #fdf1f1 !important; border-color: #eec4c1 !important;
  color: #b4453f !important; padding: 1px 10px !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_"]:not([class*="st-key-del_yes_"]):not([class*="st-key-del_no_"]) button p {
  font-weight: 700 !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_"]:not([class*="st-key-del_yes_"]):not([class*="st-key-del_no_"]) button:hover {
  background: #ef6f66 !important; border-color: #ef6f66 !important;
  color: #3d0f0c !important;
}
/* 이동 — 순서만 바꾸는 보조 동작이라 색 없이 기호만 담는 정사각 버튼 */
[class*="st-key-blockmenu_"] [class*="st-key-up_"] button,
[class*="st-key-blockmenu_"] [class*="st-key-down_"] button {
  width: 24px !important; padding: 0 !important;
}
/* 삭제 확인 줄 — 실행(삭제)만 빨강으로 채우고, 취소는 평범한 흰 버튼으로 둔다.
   컨테이너 키는 평상시 버튼 줄과 같은 blockmenu_다(리런 중 두 줄이 겹쳐 보이던 문제
   때문에 통일했다). 그래서 버튼 구분은 각 버튼의 키로 한다. */
[class*="st-key-blockmenu_"] .stButton button {
  min-height: 24px !important; border-radius: 4px !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_yes_"] button {
  background: #a5342a !important; border-color: #a5342a !important;
  color: #fff !important; padding: 1px 12px !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_yes_"] button p {
  color: #fff !important; font-weight: 700 !important; font-size: 10.5px !important;
  white-space: nowrap !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_yes_"] button:hover {
  background: #8c2b2b !important; border-color: #8c2b2b !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_no_"] button {
  background: #fff !important; border-color: var(--line) !important;
  color: var(--ink-2) !important; padding: 1px 12px !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_no_"] button p {
  color: var(--ink-2) !important; font-weight: 400 !important; font-size: 10.5px !important;
  white-space: nowrap !important;
}
[class*="st-key-blockmenu_"] [class*="st-key-del_no_"] button:hover {
  background: #fafbfc !important; border-color: var(--muted) !important;
}
/* 라벨은 Streamlit이 button > p 로 감싸므로 폰트는 p에 직접 지정해야 먹는다 */
.st-key-google_freeze_done .stButton button p {
  font-size: 9.5px !important; line-height: 1.2 !important; white-space: nowrap !important;
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
    hint: bool = False, extra_hint: str | None = None, note: str | None = None,
) -> None:
    """섹션 헤더. description은 기본적으로 제목 아래 한 줄로 풀어 보여준다.

    hint=True면 대신 제목 옆 "?" 아이콘에 넣어, 커서를 올렸을 때만 보이게 한다 —
    매달 보는 사람에게는 매번 눈에 밟히는 설명 줄보다 필요할 때만 여는 쪽이 낫다.

    extra_hint는 description과 별개로, 항상 아이콘 형태로만 붙는 두 번째 참고 정보다
    (예: "이 데이터를 어디서 읽었는지" 같은 진단용 정보 — 매번 보일 필요는 없지만
    본문 설명과 섞으면 안 되는 것).

    note는 "*앱스플라이어 코호트 데이터 기준" 같은 짧은 데이터 출처 각주 전용이다.
    description과 달리 별도 줄을 차지하지 않고 제목 옆에 작게 붙는다 — 본문 설명이
    아니라 "이 표가 어느 데이터를 쓰는지"만 알려주는 티 안 나는 안내이기 때문.
    """
    chip = f'<span class="sec-badge">{_e(badge)}</span>' if badge else ""
    tip = _hint_icon(description) if description and hint else ""
    tip2 = _hint_icon(extra_hint) if extra_hint else ""
    note_html = f'<span class="sec-note">{_e(note)}</span>' if note else ""
    st.markdown(
        f'<div class="sec"><div class="sec-l">'
        f'<span class="sec-n">{_e(number)}</span>'
        f'<span class="sec-t">{_e(title)}</span>{note_html}{tip}{tip2}</div>{chip}</div>',
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


def kpi_cards(cards: list[dict], note: str = "") -> None:
    """cards: [{label, value, delta, delta_direction, sub, primary}].

    델타는 값 **옆에** 붙인다(2026-08-28 확정). 비교 기준 문구는 카드마다 반복하지 않고
    note로 받아 카드 묶음 우측 상단에 한 번만 찍는다 — 여섯 칸에 같은 말이 반복되면
    정작 읽어야 할 숫자가 묻힌다.
    """
    blocks = []
    for card in cards:
        klass = "kpi is-primary" if card.get("primary") else "kpi"
        delta = card.get("delta", "")
        direction = card.get("delta_direction", "")
        delta_class = "kpi-d" + (f" is-{direction}" if direction else "")
        delta_html = f'<span class="{delta_class}">{_e(delta)}</span>' if delta else ""
        # 부연 설명("마크업 포함")은 라벨 옆에 붙인다(2026-08-28). 값 아래에 두면
        # 그 카드만 한 줄 길어져 여섯 칸 높이가 어긋나고, 나머지 다섯 칸은 아래가
        # 빈 채로 남는다. 라벨 옆이면 어느 카드에 붙어도 높이가 그대로다.
        sub = card.get("sub", "")
        sub_html = f'<span class="kpi-sub">{_e(sub)}</span>' if sub else ""
        blocks.append(
            f'<div class="{klass}">'
            f'<div class="kpi-l">{_e(card["label"])}{sub_html}</div>'
            f'<div class="kpi-row">'
            f'<span class="kpi-v">{_e(card["value"])}</span>{delta_html}</div>'
            f'</div>'
        )
    note_html = f'<div class="kpis-note">{_e(note)}</div>' if note else ""
    st.markdown(
        f'<div class="kpis-wrap">{note_html}'
        f'<div class="kpis">{"".join(blocks)}</div></div>',
        unsafe_allow_html=True,
    )


def report_table(
    rows: list[list[str]],
    headers: list[str],
    left_columns: set[str] | None = None,
    group_starts: set[str] | None = None,
    row_classes: list[str] | None = None,
    cell_styles: list[dict[str, str]] | None = None,
    link_columns: set[str] | None = None,
) -> None:
    """리포트용 HTML 표. `st.dataframe`으로 못 하는 것들을 하기 위해 직접 그린다.

    st.dataframe은 헤더까지 캔버스로 그려서 **헤더 정렬·굵기·글자색·그룹 구분선을
    바꿀 수 없다**(2026-08-28 확인: column_config의 alignment는 문서상 "cell content"
    전용, Styler는 헤더에 안 먹음 — streamlit#6958). 그래서 헤더를 손봐야 하는 표만
    이 함수로 그린다.

    바꿔 잃는 것: 셀 클릭·드래그 강조(st.dataframe의 selection 이벤트)와 CSV 내려받기
    버튼. 그 기능을 쓰는 표는 그대로 st.dataframe에 남겨둔다.
    """
    left_columns = left_columns or set()
    group_starts = group_starts or set()
    row_classes = row_classes or [""] * len(rows)
    # cell_styles[행][컬럼명] = "background-color: ..." — CPI 히트맵과 저장된 셀 강조를
    # 그대로 옮겨오기 위한 통로다. st.dataframe이 Styler로 하던 일을 여기서 대신한다.
    cell_styles = cell_styles or [{} for _ in rows]
    # 값이 URL인 컬럼만 링크로 심는다(구글 표의 소재 링크). 나머지 셀은 항상 이스케이프된
    # 텍스트다 — 임의의 HTML이 표 안으로 들어오지 않게 한다.
    link_columns = link_columns or set()

    def cell_class(name: str) -> str:
        classes = ["l" if name in left_columns else "c"]
        if name in group_starts:
            classes.append("gs")
        return " ".join(classes)

    head = "".join(
        f'<th class="{cell_class(name)}">{_e(name)}</th>' for name in headers
    )
    body = []
    for values, klass, styles in zip(rows, row_classes, cell_styles):
        cells = []
        for name, value in zip(headers, values):
            style = styles.get(name, "")
            attr = f' style="{_e(style)}"' if style else ""
            text = _e(value)
            if name in link_columns and str(value).startswith("http"):
                text = (
                    f'<a class="rt-link" href="{_e(value)}" target="_blank" '
                    f'rel="noopener">열기</a>'
                )
            cells.append(f'<td class="{cell_class(name)}"{attr}>{text}</td>')
        body.append(f'<tr class="{klass}">{"".join(cells)}</tr>')
    st.markdown(
        f'<div class="rt-wrap"><table class="rt">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        f"</table></div>",
        unsafe_allow_html=True,
    )


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
