# -*- coding: utf-8 -*-
"""편집기 `표시` 줄의 정렬 규칙 (시안 A — 규리님 2026-09-30).

규리님: *"표시 토글 위치가 너무 중구난방이야. 디자인 통일시켜."*

원인이 셋이었고 전부 이 파일이 막는다:

1. **못 쓰는 토글이 자리를 차지했다.** `구글 포함`은 작품 축일 때만, `묶어 보기`는
   행이 2개 이상일 때만 그려지는데 칸은 늘 예약돼 있었다 — 화면에 빈 구멍이 남았다.
2. **칸 폭이 제각각이었다**(1.7 / 1.2 / 1.5 / 1.5). 글자 수와 무관하게 간격이 들쭉.
3. **`?`(help)가 반만 붙어 있었다.** 대조군·썸네일엔 없고 나중에 추가한 둘엔 있었다.

진입점은 import할 수 없어(그리기 시작한다) 소스를 AST로 읽는다.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: 진입점 이름은 배포처마다 다르다 — madup.app 포털은 `app.py`로 복사한다.
ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def source() -> str:
    for name in ENTRYPOINTS:
        path = ROOT / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    pytest.skip("진입점을 찾지 못했다")


def toggle_calls(tree: ast.Module) -> list[ast.Call]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "toggle"]


def test_토글에_물음표를_붙이지_않는다():
    """이름 옆 `?`는 짧은 줄에서 노이즈다(규리님 지적).

    예전에 대조군·썸네일에서 뺐는데 나중에 추가한 `구글 포함`·`묶어 보기`에
    다시 넣어 **반만 붙어 있었다.** 설명은 표 아래 편집자 안내 줄이 맡는다.
    """
    tree = ast.parse(source())
    calls = toggle_calls(tree)
    assert calls, "토글을 하나도 못 찾았다 — 검사가 낡았다"
    with_help = [c for c in calls
                 if any(k.arg == "help" for k in c.keywords)]
    labels = [c.args[0].value if c.args and isinstance(c.args[0], ast.Constant)
              else "?" for c in with_help]
    assert not with_help, f"`?`가 붙은 토글: {labels}"


def test_칸_폭이_균일하다():
    """글자 수가 달라도 간격은 같아야 한 줄로 읽힌다."""
    text = source()
    assert "TOGGLE_W = " in text, "토글 칸 폭을 상수 하나로 두세요"
    assert ("[TOGGLE_W] * (3 + int(can_title) + int(can_gcre) + int(can_group))"
            in text), (
        "토글 칸은 **쓸 수 있는 개수만큼** 같은 폭으로 만들어야 합니다 "
        "(항상 있는 셋: 대조군 비교 · 썸네일 · 기간 예외)"
    )


def test_기간_예외도_같은_줄_토글이다():
    """⚠ 처음에 이 줄 **아래 별도 체크박스**로 붙였다가 토글들과 정렬이 어긋났다
    (규리님 지적 2026-10-01: *"토글들 위치가 제멋대로야"*).

    같은 `st.columns` 슬롯을 쓰고, 다른 토글과 같은 폭이어야 한 줄로 읽힌다.
    """
    text = source()
    assert "c_thru = slots.pop(0)" in text, "기간 예외가 토글 줄 슬롯을 안 쓴다"
    assert "c_thru.toggle(" in text, "체크박스가 아니라 토글이어야 줄이 맞는다"
    # 체크박스로 되돌리면 위 두 단정이 깨진다 — 무의미한 `or True` 단정을 두지 않는다.


def test_못_쓰는_토글은_칸을_안_만든다():
    """자리를 예약하면 빈 구멍이 남는다 — 규리님 스샷의 그 공백이다.

    구글 편집기와 같은 판단: *성립하지 않는 위젯은 아예 그리지 않는다.*
    """
    text = source()
    assert 'c_tl = slots.pop(0) if can_title else None' in text
    assert 'c_gc = slots.pop(0) if can_gcre else None' in text
    assert 'c_gr = slots.pop(0) if can_group else None' in text


def test_구글_토글_둘을_동시에_못_켠다():
    """⚠ `구글 포함`(캠페인 단위)과 `구글 소재`(애셋 단위)를 함께 켜면 구글이 두 번
    들어와 **이중 집계**가 된다. 화면에서 둘 중 하나만 그린다."""
    text = source()
    assert "can_gcre = (not can_title)" in text, (
        "구글 토글 둘이 동시에 뜨면 이중 집계가 된다")


def test_뒤집을_기준은_토글보다_뒤에_온다():
    """예전에는 `대조군 비교` 바로 옆에 끼어들어, 토글 하나를 켜면 나머지
    토글의 x좌표가 전부 밀렸다. 지금은 줄 맨 오른쪽이다."""
    text = source()
    order = [text.index(k) for k in (
        "c_th = slots.pop(0)",           # 썸네일
        "c_tl = slots.pop(0)",           # 구글 포함
        "c_gr = slots.pop(0)",           # 묶어 보기
        "c_lb = slots.pop(0)",           # 뒤집을 기준
    )]
    assert order == sorted(order), "뒤집을 기준이 토글보다 앞에 있습니다"


def test_묶어_보기_부작용을_표_아래에서_알린다():
    """`?`를 뺐으므로 그 정보가 어디에도 없으면 안 된다."""
    assert "묶어 보기를 켠 표에서는 셀을 눌러 강조할 수 없습니다" in source()


# ------------------------------------------------- 토글 CSS (2026-09-30 스샷)

def ui_css() -> str:
    return (ROOT / "ui.py").read_text(encoding="utf-8")


def test_토글_정렬은_위젯_키를_나열하지_않는다():
    """예전에는 `pvct_`·`pvth_` 두 키만 뒤집어 놨다.

    그래서 나중에 추가한 `구글 포함`(`pvtl_`)·`묶어 보기`(`pvgrp_`)가 빠져,
    **같은 줄에서 어떤 토글은 이름이 왼쪽 어떤 토글은 오른쪽**에 붙었다.
    편집기 컨테이너로 한정하면 토글을 더 넣어도 저절로 따라온다.
    """
    css = ui_css()
    assert '[class*="st-key-pv_"] [data-testid="stCheckbox"] label' in css
    assert "row-reverse" in css
    for key in ("pvct_", "pvth_", "pvtl_", "pvgrp_"):
        assert f'[class*="st-key-{key}"] [data-testid="stCheckbox"]' not in css, (
            f"`{key}` 를 따로 적어 두면 다음 토글이 또 빠집니다"
        )


def test_토글_이름이_리포트_라벨과_같은_크기다():
    """Streamlit 기본은 14px/400이라 옆의 `표시` 라벨(12px/600)보다 크고 흐려서
    혼자 떠 보였다(규리님: *"토글명 폰트가 너무 구려"*). 실측해서 맞춘 값이다."""
    css = ui_css()
    block = css[css.index('[class*="st-key-pv_"] [data-testid="stCheckbox"] label\n'
                          '[data-testid="stMarkdownContainer"] p'):][:320]
    assert "font-size: 12px" in block
    assert "font-weight: 600" in block
    assert "font-family" not in block, (
        "글꼴은 건드리지 않습니다 — 주변 글자와 같은 것을 써야 톤이 맞습니다"
    )
