# -*- coding: utf-8 -*-
"""작품 단위 집계(`title_level`) — **구글을 담되 가짜 버킷은 안 만든다.**

구글은 `Media_RAW`에 `ad == "-"`로 들어오므로 소재 단위 프레임(`named_overview`)에서
구조적으로 빠져 있다. 장르는 소재가 아니라 작품 속성이라 소재명이 없어도 집계되므로,
장르 표에서는 구글을 담아야 답이 반쪽이 되지 않는다(구글이 소진의 1/3이다).

⚠ 그런데 **소재 단위 축이 하나라도 섞이면** 구글 행이 전부 `미분류` 한 줄로 뭉쳐
표에 **가짜 버킷**이 생긴다 — 커밋 `883600f`와 정확히 같은 사고다. 이 파일이 그
게이트를 지킨다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import view_state
import pandas as pd

from creative_data import (
    TITLE_LEVEL_FIELDS,
    UNATTRIBUTABLE,
    drop_unattributable,
    title_level_allowed,
)

ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def entrypoints():
    found = [(n, pathlib.Path(n).read_text(encoding="utf-8"))
             for n in ENTRYPOINTS if pathlib.Path(n).exists()]
    if not found:
        pytest.skip("진입점을 찾지 못했습니다")
    return found


# ------------------------------------------------------- 게이트

def test_작품_단위_축만이면_허용한다():
    assert title_level_allowed([{"field": "genre_group"}, {"field": "os"}])
    assert title_level_allowed([{"field": "title_kr"}], {"media": ["Meta"]})


def test_소재_단위_축이_섞이면_막는다():
    """구글 행이 이 축들에서 전부 빈 값이 된다 — 가짜 `미분류` 버킷의 원인."""
    for field in ("creative_type", "usp", "format", "size", "ad",
                  "extra_info_tag", "mix_group", "producer_group", "orientation"):
        assert not title_level_allowed([{"field": "genre_group"}, {"field": field}]), field


def test_필터에_섞여도_막는다():
    """행만 보면 안 된다 — 필터도 구글 행을 통째로 날린다."""
    assert not title_level_allowed([{"field": "genre_group"}], {"creative_type": ["MIX"]})


def test_값이_없는_필터는_세지_않는다():
    """화면에서 구분만 고르고 값을 안 고른 필터는 아무것도 걸지 않는다."""
    assert title_level_allowed([{"field": "genre_group"}], {"creative_type": []})


def test_축이_하나도_없으면_허용하지_않는다():
    """행도 필터도 없으면 그 달 전체 한 줄이다 — 켤 이유가 없다."""
    assert not title_level_allowed([], {})


def test_문자열_행도_받는다():
    """`normalize_rows` 전후 어느 쪽이 와도 같은 답이어야 한다."""
    assert title_level_allowed(["genre_group", "os"])


def test_작품_단위_축_목록():
    """늘릴 때는 **구글 행에 그 값이 실제로 있는지** 확인하고 넣을 것."""
    assert TITLE_LEVEL_FIELDS == {"genre_group", "title_kr", "title_code", "media", "os"}


# ------------------------------------------------------- 귀속 불가 행 제외

def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "media": ["Google", "Google", "Meta", "TikTok"],
        "os": ["AOS", "iOS", "iOS", "AOS"],
        "cost": [100.0, 200.0, 300.0, 400.0],
        "total install": [10.0, 0.0, 30.0, 40.0],
    })


def test_구글_iOS를_뺀다():
    """⚠ **실측으로 찾은 진짜 데이터 문제다**(2026-09-16, 8월 UA).

    구글 iOS는 `Media_RAW`에 작품별 소진 행과 캠페인 단위 설치 행이 **따로** 들어오고
    둘이 조인되지 않는다 — 소진 ₩40,952,170은 작품에 붙어 있는데 설치 9,965건은 전부
    `title_kr = 확인불가` · 소진 ₩0인 별도 행 62개에 있다. 그대로 두면 표가 양방향으로
    틀린다: `미분류 iOS`가 CPI ₩0(설치만), 실제 장르의 iOS는 CPI가 비거나 부풀려진다.
    """
    out, notes = drop_unattributable(_frame())
    assert len(out) == 3
    assert not ((out["media"] == "Google") & (out["os"] == "iOS")).any()
    assert notes and notes[0][0] == "Google iOS" and notes[0][1] == 200.0


def test_구글_AOS는_빼지_않는다():
    """구글 AOS는 같은 행에 소재·설치가 함께 있어 정상이다 — 빼면 ₩71,971,025이
    이유 없이 사라진다."""
    out, _ = drop_unattributable(_frame())
    assert ((out["media"] == "Google") & (out["os"] == "AOS")).any()


def test_메타_틱톡은_건드리지_않는다():
    out, _ = drop_unattributable(_frame())
    assert set(out["media"]) == {"Google", "Meta", "TikTok"}


def test_뺀_이유를_함께_돌려준다():
    """**말없이 빼면** 광고주가 1번 총괄과 대조하며 어긋난 금액을 본다."""
    _, notes = drop_unattributable(_frame())
    assert "캠페인 단위" in notes[0][2]


def test_해당_행이_없으면_사유도_없다():
    frame = _frame()
    frame = frame[~((frame["media"] == "Google") & (frame["os"] == "iOS"))]
    out, notes = drop_unattributable(frame)
    assert notes == [] and len(out) == len(frame)


def test_빈_프레임과_컬럼_누락에도_안전하다():
    assert drop_unattributable(pd.DataFrame())[1] == []
    assert drop_unattributable(pd.DataFrame({"cost": [1.0]}))[1] == []
    assert drop_unattributable(None)[1] == []


def test_제외_목록():
    """늘릴 때는 **소진과 설치가 같은 행에 있는지** 실데이터로 확인하고 넣을 것."""
    assert set(UNATTRIBUTABLE) == {("Google", "iOS")}


def test_소재_단위_표에서는_빼지_않는다():
    """`named_overview`에는 구글이 애초에 없다 — 거기까지 손대면 2·4번 섹션 숫자가
    바뀐다(광고주에게 이미 나간 표다)."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_view")
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and "drop_unattributable" in ast.unparse(node.func):
                parent = ast.unparse(fn)
                at = parent.find("drop_unattributable")
                guard = parent.rfind("if view['title_level']", 0, at)
                assert guard > 0, f"{name}: 작품 단위 표 밖에서도 행을 뺀다"


# ------------------------------------------------------- 뷰 정규화

def test_기본값은_꺼짐이다():
    """기존에 저장된 표가 한 줄도 안 바뀌어야 한다."""
    assert view_state.VIEW_DEFAULTS["title_level"] is False
    assert view_state.view_with_defaults({"rows": [{"field": "genre_group"}]})["title_level"] is False


def test_소재_축이_섞이면_읽을_때_강제로_끈다():
    """⚠ 화면에서 토글을 감추는 것만으로는 부족하다 — 켠 뒤에 축을 바꾸면 저장된
    True가 그대로 남아 다음에 열 때 가짜 버킷이 생긴다."""
    got = view_state.view_with_defaults({
        "title_level": True,
        "rows": [{"field": "genre_group"}, {"field": "creative_type"}],
    })
    assert got["title_level"] is False


def test_허용되면_켠_채로_남는다():
    got = view_state.view_with_defaults({
        "title_level": True, "rows": [{"field": "genre_group"}, {"field": "os"}],
    })
    assert got["title_level"] is True


def test_작품_단위에서는_대조군과_썸네일을_끈다():
    """대조군은 "같은 범위에서 이 소재군을 뺀 나머지"라 소재 단위 프레임을 전제한다."""
    got = view_state.view_with_defaults({
        "title_level": True, "rows": [{"field": "genre_group"}],
        "contrast": True, "thumbs": True, "include_ads": ["어떤소재"],
    })
    assert got["contrast"] is False and got["thumbs"] is False
    assert got["include_ads"] == []


def test_구글_표에서는_꺼진다():
    """`kind == "google"`은 Drive 애셋 프레임이라 이 토글과 무관하다."""
    got = view_state.view_with_defaults({"kind": "google", "title_level": True})
    assert got["title_level"] is False


def test_위젯에서_저장된다():
    session = {"pvtl_k": True, "pvrows_k": ["genre_group", "os"]}
    got = view_state.view_from_widgets({"id": "v1"}, "k", session)
    assert got["title_level"] is True


def test_저장할_때도_다시_판정한다():
    """저장본에 거짓 True가 남으면, 나중에 축을 되돌렸을 때 켠 적 없는 토글이 켜진다."""
    session = {"pvtl_k": True, "pvrows_k": ["genre_group", "creative_type"]}
    assert view_state.view_from_widgets({"id": "v1"}, "k", session)["title_level"] is False


# ------------------------------------------------------- 화면 배선 (AST)

def test_화면이_프레임을_갈아끼운다():
    """토글만 있고 프레임을 안 바꾸면 구글이 여전히 안 들어온다 — 조용히 아무 일도
    일어나지 않는 유형이다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_view")
        body = ast.unparse(fn)
        assert 'overview if view[\'title_level\'] else named_overview' in body, name


def test_판정을_두_곳에서_하지_않는다():
    """`view_with_defaults`가 이미 판정했다. 렌더에서 또 물으면 두 판정이 갈린다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_view")
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "title_level_allowed" not in used, f"{name}: 렌더에서 다시 판정한다"


def test_각주가_편집_모드_밖이다():
    """분모가 다른 이유는 **광고주도 봐야 한다** — 2·4번 섹션과 대조하기 때문이다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_view")
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and "editing" in ast.unparse(node.test):
                assert "작품 단위</b> 집계" not in ast.unparse(node), (
                    f"{name}: 작품 단위 각주가 편집 모드 안에 있다")


def test_장르를_스냅샷_뒤에_붙인다():
    """⚠ 파싱 단계에 붙이면 **이미 고정된 7·8월에 그 컬럼이 없다** — `apply`가
    pd.NA로 채우고 화면에서 그 달 전체가 `미분류` 한 줄로 뭉친다(다시 고정하기
    전까지 복구 불가). 조인키는 고정본에도 있으므로 뒤에 붙이면 과거 달도 정상이다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "_media_frozen")
        body = ast.unparse(fn)
        apply_at = body.find("media_snapshot.apply")
        genre_at = body.find("attach_genre_by_month")
        assert apply_at > 0 and genre_at > 0, name
        assert apply_at < genre_at, f"{name}: 장르를 스냅샷보다 먼저 붙인다"


def test_파싱_단계에_장르를_넣지_않는다():
    """`sheet_loader.load_media_raw`는 parquet에 캐시된다 — 거기 붙이면 고정본과
    같은 문제가 생기고 `PARSER_VERSION`도 올려야 한다."""
    source = pathlib.Path("sheet_loader.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "load_media_raw")
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "attach_genre" not in used and "attach_genre_by_month" not in used


def test_고정할_때_장르표를_함께_저장한다():
    """3-B 계약. 안 저장하면 광고주가 작품을 재분류했을 때 이미 보낸 달의 표가
    조용히 달라진다(마크업 고정이 반쪽이었던 것과 같은 자리다)."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "freeze_month")
        assert "genre_table" in ast.unparse(fn), f"{name}: 장르표를 안 얼린다"


def test_고정된_장르표를_읽는다():
    """저장만 하고 안 읽으면 아무 일도 일어나지 않는다 — 조용한 실패 유형."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "_frozen_genre_tables")
        assert "genre_table" in ast.unparse(fn), name


def test_미등록_경고는_권한으로_가린다():
    """`editor_allowed`는 권한이지 모드가 아니다 — 규리님은 보기 모드에서도 보이고
    그 화면을 광고주에게 공유한다."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "render_genre_gap")
        body = ast.unparse(fn)
        assert "auth.can_edit()" in body, f"{name}: 미등록 경고에 권한 게이트가 없다"
