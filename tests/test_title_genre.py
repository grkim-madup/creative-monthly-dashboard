# -*- coding: utf-8 -*-
"""작품 장르(CLUSTER) 조인을 고정한다 (광고주 요청 2026-09-16).

⚠ **실제 시트에 닿지 않는다.** `tests/conftest.py`의 fail-closed 가드는
`google_sheets_readonly`를 막지 않으므로, 여기서 시트를 읽으면 광고주 시트를 진짜로
때린다. `title_genre`는 순수 함수만 갖고 있고 이 파일은 2차원 리스트를 직접 넣는다
(`tests/test_ios_cohort.py`와 같은 방식).

이 파일이 지키는 것:
  · 헤더를 **이름으로** 찾는다 (광고주가 열을 옮겨도 깨지지 않게)
  · 코드가 제목보다 우선 (작품명 표기가 갈린다)
  · 못 찾으면 **추측하지 않고** `미분류`
"""
from __future__ import annotations

import pandas as pd

import title_genre as G


# 실제 시트 헤더 그대로다 — `TItle ID`의 대문자 I가 두 번째인 것도 원본 표기다.
HEADER = ["Launch Date", "TItle ID", "TITLE(TW)", "TITLE(KR)", "CLUSTER", "DAY"]


def _sheet(rows) -> list[list[str]]:
    return [HEADER, *rows]


ROWS = [
    ["2014-07-01", "141", "DICE-骰子", "다이스", "[B-1] FANTASY ACTION", "수"],
    ["2020-01-01", "9981", "丟臉遊戲", "쪽팔려 게임", "[A-2] SCHOOL ROMANCE", "일"],
    ["2021-05-02", "2401", "極權教師", "참교육", "[B-2] MODERN ACTION", "토"],
]


# ------------------------------------------------------- 헤더 찾기

def test_헤더를_이름으로_찾는다():
    """⚠ 열 위치로 찾으면 광고주가 열을 하나 추가하는 순간 조용히 엉뚱한 값이 들어온다."""
    moved = [["CLUSTER", "메모", "TItle ID", "TITLE(KR)"],
             ["[E] ETC", "아무거나", "141", "다이스"]]
    table = G.parse_title_genres(moved)
    assert table["by_code"]["141"] == "[E] ETC"
    assert table["by_name"]["다이스"] == "[E] ETC"


def test_TItle_ID_표기가_달라도_찾는다():
    """원본 헤더가 `TItle ID`(대문자 I 두 번째)다. 광고주가 고쳐도 계속 잡혀야 한다."""
    for spelling in ("TItle ID", "Title ID", "title id", "TITLE ID", " Title  ID "):
        rows = [[spelling, "CLUSTER"], ["141", "[E] ETC"]]
        assert G.parse_title_genres(rows)["by_code"] == {"141": "[E] ETC"}, spelling


def test_장르_컬럼이_없으면_빈_표다():
    """다른 탭을 읽었거나 광고주가 이름을 바꾼 것이다. 조용히 통과시키면 화면이
    전부 `미분류`가 되는데 이유를 모른다 — 감사 도구가 매칭률 0%로 잡는다."""
    assert G.parse_title_genres([["TItle ID", "TITLE(KR)"], ["141", "다이스"]])["by_code"] == {}


def test_빈_입력에도_안전하다():
    for values in ([], [HEADER], None):
        table = G.parse_title_genres(values or [])
        assert table["by_code"] == {} and table["by_name"] == {}


def test_장르가_빈_행은_담지_않는다():
    """광고주는 작품을 런칭 전에 먼저 등재하고 CLUSTER는 나중에 채운다
    (실측: 10월 런칭 44건 중 CLUSTER 0건). 빈 값을 장르로 넣으면 안 된다."""
    table = G.parse_title_genres(_sheet([*ROWS, ["2026-10-01", "12345", "新作", "신작", "", "월"]]))
    assert "12345" not in table["by_code"]
    assert table["titles"] == 3


# ------------------------------------------------------- 코드 정규화

def test_앞의_0을_무시한다():
    assert G.normalize_code("0141") == G.normalize_code("141") == "141"


def test_자리표시자_코드는_매칭되지_않는다():
    """`0000`은 소재명 파서가 작품코드를 못 읽었을 때 넣는 값이다 — 매칭시키면
    서로 다른 작품이 한 장르로 뭉친다."""
    for value in ("0000", "0", "", "   ", "확인불가", None):
        assert G.normalize_code(value) == "", value


def test_소수점_표기를_흡수한다():
    """시트가 코드를 숫자로 읽어 `141.0`으로 오는 경우가 있다."""
    assert G.normalize_code("141.0") == "141"


def test_코드가_빈_시트_행이_전부를_삼키지_않는다():
    """⚠ **실제로 당한 사고다** (2026-09-16, `tools/audit_genre.py`가 잡았다).

    광고주 시트에 `Title ID`가 빈 행이 1건 있다(`扒進你心裡(無刪減)` · `[D] LGBTQ`).
    그 행을 `by_code[""]`로 담으면, 코드가 `0000`(소재명 파서가 작품코드를 못 읽은 값)인
    **`확인불가` 행이 전부 그 장르로 매칭된다** — 8월 Meta 기준 ₩3,355,878이 통째로
    LGBTQ가 됐다. 에러는 안 나고 매칭률만 올라가서 더 위험하다.
    """
    sheet = _sheet([*ROWS, ["2026-09-18", "", "扒進你心裡(無刪減)", "", "[D] LGBTQ", "토"]])
    table = G.parse_title_genres(sheet)
    assert "" not in table["by_code"]
    assert G.lookup(table, "0000", "확인불가") is None
    assert G.lookup(table, "", "확인불가") is None
    # 그 행의 중국어 제목은 정상이므로 제목 조인으로는 여전히 찾아야 한다.
    assert G.lookup(table, "", "扒進你心裡(無刪減)") == "[D] LGBTQ"


# ------------------------------------------------------- 조인 우선순위

def test_코드가_제목보다_우선이다():
    """작품명 표기가 갈리므로(`쪽팔려 게임`/`쪽팔려게임`) 코드가 더 믿을 만하다."""
    table = {"by_code": {"141": "[B-1] FANTASY ACTION"}, "by_name": {"다이스": "[E] ETC"}}
    assert G.lookup(table, "141", "다이스") == "[B-1] FANTASY ACTION"


def test_코드가_없으면_제목으로_찾는다():
    """구글 행은 소재명이 `-`라 `title_code`가 없고 `title_kr`만 있다."""
    table = G.parse_title_genres(_sheet(ROWS))
    assert G.lookup(table, "", "참교육") == "[B-2] MODERN ACTION"
    assert G.lookup(table, "0000", "참교육") == "[B-2] MODERN ACTION"


def test_공백만_다른_제목을_흡수한다():
    """`쪽팔려 게임`과 `쪽팔려게임`은 같은 작품이다(실측)."""
    table = G.parse_title_genres(_sheet(ROWS))
    assert G.lookup(table, "", "쪽팔려게임") == "[A-2] SCHOOL ROMANCE"


def test_중국어_제목으로도_찾는다():
    """구글 애셋 이름 보정이 한글 대응을 못 찾으면 중국어 제목을 남긴다."""
    table = G.parse_title_genres(_sheet(ROWS))
    assert G.lookup(table, "", "丟臉遊戲") == "[A-2] SCHOOL ROMANCE"


def test_못_찾으면_None이다():
    """추측해서 채우지 않는다 — 광고주가 장르로 읽는 값이다."""
    table = G.parse_title_genres(_sheet(ROWS))
    assert G.lookup(table, "99999", "없는작품") is None
    assert G.lookup({}, "141", "다이스") is None


# ------------------------------------------------------- 프레임에 붙이기

def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "title_code": ["141", "0000", "2401", "99999"],
        "title_kr": ["다이스", "쪽팔려게임", "참교육", "없는작품"],
        "media": ["Meta", "Google", "TikTok", "Meta"],
        "cost": [100.0, 200.0, 300.0, 400.0],
    })


def test_장르를_붙인다():
    got = G.attach_genre(_frame(), G.parse_title_genres(_sheet(ROWS)))
    assert list(got[G.GENRE_COLUMN]) == [
        "[B-1] FANTASY ACTION",     # 코드로
        "[A-2] SCHOOL ROMANCE",     # 코드가 0000이라 제목으로 (구글 경로)
        "[B-2] MODERN ACTION",
        G.UNKNOWN_GENRE,            # 못 찾음 — 추측하지 않는다
    ]


def test_원본_프레임을_고치지_않는다():
    """이 프레임은 `st.cache_data`가 들고 있다 — 제자리에서 고치면 다음 리런이
    이미 고친 것을 또 고친다."""
    frame = _frame()
    G.attach_genre(frame, G.parse_title_genres(_sheet(ROWS)))
    assert G.GENRE_COLUMN not in frame.columns


def test_표가_없어도_컬럼은_만든다():
    """컬럼 자체가 없으면 그 축을 고른 표가 조용히 빈 표로 죽는다."""
    for table in ({}, None, {"by_code": {}, "by_name": {}}):
        got = G.attach_genre(_frame(), table)
        assert (got[G.GENRE_COLUMN] == G.UNKNOWN_GENRE).all()


def test_컬럼이_없는_프레임에도_안전하다():
    frame = pd.DataFrame({"cost": [1.0, 2.0]})
    got = G.attach_genre(frame, G.parse_title_genres(_sheet(ROWS)))
    assert (got[G.GENRE_COLUMN] == G.UNKNOWN_GENRE).all()


def test_빈_프레임에도_안전하다():
    assert G.attach_genre(pd.DataFrame(), {"by_code": {"1": "x"}}).empty
    assert G.attach_genre(None, {}) is None


def test_소진_합계가_변하지_않는다():
    """장르를 붙이는 것은 컬럼 추가일 뿐 행을 더하거나 빼지 않는다."""
    frame = _frame()
    got = G.attach_genre(frame, G.parse_title_genres(_sheet(ROWS)))
    assert len(got) == len(frame)
    assert got["cost"].sum() == frame["cost"].sum()


# ------------------------------------------------------- 달별 장르표 (3-B)

def _months() -> pd.DataFrame:
    return pd.DataFrame({
        "month": [7, 8, 9],
        "title_code": ["141", "141", "141"],
        "title_kr": ["다이스", "다이스", "다이스"],
        "cost": [10.0, 20.0, 30.0],
    })


LIVE = {"by_code": {"141": "[A-4] ADULT"}, "by_name": {}}
FROZEN_8 = {"by_code": {"141": "[B-1] FANTASY ACTION"}, "by_name": {}}


def test_고정한_달은_저장된_장르표를_쓴다():
    """⚠ **이게 3-B의 핵심 계약이다.**

    장르는 스냅샷을 적용한 **뒤**에 붙는다(그래야 이미 고정된 달에도 장르가 보인다).
    그러면 광고주가 작품을 재분류했을 때 **이미 보낸 달의 표가 조용히 달라진다** —
    마크업 고정이 반쪽이라 같은 사고를 냈던 자리다(2026-09-08).
    그래서 고정 시점의 장르표를 스냅샷 `settings`에 함께 저장하고 그 달만 그걸 쓴다.
    """
    got = G.attach_genre_by_month(_months(), LIVE, {8: FROZEN_8})
    assert list(got[G.GENRE_COLUMN]) == [
        "[A-4] ADULT",            # 7월 — 저장본이 없어 라이브
        "[B-1] FANTASY ACTION",   # 8월 — 고정 당시 값이 이긴다
        "[A-4] ADULT",            # 9월 — 라이브
    ]


def test_저장본이_없으면_라이브로_떨어진다():
    """7·8월은 이 기능이 생기기 전에 고정돼서 저장본이 없다. 소급은 불가능하다 —
    다시 고정하면 그 순간의 라이브 시트를 다시 읽어 **이미 나간 숫자가 움직인다.**"""
    for frozen in (None, {}, {8: {}}, {8: {"by_code": {}, "by_name": {}}}):
        got = G.attach_genre_by_month(_months(), LIVE, frozen)
        assert set(got[G.GENRE_COLUMN]) == {"[A-4] ADULT"}, frozen


def test_month_컬럼이_없으면_라이브만_쓴다():
    frame = pd.DataFrame({"title_code": ["141"], "title_kr": ["다이스"], "cost": [1.0]})
    got = G.attach_genre_by_month(frame, LIVE, {8: FROZEN_8})
    assert got[G.GENRE_COLUMN].iloc[0] == "[A-4] ADULT"


def test_달별로_붙여도_행_수와_소진이_변하지_않는다():
    """조인이 행을 복제하는 것은 고전적인 사고다."""
    frame = _months()
    got = G.attach_genre_by_month(frame, LIVE, {8: FROZEN_8})
    assert len(got) == len(frame) and got["cost"].sum() == frame["cost"].sum()


# ------------------------------------------------------- 미등록 경고

def test_미등록_작품을_소진_큰_순으로_돌려준다():
    got = G.unregistered(G.attach_genre(_frame(), G.parse_title_genres(_sheet(ROWS))))
    assert list(got["title_kr"]) == ["없는작품"]
    assert got["cost"].iloc[0] == 400.0


def test_전부_등록됐으면_빈_표다():
    frame = _frame().iloc[:3]
    got = G.unregistered(G.attach_genre(frame, G.parse_title_genres(_sheet(ROWS))))
    assert got.empty


def test_장르_컬럼이_없으면_빈_표를_돌려준다():
    assert G.unregistered(_frame()).empty
    assert G.unregistered(pd.DataFrame()).empty


# ------------------------------------------------------- 회귀 앵커

def test_다른_마켓_탭을_쓰지_않는다():
    """⚠ `Title_info_raw` 탭에는 **전 마켓이 섞여 있다**(실측 TW 2,196 / TH 1,875 /
    ID 1,703 / FR 1,458 / SP 609 / DE 307). 그쪽으로 옮기게 되면
    `language_code == "TW"` 필터가 필수다 — 지금은 TW 전용인 `title_info`를 쓴다."""
    assert G.TITLE_INFO_SHEET_NAME == "title_info"


def test_죽은_genre_컬럼_이름을_쓰지_않는다():
    """`creative_data`가 Media_RAW의 `유형`을 `genre`로 이미 파싱하는데 **8월 소진의
    100%가 빈값**이다(실측). 이름이 겹치면 "값이 있는데 왜 안 보이나"가 된다."""
    assert G.GENRE_COLUMN == "genre_group" != "genre"
