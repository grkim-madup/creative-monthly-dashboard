# -*- coding: utf-8 -*-
"""기본 리포트 월 = **마감된 마지막 월**.

규리님(2026-09-08): *"8월 데이터가 기본으로 보여야 해. 오늘이 9/8이지만 이번
먼슬리는 8월 데이터 보고야(8월 먼슬리는 8월이 마감된 후에 진행)."*

예전에는 "데이터가 있는 가장 최근 월"을 열어서, 시트에 9월 집행분이 하루라도 들어오면
**아직 절반도 안 지난 9월의 반쪽 숫자**가 광고주 첫 화면이 됐다.
"""
import datetime as dt

import pytest

from creative_data import default_month


def d(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, day)


def test_9월_8일에는_8월을_연다():
    """이 테스트가 이 함수의 존재 이유다."""
    assert default_month([2, 3, 4, 5, 6, 7, 8, 9], d(2026, 9, 8)) == 8


def test_다음달_데이터가_없어도_같다():
    assert default_month([2, 3, 4, 5, 6, 7, 8], d(2026, 9, 8)) == 8


def test_월말에도_그_달로_넘어가지_않는다():
    """9/30에도 9월은 아직 마감이 아니다 — 마감 후 작업이라는 게 규칙이다."""
    assert default_month([7, 8, 9], d(2026, 9, 30)) == 8


def test_달이_바뀌면_따라간다():
    assert default_month([7, 8, 9], d(2026, 10, 1)) == 9


def test_마감된_달이_여러_개면_가장_최근():
    assert default_month([2, 5, 8], d(2026, 9, 8)) == 8


def test_마감된_달이_없으면_최근_월로_떨어진다():
    """1월처럼 이전 달이 목록에 없는 경우 — 빈 화면보다 낫다."""
    assert default_month([1], d(2026, 1, 15)) == 1
    assert default_month([9], d(2026, 9, 8)) == 9


def test_목록이_비면_None():
    assert default_month([], d(2026, 9, 8)) is None


def test_순서가_뒤섞여_있어도_된다():
    assert default_month([9, 3, 8, 5], d(2026, 9, 8)) == 8


def test_진입점이_KST로_판단한다():
    """컨테이너가 UTC라 그냥 `date.today()`를 쓰면 자정 전후로 달이 하루 어긋난다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("creative_dashboard.py", "app.py"):
        path = root / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "default_month(months, _today_kst)" in source, name
        assert "hours=9" in source, name
