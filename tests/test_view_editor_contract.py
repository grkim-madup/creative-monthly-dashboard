"""편집기의 **위젯 → 저장** 계약.

이 계약을 검증하는 테스트가 그동안 **하나도 없었다** — `view_from_widgets`가 진입점
안에 있어서 import할 수 없었기 때문이다(`view_state.py`로 빼낸 이유). 편집기는 이
프로젝트에서 "위젯 상태와 저장 상태가 엇갈리는" 버그가 가장 많이 났던 곳이라,
레이아웃을 바꾸기 전에 여기를 먼저 못 박는다.
"""

from __future__ import annotations

import pytest

from view_state import (
    VIEW_DEFAULTS,
    view_from_widgets,
    view_with_defaults,
)

KEY = "blk123_vw456"


def saved(**over) -> dict:
    """저장돼 있는 뷰 하나. 8월 `매체별 EPN 소재 성과`의 실제 모양이다."""
    base = {
        "id": "vw456",
        "label": "매체별 EPN 소재 성과",
        "kind": "pivot",
        "rows": [{"field": "media"}],
        "values": ["cost", "impression", "CPI"],
        "filters": {"extra_info_tag": ["epn"], "creative_type": ["Highlight"]},
        "include_ads": [],
        "contrast": True,
        "contrast_field": "extra_info_tag",
        "thumbs": True,
    }
    return {**base, **over}


# ------------------------------------- 세션 키가 없으면 저장값을 그대로 유지한다

def test_세션이_비면_저장값이_그대로_나온다():
    """화면을 안 그린 상태(저장 버튼만 누른 리런)에서도 값이 보존돼야 한다."""
    out = view_from_widgets(saved(), KEY, {})
    assert out["label"] == "매체별 EPN 소재 성과"
    assert [r["field"] for r in out["rows"]] == ["media"]
    assert out["values"] == ["cost", "impression", "CPI"]
    assert out["filters"] == {"extra_info_tag": ["epn"],
                              "creative_type": ["Highlight"]}
    assert out["contrast"] is True and out["thumbs"] is True


@pytest.mark.parametrize("field, value", [
    ("chart_kind", "ranking"), ("metric", "CTR"), ("top_n", 20),
])
def test_그래프_필드는_위젯이_없어도_안_잃는다(field, value):
    """그래프 UI를 걷어냈다 — 위젯이 없으니 저장값이 그대로 실려 나가야 한다.

    이게 성립하지 않으면 `그래프 삭제`는 데이터를 버리는 변경이 된다.
    """
    out = view_from_widgets(saved(**{field: value}), KEY, {})
    assert out[field] == value


def test_읽지_않는_필드도_버리지_않는다():
    """`metrics`는 편집 위젯이 없다 — 그래도 저장된 값이 살아 있어야 한다."""
    out = view_from_widgets(saved(metrics=["cost", "CPI"]), KEY, {})
    assert out["metrics"] == ["cost", "CPI"]


# --------------------------------------------------- 위젯 값이 저장값을 이긴다

def test_위젯_값이_저장값을_덮는다():
    session = {
        f"vlabel_{KEY}": "고친 이름",
        f"pvrows_{KEY}": ["media", "os"],
        f"pvvals_{KEY}": ["cost", "CTR"],
        f"pvct_{KEY}": False,
        f"pvth_{KEY}": False,
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["label"] == "고친 이름"
    assert [r["field"] for r in out["rows"]] == ["media", "os"]
    assert out["values"] == ["cost", "CTR"]
    assert out["contrast"] is False and out["thumbs"] is False


def test_행을_비우면_빈_채로_저장된다():
    """행을 비우는 것은 정당한 선택이다 — 렌더가 기본값으로 되살린다."""
    out = view_from_widgets(saved(), KEY, {f"pvrows_{KEY}": []})
    assert out["rows"] == []


def test_같은_구분을_행에_두_번_넣으면_하나로_모인다():
    out = view_from_widgets(saved(), KEY, {f"pvrows_{KEY}": ["media", "media"]})
    assert [r["field"] for r in out["rows"]] == ["media"]


# ----------------------------------------------------------------- 필터 계약

def test_값이_빈_구분은_필터에서_빠진다():
    """화면에서 빈 멀티셀렉트로 보이는 구분은 아무것도 걸지 않는다.

    이게 어긋나면 「칩은 있는데 표에 다 나온다」는 그 사고가 다시 난다.
    """
    session = {
        f"pvfilters_{KEY}": ["extra_info_tag", "creative_type"],
        f"pvfval_{KEY}_extra_info_tag": ["epn"],
        f"pvfval_{KEY}_creative_type": [],
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["filters"] == {"extra_info_tag": ["epn"]}


def test_구분을_빼면_그_값_키가_남아_있어도_안_들어간다():
    """구분 멀티셀렉트가 무엇이 걸렸는지를 정한다 — 값 키는 세션에 남아 있을 수 있다."""
    session = {
        f"pvfilters_{KEY}": ["extra_info_tag"],
        f"pvfval_{KEY}_extra_info_tag": ["epn"],
        f"pvfval_{KEY}_creative_type": ["Highlight"],   # 뺀 구분의 잔재
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["filters"] == {"extra_info_tag": ["epn"]}


def test_구분만_고르고_값을_안_고르면_필터가_빈다():
    session = {
        f"pvfilters_{KEY}": ["size"],
        f"pvfval_{KEY}_size": [],
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["filters"] == {}


def test_구분을_새로_넣으면_저장값이_아니라_위젯_값을_쓴다():
    session = {
        f"pvfilters_{KEY}": ["extra_info_tag", "os"],
        f"pvfval_{KEY}_extra_info_tag": ["comic", "hashtag"],
        f"pvfval_{KEY}_os": ["AOS"],
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["filters"] == {"extra_info_tag": ["comic", "hashtag"],
                             "os": ["AOS"]}


# --------------------------------------------------- 기간 비교 (같은 자리를 쓴다)

def test_기간_비교로_바꿔도_값과_필터가_살아남는다():
    """지금 정본은 기간 비교를 고르면 `pivot_editor`가 사라져 필터를 고칠 수 없었다.

    행 자리에 기간이 들어가고 값·필터는 그대로 남는 것이 이 재설계의 핵심이다.
    """
    session = {
        f"vkind_{KEY}": "compare",
        f"vperiod_label_{KEY}_0": "방영 전 (4월 누적)",
        f"vperiod_months_{KEY}_0": [3, 4],
        f"vperiod_label_{KEY}_1": "방영 후 (6월 누적)",
        f"vperiod_months_{KEY}_1": [5, 6],
        f"pvfilters_{KEY}": ["extra_info_tag"],
        f"pvfval_{KEY}_extra_info_tag": ["epn"],
        f"pvvals_{KEY}": ["cost", "CPI"],
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["kind"] == "compare"
    assert out["filters"] == {"extra_info_tag": ["epn"]}
    assert out["values"] == ["cost", "CPI"]
    assert [p["label"] for p in out["periods"]] == ["방영 전 (4월 누적)",
                                                     "방영 후 (6월 누적)"]
    assert [p["months"] for p in out["periods"]] == [[3, 4], [5, 6]]


def test_기간_위젯이_없으면_저장된_기간이_남는다():
    stored = [{"label": "전", "months": [3]}, {"label": "후", "months": [6]}]
    out = view_from_widgets(saved(kind="compare", periods=stored), KEY, {})
    assert out["periods"] == stored


def test_기간_월은_정수로_저장된다():
    """문자열로 들어오면 `compare_periods`의 월 비교가 조용히 빗나간다."""
    session = {
        f"vperiod_label_{KEY}_0": "A", f"vperiod_months_{KEY}_0": ["3", "4"],
        f"vperiod_label_{KEY}_1": "B", f"vperiod_months_{KEY}_1": ["5"],
    }
    out = view_from_widgets(saved(), KEY, session)
    assert out["periods"][0]["months"] == [3, 4]
    assert all(isinstance(m, int) for p in out["periods"] for m in p["months"])


# ----------------------------------------------------------- id / 기본값 계약

def test_저장된_id를_바꾸지_않는다():
    """id가 흔들리면 `view_key`가 바뀌어 위젯 상태·셀 강조가 앵커를 잃는다."""
    out = view_from_widgets(saved(), KEY, {})
    assert out["id"] == "vw456"


def test_id가_없으면_발급한다():
    out = view_with_defaults({"label": "새 표"})
    assert out["id"] and len(out["id"]) == 6


def test_기본값에_필수_필드가_다_있다():
    for field in ("label", "kind", "rows", "values", "filters", "contrast",
                  "contrast_field", "thumbs", "include_ads", "periods"):
        assert field in VIEW_DEFAULTS


def test_기본값을_고쳐도_다른_뷰가_오염되지_않는다():
    """`a76aaa2` — 얕은 복사로 모든 블록이 같은 dict를 공유했던 사고."""
    a = view_with_defaults({})
    b = view_with_defaults({})
    a["filters"]["os"] = ["AOS"]
    a["values"].append("cost")
    assert b["filters"] == {}
    assert b["values"] == []
    assert VIEW_DEFAULTS["filters"] == {}
