# -*- coding: utf-8 -*-
"""섹션 3에 구글을 **같은 블록 안 별도 표**로 넣기 위한 집계 (A안, 2026-09-10 승인).

⚠ 이 표를 메타/틱톡과 **같은 표에 합치면 안 된다.** 구글은 캠페인 비용이 애셋
유형별로 나뉘어 배분되고 소진·설치가 다른 비율로 배분돼서, 애셋 단위 CPI가 실제보다
33% 낮다(실측 2026-08: ₩2,429 vs ₩3,624). 광고주 발송물에서 구글이 부당하게 좋아
보인다 — 그래서 별도 표 + 배분 각주다.
"""
from __future__ import annotations

import pandas as pd

import google_ads_report as G


def _assets() -> pd.DataFrame:
    """애셋 보고서 모양의 작은 표. 비율은 일부러 행마다 다르게 둔다."""
    return pd.DataFrame({
        "asset": ["u1", "u2", "u3", "u4", "u5"],
        "asset_type": ["YouTube 동영상", "이미지", "YouTube 동영상", "이미지", "설명"],
        "title_kr": ["참교육", "참교육", "쪽팔려게임", "쪽팔려게임", "참교육"],
        "os": ["AOS", "AOS", "iOS", "iOS", "AOS"],
        "objective": ["ACi (설치)", "ACi (설치)", "ACa (액션)", "ACa (액션)", "ACi (설치)"],
        "campaign": ["c1", "c1", "c2", "c2", "c1"],
        "impression": [1000, 3000, 2000, 4000, 500],
        "click": [100, 60, 40, 40, 5],
        "cost": [10000.0, 20000.0, 30000.0, 40000.0, 5000.0],
        "total install": [10, 10, 20, 20, 1],
        "in_app_action": [5, 0, 10, 0, 0],
    })


# ------------------------------------------------------- 어휘

def test_애셋에_없는_지표를_넣지_않는다():
    """`D0 read`·`D0 coin`·`D7 coin`은 애셋 단위에 값이 없다(구조적 부재)."""
    for column in ("D0 read", "D0 coin", "D7 coin",
                   "D0 read CVR", "D0 coin CVR", "D7 coin CVR"):
        assert column not in G.GOOGLE_METRIC_COLUMNS, column


def test_소재명_파싱_축을_넣지_않는다():
    """구글은 소재 식별자가 URL이라 이 축들이 전부 빈 값이 된다 —
    예전에 넣었다가 가짜 `미분류` 버킷이 생겼다(커밋 `883600f`)."""
    for field in ("ad", "creative_type", "format", "size", "producer_group",
                  "usp", "extra_info_tag", "mix_group"):
        assert field not in G.GOOGLE_DIMENSIONS, field


def test_장르_축을_넣지_않는다():
    """장르는 `Media_RAW` 프레임에 붙는다(`title_genre.attach_genre`). 구글 애셋
    프레임은 Drive 보고서에서 별도로 오므로 그 컬럼이 **아예 없다** — 넣으면
    `google_pivot`이 조용히 빈 표를 낸다(`rows`에 없는 컬럼은 걸러진다)."""
    assert "genre_group" not in G.GOOGLE_DIMENSIONS


def test_기본_축은_작품이다():
    """2026-09-09에 작품명 보정이 들어가 쓸 수 있게 됐다."""
    assert G.GOOGLE_DEFAULT_ROWS == ["title_kr"]
    assert "title_kr" in G.GOOGLE_DIMENSIONS


# ------------------------------------------------------- 집계 불변식

def test_축을_바꿔도_소진_합계가_같다():
    """실데이터에서도 확인했다(2026-08 영상+이미지 ₩67,751,670)."""
    frame = _assets()
    totals = {tuple(rows): G.google_pivot(frame, rows=rows)["cost"].sum()
              for rows in (["title_kr"], ["asset_type"], ["os"], ["title_kr", "os"])}
    assert len(set(round(v, 2) for v in totals.values())) == 1, totals


def test_텍스트_애셋은_빠진다():
    """`설명`·`광고 제목`·`앱 딥 링크`는 소재로 볼 수 없다."""
    frame = _assets()
    table = G.google_pivot(frame)          # creative_only 기본 True
    # 설명 행의 소진 5,000이 빠져야 한다.
    assert round(table["cost"].sum(), 2) == 100000.0
    with_text = G.google_pivot(frame, creative_only=False)
    assert round(with_text["cost"].sum(), 2) == 105000.0


def test_비율은_합계에서_재계산한다():
    """행별 평균을 내면 큰 행이 작은 행에 묻힌다 — 다른 섹션과 같은 규칙."""
    table = G.google_pivot(_assets(), rows=["title_kr"])
    row = table[table["title_kr"] == "참교육"].iloc[0]
    # 영상+이미지만: 노출 4,000 · 클릭 160 → CTR 4%
    assert round(float(row["CTR"]), 4) == 0.04
    # 소진 30,000 / 설치 20 → CPI 1,500
    assert round(float(row["CPI"]), 2) == 1500.0


def test_인앱_CPA는_액션이_없으면_비운다():
    """0으로 나누면 무한이 되고, 0으로 채우면 "CPA가 0원"으로 읽힌다."""
    table = G.google_pivot(_assets(), rows=["title_kr"])
    row = table[table["title_kr"] == "쪽팔려게임"].iloc[0]
    # 소진 70,000 / 인앱 액션 10건 = 7,000. (설치 20건이 아니라 **액션** 수로 나눈다)
    assert float(row["인앱 CPA"]) == 7000.0
    frame = _assets()
    frame["in_app_action"] = 0
    empty = G.google_pivot(frame, rows=["title_kr"])
    assert empty["인앱 CPA"].isna().all()


# ------------------------------------------------------- 필터

def test_필터는_AND다():
    table = G.google_pivot(_assets(), rows=["title_kr"],
                           filters={"os": ["AOS"], "asset_type": ["이미지"]})
    assert len(table) == 1
    assert round(table["cost"].sum(), 2) == 20000.0


def test_빈_필터는_아무것도_걸지_않는다():
    frame = _assets()
    base = G.google_pivot(frame)["cost"].sum()
    for empty in ({}, {"os": []}, {"os": ""}, {"없는컬럼": ["x"]}):
        assert G.google_pivot(frame, filters=empty)["cost"].sum() == base, empty


def test_값_순서는_정본_목록_순서다():
    """고른 순서가 아니다 — 다른 표와 같은 규칙."""
    table = G.google_pivot(_assets(), values=["CPI", "cost", "CTR"])
    assert list(table.columns) == ["title_kr", "cost", "CTR", "CPI"]


def test_빈_프레임에도_안전하다():
    assert G.google_pivot(pd.DataFrame()).empty
    assert G.google_pivot(None).empty
    assert G.google_pivot(_assets(), rows=["없는축"]).empty


# ------------------------------------------------------- 배분 비율

def test_배분_비율을_계산한다():
    """각주에 **매달 계산해서** 찍는다 — 박아두면 다음 달에 거짓말이 된다."""
    assets = pd.DataFrame({"cost": [100.0], "total install": [10]})
    real = pd.DataFrame({"cost": [50.0], "total install": [10]})
    gap = G.allocation_gap(assets, real)
    assert gap["cost_ratio"] == 2.0
    assert gap["install_ratio"] == 1.0
    assert gap["cpi_ratio"] == 2.0            # 애셋 CPI 10 vs 실제 5


def test_진짜_집행액이_없으면_비율을_내지_않는다():
    """추정해서 채우면 광고주에게 틀린 근거가 간다."""
    gap = G.allocation_gap(pd.DataFrame({"cost": [100.0], "total install": [10]}), None)
    assert gap["cost_ratio"] is None
    assert gap["cpi_ratio"] is None


def test_배분_각주가_있다():
    """광고주도 봐야 하는 문구다 — 편집 모드 안에 감싸면 안 된다."""
    note = G.GOOGLE_ALLOCATION_NOTE
    assert "배분" in note and "CPI 비교에 쓸 수 없" in note
