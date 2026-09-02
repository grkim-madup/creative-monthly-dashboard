# -*- coding: utf-8 -*-
"""대조군을 가르는 규칙.

이 계약이 깨지면 광고주에게 가는 "그 외 소재 평균"이 틀린다 — 값이 비어 있거나
예외가 나는 게 아니라 **그럴듯한 다른 숫자**가 나오므로 눈으로는 못 잡는다.
"""
import pandas as pd
import pytest

from creative_data import CREATIVE_FIELDS, SCOPE_FIELDS, contrast_split


@pytest.fixture()
def scope() -> pd.DataFrame:
    # 같은 소재(A)가 두 매체에 있다 — 이름으로만 제외하면 매체 필터가 틀어지는 사례.
    return pd.DataFrame([
        {"ad": "A", "media": "TikTok", "os": "AOS", "format": "VID",
         "extra_info": "epn", "cost": 100.0},
        {"ad": "A", "media": "Meta", "os": "AOS", "format": "VID",
         "extra_info": "epn", "cost": 200.0},
        {"ad": "B", "media": "TikTok", "os": "AOS", "format": "VID",
         "extra_info": "text", "cost": 300.0},
        {"ad": "C", "media": "Meta", "os": "iOS", "format": "IMG",
         "extra_info": None, "cost": 400.0},
    ])


def test_소재_속성_필터는_뒤집힌다(scope):
    subject, rest = contrast_split(scope, {"format": ["VID"]}, [])
    assert set(subject["ad"]) == {"A", "B"}
    assert set(rest["ad"]) == {"C"}


def test_집행_조건_필터는_대조군에도_유지된다(scope):
    """매체를 좁혔으면 대조군도 그 매체 안이어야 한다."""
    subject, rest = contrast_split(scope, {"media": ["TikTok"], "format": ["VID"]}, [])
    assert set(subject["ad"]) == {"A", "B"}
    # C는 Meta라서 대조군에도 들어오지 않는다. 그래서 대조군이 빈다.
    assert rest.empty
    assert set(rest.get("media", pd.Series(dtype=object))) == set()


def test_대상과_대조군은_비교_범위를_정확히_채운다(scope):
    subject, rest = contrast_split(scope, {"media": ["Meta"], "format": ["VID"]}, [])
    base = scope[scope["media"] == "Meta"]
    assert len(subject) + len(rest) == len(base)
    assert subject["cost"].sum() + rest["cost"].sum() == base["cost"].sum()
    assert not set(subject["ad"]) & set(rest["ad"])


def test_태그_필터는_소재_이름으로_제외한다(scope):
    """`epn-6s` 소재가 `6s` 줄로 대조군에 되살아나면 양쪽에 동시에 들어간다."""
    subject, rest = contrast_split(scope, {"extra_info_tag": ["epn"]}, [])
    assert set(subject["ad"]) == {"A"}
    assert "A" not in set(rest["ad"])


def test_집행_조건만_좁히면_대조군이_없다(scope):
    """"그 외 소재"라고 부를 것이 없다. 빈 프레임으로 알린다 — 화면이 안내를 띄운다."""
    subject, rest = contrast_split(scope, {"media": ["TikTok"]}, [])
    assert not subject.empty
    assert rest.empty


def test_필터가_없으면_대조군이_없다(scope):
    subject, rest = contrast_split(scope, {}, [])
    assert len(subject) == len(scope)
    assert rest.empty


def test_손으로_더한_소재는_필터가_있을_때만_대상에_합쳐진다(scope):
    """필터 없이 소재만 고르면 대상이 이미 전체다 — 그때는 대조군을 만들지 않는다."""
    _subject, rest = contrast_split(scope, {}, ["A"])
    assert rest.empty

    subject, rest = contrast_split(scope, {"extra_info_tag": ["text"]}, ["A"])
    assert set(subject["ad"]) == {"A", "B"}
    assert set(rest["ad"]) == {"C"}


def test_두_필드_집합은_겹치지_않는다():
    """한 필드가 양쪽에 있으면 유지도 하고 뒤집기도 해서 결과가 정의되지 않는다."""
    assert not CREATIVE_FIELDS & SCOPE_FIELDS


def test_모든_차원이_두_집합_중_한_곳에_들어간다():
    """새 차원을 추가하면서 이 분류를 빠뜨리면 그 필터로는 **대조군이 안 만들어진다.**

    실제로 `mix_group`을 추가하고 여기 넣지 않아 "대조군을 만들 수 없습니다"가 떴다
    (규리님이 화면에서 잡았다). 예외도 에러도 나지 않는 유형이라 테스트로 막는다.
    """
    from creative_data import DIMENSION_COLUMNS

    unclassified = set(DIMENSION_COLUMNS) - CREATIVE_FIELDS - SCOPE_FIELDS
    assert not unclassified, f"두 집합 어디에도 없는 차원: {sorted(unclassified)}"


def test_MIX_필터로_대조군이_만들어진다():
    """`mix_group`은 소재를 고르는 차원이므로 뒤집혀야 한다."""
    scope = pd.DataFrame([
        {"ad": "A", "media": "Meta", "mix_group": "MIX", "cost": 100.0},
        {"ad": "B", "media": "Meta", "mix_group": "일반", "cost": 200.0},
    ])
    subject, rest = contrast_split(scope, {"mix_group": ["MIX"]}, [])
    assert set(subject["ad"]) == {"A"}
    assert set(rest["ad"]) == {"B"}
