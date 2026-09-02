# -*- coding: utf-8 -*-
"""MIX 소재 묶기 — 소재명 규칙이 안 지켜진 소재군을 세 조건의 합집합으로 잡는다.

규리님이 정한 규칙: `Creative Type = Mix` / `Extra Info = mix` / `Title ID = 0000`
중 **하나라도** 맞으면 MIX. 이 판정이 틀리면 MIX 성과가 통째로 다른 숫자가 되고,
그게 광고주 리포트에 그대로 실린다.
"""
import pandas as pd

from creative_data import MIX_LABEL, NON_MIX_LABEL, mix_group


def frame(rows: list[dict]) -> pd.DataFrame:
    columns = ["creative_type", "extra_info", "title_code"]
    return pd.DataFrame([{c: r.get(c) for c in columns} for r in rows])


def test_creative_type이_MIX면_잡는다():
    got = mix_group(frame([{"creative_type": "MIX", "title_code": "1234"}]))
    assert list(got) == [MIX_LABEL]


def test_대소문자를_가리지_않는다():
    got = mix_group(frame([{"creative_type": "Mix"}, {"creative_type": "mix"}]))
    assert list(got) == [MIX_LABEL, MIX_LABEL]


def test_MixTitle도_포함한다():
    """2026-09-03 규리님 확인. 실물이 하나뿐이고(`2401_極權教師_..._MixTitle_9X16_1`),
    Title ID가 `0000`이 아니라 `2401`이라 세 조건 중 어디에도 안 걸린다 —
    그래서 Creative Type으로 명시적으로 넣어야 한다."""
    got = mix_group(frame([
        {"creative_type": "MixTitle", "title_code": "2401"},
        {"creative_type": "MIXTITLE", "title_code": "2401"},
    ]))
    assert list(got) == [MIX_LABEL, MIX_LABEL]


def test_extra_info_태그가_mix면_잡는다():
    got = mix_group(frame([
        {"extra_info": "Mix_12anniversaryW2_New", "title_code": "1234"},
        {"extra_info": "event1_Mix_12anniversaryW2_New", "title_code": "1234"},
        {"extra_info": "TITLE2-mix", "title_code": "1234"},
    ]))
    assert list(got) == [MIX_LABEL] * 3


def test_태그는_토큰_일치다():
    """부분 문자열로 보면 `remix`·`mixtitle` 같은 값이 딸려 들어온다."""
    got = mix_group(frame([
        {"extra_info": "remix", "title_code": "1234"},
        {"extra_info": "mixed", "title_code": "1234"},
    ]))
    assert list(got) == [NON_MIX_LABEL, NON_MIX_LABEL]


def test_title_code가_0000이면_잡는다():
    """여러 작품을 섞은 소재라 작품 코드가 비어 있다."""
    got = mix_group(frame([{"creative_type": "Highlight", "title_code": "0000"}]))
    assert list(got) == [MIX_LABEL]


def test_셋_다_아니면_일반이다():
    got = mix_group(frame([
        {"creative_type": "Highlight", "extra_info": "6s-text", "title_code": "5144"},
    ]))
    assert list(got) == [NON_MIX_LABEL]


def test_값이_비어도_죽지_않는다():
    got = mix_group(frame([{}, {"creative_type": None, "extra_info": None,
                                "title_code": None}]))
    assert list(got) == [NON_MIX_LABEL, NON_MIX_LABEL]


def test_컬럼이_없어도_죽지_않는다():
    """구글 등 일부 경로는 파싱 컬럼이 없다 — 예외 대신 전부 `일반`이어야 한다."""
    got = mix_group(pd.DataFrame([{"ad": "x"}]))
    assert list(got) == [NON_MIX_LABEL]


def test_빈_프레임():
    assert mix_group(pd.DataFrame()).empty


def test_피벗_차원에_들어_있다():
    """행·필터에서 고를 수 있어야 규리님이 MIX만 따로 볼 수 있다."""
    from creative_data import DIMENSION_COLUMNS

    assert "mix_group" in DIMENSION_COLUMNS
