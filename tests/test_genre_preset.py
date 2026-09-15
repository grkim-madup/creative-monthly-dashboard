# -*- coding: utf-8 -*-
"""`＋ 장르 성과` 프리셋 — **버튼 한 번 = 표 세 개 + 제목**.

규리님(2026-09-16): *"대시보드에선 모든 수작업은 최소한으로 들어가야 해."*

장르는 위 주제 후보(`topics.candidates`)와 성격이 다르다. 태그·유형은 매달 새로
생기고 사라져서 "이번 달 신규/급증"이 뜻을 갖지만, **장르는 10종이 고정이고 매달
같다.** 그래서 후보 목록에 얹지 않고 프리셋 버튼으로 뺐다.
"""
from __future__ import annotations

import ast
import pathlib

import pandas as pd
import pytest

import topics
from creative_data import title_level_allowed
from view_state import view_with_defaults

ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def entrypoints():
    found = [(n, pathlib.Path(n).read_text(encoding="utf-8"))
             for n in ENTRYPOINTS if pathlib.Path(n).exists()]
    if not found:
        pytest.skip("진입점을 찾지 못했습니다")
    return found


# ------------------------------------------------------- 표 세 개

def test_표가_두_개다():
    """⚠ `장르별 작품 성과`는 **자동 생성하지 않는다**(규리님 2026-09-16) — 장르 표의
    질문은 "매체별로 어떤 장르가 좋은가"이고 작품 단위는 그 질문에 답하지 않는다."""
    views = topics.genre_preset_views()
    assert len(views) == 2
    assert [v["label"] for v in views] == ["매체·OS별 장르 효율", "OS별 장르 효율"]


def test_효율_표는_장르를_마지막_행에_둔다():
    """⚠ **이게 규리님 질문에 답하는 구조다** — *"각 매체별로 어떤 장르가 효율이
    좋은가"*. `rank_within_groups`가 **마지막 축**을 그룹 안에서 줄세우므로, 장르가
    맨 뒤에 와야 매체·OS 묶음 안에서 장르가 순위대로 선다.

    장르를 첫 행에 두면 예전처럼 매체가 뒤섞여 나열되어 그 질문에 답을 못 한다.
    """
    first, second = topics.genre_preset_views()
    assert [r["field"] for r in first["rows"]] == ["media", "os", topics.GENRE_FIELD]
    assert [r["field"] for r in second["rows"]] == ["os", topics.GENRE_FIELD]


def test_효율_표는_CPI로_줄세운다():
    for view in topics.genre_preset_views():
        assert view["rank_by"] == "CPI", view["label"]


def test_구글이_미리_켜져_있다():
    """장르 표에서 구글을 빼면 소진의 1/3이 빠져 답이 반쪽이 된다."""
    for view in topics.genre_preset_views():
        assert view["title_level"] is True


def test_세_표_모두_작품_단위로_성립한다():
    """⚠ 소재 축이 하나라도 섞이면 화면이 조용히 소재 단위로 되돌린다 — 그러면
    구글이 사라지는데 토글은 켜져 보인다."""
    for view in topics.genre_preset_views():
        got = view_with_defaults(view)
        assert title_level_allowed(got["rows"], got["filters"]), view["label"]
        assert got["title_level"] is True, view["label"]


def test_id를_박아_둔다():
    """⚠ 비우면 `view_with_defaults`가 리런마다 새 uuid를 발급해 위젯 상태·셀 강조가
    앵커를 잃는다(`preset_views`와 같은 이유)."""
    views = topics.genre_preset_views()
    ids = [v["id"] for v in views]
    assert all(ids) and len(set(ids)) == len(views)


def test_뷰마다_다른_객체다():
    """⚠ 얕은 복사로 안쪽 리스트를 공유하면 한 표를 고칠 때 다른 표가 따라 바뀐다
    (`a76aaa2`와 같은 유형)."""
    a, b = topics.genre_preset_views()
    a["values"].append("침입")
    assert "침입" not in b["values"]
    a["filters"]["x"] = ["y"]
    assert b["filters"] == {}


def test_소재_단위_지표를_넣지_않는다():
    """작품 단위 표라 소재명 파싱에서 오는 것은 값으로도 쓰지 않는다."""
    for view in topics.genre_preset_views():
        assert "ad" not in view["values"]


# ------------------------------------------------------- 제목

def test_제목에_요약을_붙이지_않는다():
    """규리님(2026-09-16): *"블록 제목은 그냥 장르별 성과로만 써줘."*
    예전에는 `장르별 성과 · AOS FANTASY ACTION / iOS ADULT`처럼 계산한 요약을 붙였다.
    그 판단은 표와 인사이트 초안이 이미 말하고, 매달 제목이 달라지면 목차에서 같은
    주제로 안 읽힌다."""
    assert topics.GENRE_TITLE == "장르별 성과"
    assert not hasattr(topics, "genre_headline"), "죽은 요약 코드가 남아 있다"


# ------------------------------------------------------- 화면 배선 (AST)

def test_버튼이_주제_추가_팝오버_안에_있다():
    """⚠ 별도 버튼으로 두면 **버튼 줄이 두 줄이 된다**(규리님 2026-09-16).
    장르는 후보 목록(신규/급증)에는 얹을 수 없지만 — 10종이 고정이라 "이번 달 새로
    등장"이 성립하지 않는다 — 같은 팝오버 안에는 들어갈 수 있다."""
    for name, source in entrypoints():
        assert "장르별 성과 만들기" in source, f"{name}: 프리셋 버튼이 없다"
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "topic_picker")
        assert "장르별 성과 만들기" in ast.unparse(fn), (
            f"{name}: 버튼이 주제 추가 팝오버 밖에 있다")


def test_한_번의_커밋으로_만든다():
    """⚠ `add_block` 후 따로 저장하면 **표가 없는 빈 블록**이 저장되는 순간이 생긴다
    (`add_topic_block`이 같은 이유로 한 커밋이다)."""
    for name, source in entrypoints():
        fn = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "add_genre_block")
        body = ast.unparse(fn)
        assert body.count("commit_blocks") == 1, name
        inner = next(n for n in ast.walk(fn)
                     if isinstance(n, ast.FunctionDef) and n.name == "_fn")
        text = ast.unparse(inner)
        assert "add_block" in text and "update_block" in text, (
            f"{name}: 블록 생성과 표 채우기가 한 커밋이 아니다")


# ------------------------------------------------------- 인사이트 초안

def _scope(rows) -> pd.DataFrame:
    """`aggregate_by`가 파생 지표를 다시 계산하므로 **원시 지표를 전부** 준다.

    ⚠ 하나라도 빠지면 `KeyError`다(실제로 `D7 coin`을 빼먹어 실패했다) — 지표를
    늘릴 때 이 픽스처도 같이 봐야 한다.
    """
    frame = pd.DataFrame(rows, columns=[
        "genre_group", "os", "media", "cost", "impression", "click",
        "total install", "D0 read", "D0 coin"])
    frame["D7 read"] = frame["D0 read"]
    frame["D7 coin"] = frame["D0 coin"]
    return frame


def test_초안이_OS마다_최저_CPI_장르를_짚는다():
    import insight_draft

    scope = _scope([
        ("[B-1] FANTASY ACTION", "AOS", "Meta", 10000.0, 1000.0, 100.0, 100.0, 50.0, 5.0),
        ("[A-4] ADULT",          "AOS", "Meta", 10000.0, 1000.0, 100.0,  20.0, 10.0, 1.0),
        ("[A-4] ADULT",          "iOS", "Meta", 10000.0, 1000.0, 100.0, 100.0, 50.0, 5.0),
        ("[C] THRILLER & HORROR", "iOS", "Meta", 10000.0, 1000.0, 100.0, 20.0, 10.0, 1.0),
    ])
    lines = insight_draft.genre_lines(scope, 8)
    body = "\n".join(lines)
    assert "AOS 최저 CPI — [B-1] FANTASY ACTION" in body
    assert "iOS 최저 CPI — [A-4] ADULT" in body
    assert "OS별로 효율이 갈림" in body


def test_초안이_조사를_틀리지_않는다():
    """⚠ `ACTION가`·`ADULT이` 가 실제로 나왔다. 영문 장르명 뒤 주격 조사를 아예
    만들지 않도록 개조식으로 쓴다(실제 리포트 문체와도 맞는다)."""
    import insight_draft

    scope = _scope([
        ("[B-1] FANTASY ACTION", "AOS", "Meta", 10000.0, 1000.0, 100.0, 100.0, 50.0, 5.0),
        ("[A-4] ADULT",          "iOS", "Meta", 10000.0, 1000.0, 100.0, 100.0, 50.0, 5.0),
    ])
    body = "\n".join(insight_draft.genre_lines(scope, 8))
    for wrong in ("ACTION가", "ACTION이", "ADULT이", "ADULT가", "ACTION는", "ADULT은"):
        assert wrong not in body, wrong


def test_설치가_없는_OS는_판단_불가로_남긴다():
    """7월 iOS가 실제로 이렇다 — 메타·틱톡 iOS 설치는 8월부터 들어온다.
    **없는 판단을 지어내지 않는다.**"""
    import insight_draft

    scope = _scope([
        ("[A-1] MODERN ROMANCE", "iOS", "Meta", 10000.0, 1000.0, 100.0, 0.0, 0.0, 0.0),
    ])
    body = "\n".join(insight_draft.genre_lines(scope, 7))
    assert "설치가 집계되지 않아 효율 판단 불가" in body


def test_예시_자리는_비운다():
    """⚠ `ex)`에 예시를 지어 넣으면 광고주에게 없는 사실이 간다."""
    import insight_draft

    scope = _scope([
        ("[B-1] FANTASY ACTION", "AOS", "Meta", 10000.0, 1000.0, 100.0, 100.0, 50.0, 5.0),
        ("[A-4] ADULT",          "iOS", "Meta", 10000.0, 1000.0, 100.0, 100.0, 50.0, 5.0),
    ])
    body = "\n".join(insight_draft.genre_lines(scope, 8))
    assert "ex) (확인 필요)" in body


def test_미분류는_초안에_안_쓴다():
    import insight_draft

    scope = _scope([
        ("미분류",       "AOS", "Meta", 90000.0, 9000.0, 900.0, 900.0, 400.0, 40.0),
        ("[A-4] ADULT", "AOS", "Meta", 10000.0, 1000.0, 100.0,  50.0,  20.0,  2.0),
    ])
    body = "\n".join(insight_draft.genre_lines(scope, 8))
    assert "미분류" not in body


def test_빈_표에는_아무_말도_안_한다():
    import insight_draft

    assert insight_draft.genre_lines(pd.DataFrame(), 8) == []
    assert insight_draft.genre_lines(_scope([]), 8) == []


def test_화면이_장르_표를_따로_가른다():
    """장르 표를 소재 단위 서사(대조군·swing)에 섞으면 "이 소재군이 기존 대비"라는
    문장이 성립하지 않는 표에 그 문장을 붙이게 된다."""
    for name, source in entrypoints():
        assert "genre_views" in source, f"{name}: 장르 표를 가르지 않는다"
        assert '"kind": "genre"' in source or "'kind': 'genre'" in source, name
