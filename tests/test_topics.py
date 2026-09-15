"""주제 후보 발굴과 표 프리셋 규칙을 고정한다.

이 규칙은 광고주 리포트에서 "이번 달 무엇을 분석할까"를 제안하는 자리라, 조용히 바뀌면
어떤 소재군이 통째로 리포트에서 빠질 수 있다. 판정 문턱과 제외 규칙을 여기서 못 박는다.
"""

from __future__ import annotations

import pandas as pd
import pytest

import topics


#: ⚠ 아래 대부분의 테스트는 `min_ads=1`로 부른다. 픽스처가 소재 하나짜리라서인데,
#: 그 테스트들의 관심사는 신규/급증·노이즈·라벨·정렬이지 **소재 수가 아니다.**
#: 소재 수 규칙(`MIN_TOPIC_ADS`)은 맨 아래에서 기본값 그대로 따로 검증한다 —
#: 문턱을 여기저기 꺼 두면 정작 기본 동작을 아무도 안 지키게 된다.
def frame(rows: list[dict]) -> pd.DataFrame:
    """(month, cost) 중심의 최소 프레임. 안 준 컬럼은 빈 값으로 채운다."""
    base = {"ad": "", "extra_info": None, "creative_type": "", "mix_group": "일반",
            "cost": 0.0, "month": 8}
    return pd.DataFrame([{**base, **r} for r in rows])


def labels(found: list[dict]) -> list[str]:
    return [c["label"] for c in found]


def by_label(found: list[dict], label: str) -> dict:
    return next(c for c in found if c["label"] == label)


# --------------------------------------------------------------------- 신규 / 급증

def test_직전_기간_소진이_0이면_신규():
    df = frame([
        {"month": 8, "extra_info": "epn", "cost": 500_000, "ad": "a"},
    ])
    found = topics.candidates(df, 8, min_ads=1)
    assert by_label(found, "EPN")["kind"] == topics.KIND_NEW


def test_직전_기간에_집행이_있으면_신규가_아니다():
    df = frame([
        {"month": 7, "extra_info": "epn", "cost": 400_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 500_000, "ad": "a"},
    ])
    # 1.25배라 급증도 아니다 → 후보가 아니다
    assert labels(topics.candidates(df, 8, min_ads=1)) == []


def test_직전_달_대비_문턱_이상이면_급증():
    df = frame([
        {"month": 7, "extra_info": "mix", "cost": 1_000_000, "ad": "a"},
        {"month": 8, "extra_info": "mix", "cost": 1_500_000, "ad": "a"},
    ])
    found = topics.candidates(df, 8, min_ads=1)
    assert by_label(found, "MIX")["kind"] == topics.KIND_SURGE
    assert by_label(found, "MIX")["prev_cost"] == 1_000_000


def test_급증_문턱을_못_넘으면_제외된다():
    df = frame([
        {"month": 7, "extra_info": "mix", "cost": 1_000_000, "ad": "a"},
        {"month": 8, "extra_info": "mix", "cost": 1_400_000, "ad": "a"},
    ])
    assert labels(topics.candidates(df, 8, min_ads=1)) == []


def test_급증_문턱은_1_5배다():
    """8월 MIX가 1.97배였는데 2.0 문턱에서 빠졌다 — 규리님이 실제로 고른 주제다."""
    assert topics.SURGE_RATIO == 1.5


def test_lookback_밖의_집행은_신규_판정을_막지_않는다():
    df = frame([
        {"month": 2, "extra_info": "epn", "cost": 900_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 500_000, "ad": "a"},
    ])
    found = topics.candidates(df, 8, lookback=3, min_ads=1)
    assert by_label(found, "EPN")["kind"] == topics.KIND_NEW


# ------------------------------------------------------------------------- 제외 규칙

def test_소진이_문턱_미만이면_제외():
    df = frame([{"month": 8, "extra_info": "epn", "cost": 50_000, "ad": "a"}])
    assert topics.candidates(df, 8, min_ads=1) == []


@pytest.mark.parametrize("tag", ["1", "2", "8", "12th", "12anniversaryw2", "a", "ab"])
def test_버전_배리에이션_표기는_주제가_아니다(tag):
    df = frame([{"month": 8, "extra_info": tag, "cost": 5_000_000, "ad": "a"}])
    assert topics.candidates(df, 8, min_ads=1) == []


@pytest.mark.parametrize("tag", ["epn", "comic", "text", "vari", "men"])
def test_진짜_태그는_남는다(tag):
    df = frame([{"month": 8, "extra_info": tag, "cost": 5_000_000, "ad": "a"}])
    assert labels(topics.candidates(df, 8, min_ads=1)) == [tag.upper()]


def test_노이즈_규칙은_태그_축에만_적용된다():
    """유형은 통제된 어휘라 `AI` 같은 두 글자 이름이 정당하다."""
    df = frame([{"month": 8, "creative_type": "AI", "cost": 5_000_000, "ad": "a"}])
    assert labels(topics.candidates(df, 8, min_ads=1)) == ["AI"]


def test_센티널_값은_주제가_아니다():
    """`없음`은 태그가 안 붙은 소재 전부, `일반`은 MIX가 아닌 소재 전부다."""
    df = frame([
        {"month": 8, "extra_info": None, "cost": 90_000_000, "ad": "a",
         "mix_group": "일반"},
    ])
    assert topics.candidates(df, 8, min_ads=1) == []


# ----------------------------------------------------------------- 태그 펼치기 / 중복

def test_한_소재의_태그가_여러_개면_각각_집계된다():
    df = frame([{"month": 8, "extra_info": "text-thumb", "cost": 3_000_000, "ad": "a"}])
    found = topics.candidates(df, 8, min_ads=1)
    assert sorted(labels(found)) == ["TEXT", "THUMB"]
    # 펼침이라 둘 다 소재 전액을 갖는다 — 합계가 전체를 넘는다(구성비가 아니다)
    assert by_label(found, "TEXT")["cost"] == 3_000_000


def test_같은_이름이_여러_축에_걸리면_소진이_큰_축만_남는다():
    df = frame([
        {"month": 8, "extra_info": "mix", "cost": 600_000, "ad": "a",
         "creative_type": "MIX", "mix_group": "MIX"},
        {"month": 8, "extra_info": None, "cost": 10_000_000, "ad": "b",
         "creative_type": "Highlight", "mix_group": "MIX"},
    ])
    found = [c for c in topics.candidates(df, 8, min_ads=1) if c["label"] == "MIX"]
    assert len(found) == 1
    assert found[0]["field"] == "mix_group"
    assert found[0]["cost"] == 10_600_000


def test_소재_개수는_고유_소재명_기준():
    df = frame([
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "b"},
    ])
    assert by_label(topics.candidates(df, 8, min_ads=1), "EPN")["ads"] == 2


# ----------------------------------------------------------------------------- 정렬

def test_신규가_급증보다_먼저_그_안에서는_소진_내림차순():
    df = frame([
        {"month": 7, "extra_info": "text", "cost": 1_000_000, "ad": "t"},
        {"month": 8, "extra_info": "text", "cost": 9_000_000, "ad": "t"},
        {"month": 8, "extra_info": "epn", "cost": 500_000, "ad": "e"},
        {"month": 8, "extra_info": "comic", "cost": 800_000, "ad": "c"},
    ])
    assert labels(topics.candidates(df, 8, min_ads=1)) == ["COMIC", "EPN", "TEXT"]


def test_빈_프레임은_빈_목록():
    assert topics.candidates(pd.DataFrame(), 8) == []
    assert topics.candidates(None, 8) == []


def test_그_달_데이터가_없으면_빈_목록():
    df = frame([{"month": 7, "extra_info": "epn", "cost": 5_000_000, "ad": "a"}])
    assert topics.candidates(df, 8, min_ads=1) == []


# ------------------------------------------------------------------------- 표 프리셋

def test_프리셋은_표_두_개다():
    views = topics.preset_views("EPN", "extra_info_tag", "epn")
    assert len(views) == 2


def test_뷰_A는_매체별_집계_대조군_썸네일_켜짐():
    a, _ = topics.preset_views("EPN", "extra_info_tag", "epn")
    assert a["label"] == "매체별 EPN 소재 성과"
    assert [r["field"] for r in a["rows"]] == ["media", "os"]
    assert a["contrast"] is True
    assert a["contrast_field"] == "extra_info_tag"
    assert a["thumbs"] is True


def test_뷰_B는_소재단_대조군_꺼짐():
    _, b = topics.preset_views("EPN", "extra_info_tag", "epn")
    assert b["label"] == "EPN 소재단 성과"
    assert [r["field"] for r in b["rows"]] == ["ad", "media"]
    assert b["contrast"] is False
    assert b["thumbs"] is False


def test_두_뷰_모두_같은_필터를_쓴다():
    views = topics.preset_views("COMIC", "extra_info_tag", "comic")
    assert all(v["filters"] == {"extra_info_tag": ["comic"]} for v in views)


def test_필터는_뷰마다_독립된_객체다():
    """한 뷰의 필터를 고쳤을 때 다른 뷰가 따라 바뀌면 안 된다(얕은 복사 사고 재발 방지)."""
    a, b = topics.preset_views("COMIC", "extra_info_tag", "comic")
    a["filters"]["extra_info_tag"].append("hashtag")
    assert b["filters"] == {"extra_info_tag": ["comic"]}
    a["values"].append("click")
    assert "click" not in b["values"]


def test_뷰마다_id가_있고_서로_다르다():
    """id가 없으면 view_with_defaults가 리런마다 새로 발급해 위젯 상태가 앵커를 잃는다."""
    a, b = topics.preset_views("EPN", "extra_info_tag", "epn")
    assert a["id"] and b["id"]
    assert a["id"] != b["id"]


def test_기본_지표를_그대로_쓴다():
    from creative_data import DEFAULT_PIVOT_VALUES

    for view in topics.preset_views("EPN", "extra_info_tag", "epn"):
        assert view["values"] == list(DEFAULT_PIVOT_VALUES)


def test_프리셋_행은_전부_집계_가능한_차원이다():
    from creative_data import PIVOT_ROW_FIELDS

    for view in topics.preset_views("EPN", "extra_info_tag", "epn"):
        for row in view["rows"]:
            assert row["field"] in PIVOT_ROW_FIELDS


def test_블록_제목():
    assert topics.preset_title("EPN") == "EPN 소재 성과 분석"


def test_한글_라벨은_대문자로_바꾸지_않는다():
    df = frame([{"month": 8, "creative_type": "회차모음집", "cost": 5_000_000,
                 "ad": "a"}])
    assert labels(topics.candidates(df, 8, min_ads=1)) == ["회차모음집"]


# ------------------------------------------------- 블록 생성 (한 번의 커밋으로 표까지)

def test_주제_블록은_한_번의_커밋으로_표까지_채워진다(tmp_path, monkeypatch):
    """`add_topic_block`이 쓰는 경로 — 표가 없는 빈 블록이 저장되는 순간이 없어야 한다.

    `add_block`은 새 id를 돌려주지만 `mutate`는 그 반환값을 버린다. 그래서 바깥에서 id를
    받아 두 번 저장하는 대신, 같은 `fn` 안에서 만들고 그 자리에서 views를 채운다.
    """
    import blocks
    import google_sheets_writer

    monkeypatch.setattr(blocks, "BLOCKS_DIR", tmp_path / "notes")
    monkeypatch.setattr(google_sheets_writer, "configured", lambda: False)

    created = {}

    def _fn(data):
        block_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query",
                                    topics.preset_title("EPN"))
        created["id"] = block_id
        blocks.update_block(data, blocks.SLOT_ANALYSIS, block_id,
                            views=topics.preset_views("EPN", "extra_info_tag", "epn"))

    ok, reason = blocks.mutate(8, _fn)
    assert ok, reason

    stored = blocks.load_blocks(8)[blocks.SLOT_ANALYSIS]
    assert len(stored) == 1
    block = stored[0]
    assert block["id"] == created["id"]
    assert block["title"] == "EPN 소재 성과 분석"
    assert [v["label"] for v in block["views"]] == [
        "매체별 EPN 소재 성과", "EPN 소재단 성과",
    ]
    assert block["comment"] == ""      # 코멘트는 사람이 쓴다
    assert block["insight"] == ""


def test_update_block이_views를_버리지_않는다(tmp_path, monkeypatch):
    """`update_block`은 BLOCK_DEFAULTS에 없는 키를 조용히 버린다 — views는 통과해야 한다."""
    import blocks
    import google_sheets_writer

    monkeypatch.setattr(blocks, "BLOCKS_DIR", tmp_path / "notes")
    monkeypatch.setattr(google_sheets_writer, "configured", lambda: False)

    data = blocks.empty_blocks()
    block_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "t")
    blocks.update_block(data, blocks.SLOT_ANALYSIS, block_id,
                        views=topics.preset_views("MIX", "mix_group", "MIX"))
    block = blocks.find_block(data, blocks.SLOT_ANALYSIS, block_id)
    assert len(block["views"]) == 2


# --------------------------------------------------------------- 최소 소재 수

def test_소재가_하나뿐이면_후보가_아니다():
    """규리님 요청(2026-09-16): *"소재가 한 개밖에 없는 애들은 신규 소재군으로 넣지 마.
    2개 이상부터만 추가해."*

    8월 후보 목록에 `RETURN2`·`SOCIAL1`·`RETURN5`·`THUMBNAILMOVING`·`恐怖usp`가 전부
    소재 1개로 떠서 목록의 절반을 차지했다. 소재 하나는 소재군이 아니다 — 표를 세워도
    한 줄이라 "이 유형이 어떤가"를 말할 수 없다.
    """
    df = frame([{"month": 8, "extra_info": "return2", "cost": 2_818_422, "ad": "a"}])
    assert topics.candidates(df, 8) == []


def test_소재가_둘이면_후보다():
    df = frame([
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "b"},
    ])
    assert labels(topics.candidates(df, 8)) == ["EPN"]


def test_소진이_커도_소재_하나면_뺀다():
    """⚠ 소진 문턱만으로는 안 걸러진다 — 소재 하나에 ₩2.8M을 쓴 `RETURN2`가 실제로
    후보 1위로 올라왔다. 규모와 개수는 다른 조건이다."""
    df = frame([
        {"month": 8, "extra_info": "return2", "cost": 9_000_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 200_000, "ad": "x"},
        {"month": 8, "extra_info": "epn", "cost": 200_000, "ad": "y"},
    ])
    assert labels(topics.candidates(df, 8)) == ["EPN"]


def test_급증에도_같은_문턱이_걸린다():
    """신규만 걸러도 `[급증]`으로 소재 하나짜리가 다시 올라온다."""
    df = frame([
        {"month": 7, "extra_info": "teaser", "cost": 1_000_000, "ad": "a"},
        {"month": 8, "extra_info": "teaser", "cost": 3_000_000, "ad": "a"},
    ])
    assert topics.candidates(df, 8) == []


def test_같은_소재가_여러_행이어도_하나로_센다():
    """일별 행이 여러 개인 것과 소재가 여러 개인 것은 다르다."""
    df = frame([
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "a"},
        {"month": 8, "extra_info": "epn", "cost": 300_000, "ad": "a"},
    ])
    assert topics.candidates(df, 8) == []


def test_문턱은_2다():
    assert topics.MIN_TOPIC_ADS == 2
