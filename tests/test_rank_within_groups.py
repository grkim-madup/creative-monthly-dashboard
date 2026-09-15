# -*- coding: utf-8 -*-
"""**그룹 안에서 줄세우기** — 장르 표가 질문에 답하게 만드는 정렬.

규리님(2026-09-16): *"장르별 성과 테이블은 각 매체별로 어떤 장르가 효율이 좋은가를
보는 게 목적이야. 지금 있는 테이블들은 그 질문에 답을 해주지 못해."*

`aggregate_by`는 **항상 소진액 내림차순**이라 매체·OS가 뒤섞여 나열된다. 그러면
"TikTok 안에서 어느 장르가 좋나"를 읽으려고 눈으로 같은 매체 줄을 모아야 한다.
"""
from __future__ import annotations

import pandas as pd

from creative_data import (
    MEDIA_ORDER,
    OS_ORDER,
    UNRANKED_VALUES,
    sort_within_groups,
)

ROWS = [{"field": "media"}, {"field": "os"}, {"field": "genre_group"}]


def _table(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["media", "os", "genre_group", "cost", "CPI"])


def _order(table: pd.DataFrame) -> list[tuple]:
    return [(r.media, r.os, r.genre_group) for r in table.itertuples(index=False)]


# ------------------------------------------------------- 그룹 순서

def test_매체_순서는_틱톡_메타_구글이다():
    """규리님 지정. **소진액 순이 아니라 고정 순서**다 — 매달 순서가 바뀌면 지난달
    리포트와 나란히 놓고 읽을 수가 없다."""
    assert MEDIA_ORDER == ("TikTok", "Meta", "Google")
    table = _table([
        ("Google", "AOS", "A", 100.0, 10.0),
        ("Meta",   "AOS", "A", 100.0, 10.0),
        ("TikTok", "AOS", "A", 100.0, 10.0),
    ])
    got = sort_within_groups(table, ROWS)
    assert list(got["media"]) == ["TikTok", "Meta", "Google"]


def test_AOS가_iOS보다_먼저다():
    assert OS_ORDER == ("AOS", "iOS")
    table = _table([
        ("TikTok", "iOS", "A", 100.0, 10.0),
        ("TikTok", "AOS", "A", 100.0, 10.0),
    ])
    assert list(sort_within_groups(table, ROWS)["os"]) == ["AOS", "iOS"]


def test_소진액이_커도_매체_순서가_이긴다():
    """⚠ 여기가 예전 동작과 갈리는 지점이다 — `aggregate_by`는 소진액으로만 세운다."""
    table = _table([
        ("Google", "AOS", "A", 9_000_000.0, 10.0),
        ("TikTok", "AOS", "B",    10_000.0, 20.0),
    ])
    assert list(sort_within_groups(table, ROWS)["media"]) == ["TikTok", "Google"]


def test_모르는_매체는_뒤로_간다():
    table = _table([
        ("Appier", "AOS", "A", 100.0, 10.0),
        ("Meta",   "AOS", "A", 100.0, 10.0),
    ])
    assert list(sort_within_groups(table, ROWS)["media"]) == ["Meta", "Appier"]


# ------------------------------------------------------- 그룹 안 순위

def test_그룹_안에서_소진액_내림차순이다():
    """규리님(2026-09-16): *"각 매체별 OS별 장르의 정렬은 소진액 높은순으로."*

    ⚠ 처음에는 효율(CPI) 순으로 세웠는데, 소진 ₩188,722짜리가 ₩5,642,184짜리보다
    위에 와서 **규모가 안 읽혔다.** 효율은 색이 말한다(1등 초록 / 꼴찌 빨강) —
    정렬과 색이 서로 다른 것을 말하게 나눠 둔 것이다.
    """
    table = _table([
        ("TikTok", "AOS", "적게",   188_722.0, 1275.0),   # CPI는 가장 좋다
        ("TikTok", "AOS", "많이", 5_642_184.0, 1319.0),
        ("TikTok", "AOS", "중간", 1_435_072.0, 1421.0),
    ])
    assert list(sort_within_groups(table, ROWS)["genre_group"]) == ["많이", "중간", "적게"]


def test_효율이_좋아도_소진이_작으면_아래다():
    table = _table([
        ("TikTok", "AOS", "효율최고", 100.0, 1.0),
        ("TikTok", "AOS", "돈많이",  900.0, 9999.0),
    ])
    assert list(sort_within_groups(table, ROWS)["genre_group"]) == ["돈많이", "효율최고"]


def test_소진이_없는_줄은_그룹_맨_뒤다():
    table = _table([
        ("TikTok", "AOS", "값없음", 0.0, float("nan")),
        ("TikTok", "AOS", "있음",  100.0, 5000.0),
    ])
    assert list(sort_within_groups(table, ROWS)["genre_group"]) == ["있음", "값없음"]


def test_미분류는_소진이_커도_그룹_맨_뒤다():
    """⚠ **실제로 1위로 올라왔다** — 8월 Google AOS에서 `미분류`가 소진 ₩22.1M으로
    모든 장르보다 컸다. 분류가 안 된 것이지 하나의 분류가 아니다.
    숨기지는 않는다(소진이 맞아떨어져야 한다) — 뒤로만 보낸다."""
    table = _table([
        ("TikTok", "AOS", "미분류", 900.0, 1000.0),
        ("TikTok", "AOS", "진짜장르", 100.0, 5000.0),
    ])
    assert list(sort_within_groups(table, ROWS)["genre_group"]) == ["진짜장르", "미분류"]


def test_미분류를_지우지는_않는다():
    table = _table([
        ("TikTok", "AOS", "미분류", 700.0, 1000.0),
        ("TikTok", "AOS", "장르",   300.0, 5000.0),
    ])
    got = sort_within_groups(table, ROWS)
    assert len(got) == 2 and got["cost"].sum() == 1000.0


def test_후순위_값_목록():
    assert "미분류" in UNRANKED_VALUES and "확인불가" in UNRANKED_VALUES


# ------------------------------------------------------- 안전장치

def test_행이_하나면_그대로_둔다():
    """묶을 그룹이 없다 — 마지막 축이 곧 유일한 축이다."""
    table = _table([("TikTok", "AOS", "A", 100.0, 10.0)])
    got = sort_within_groups(table, [{"field": "genre_group"}])
    assert _order(got) == _order(table)


def test_소진액_컬럼이_없으면_그대로_둔다():
    table = pd.DataFrame([("TikTok", "AOS", "A", 10.0)],
                         columns=["media", "os", "genre_group", "CPI"])
    got = sort_within_groups(table, ROWS)
    assert list(got["genre_group"]) == ["A"]


def test_빈_표에도_안전하다():
    assert sort_within_groups(pd.DataFrame(), ROWS).empty
    assert sort_within_groups(None, ROWS) is None


def test_보조_컬럼을_남기지_않는다():
    """정렬용 임시 컬럼이 표에 남으면 광고주 화면에 그대로 나간다."""
    table = _table([("TikTok", "AOS", "A", 100.0, 10.0)])
    got = sort_within_groups(table, ROWS)
    assert list(got.columns) == list(table.columns)


def test_행_수와_합계가_변하지_않는다():
    table = _table([
        ("TikTok", "AOS", "A", 100.0, 10.0),
        ("Meta",   "iOS", "B", 200.0, 20.0),
        ("Google", "AOS", "C", 300.0, 30.0),
    ])
    got = sort_within_groups(table, ROWS)
    assert len(got) == 3 and got["cost"].sum() == 600.0
