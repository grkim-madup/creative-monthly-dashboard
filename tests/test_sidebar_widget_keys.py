# -*- coding: utf-8 -*-
"""사이드바 위젯에 `key`가 있는지.

`key` 없는 위젯은 Streamlit이 **위젯 트리의 위치**로 식별한다. 그래서 위나 아래
요소의 구조가 리런마다 바뀌면 식별자가 흔들리고, 값이 `value=`(기본값)로 되돌아간다.

실제로 그랬다: 구글 마크업 배율 아래 고정 블록의 컨테이너 키가 상태에 따라
바뀐다(`google_freeze_loading` → `google_freeze_done`/`pending`/`nodata`).
규리님이 1.08로 맞춰도 다음 리런에서 1.0830으로 되돌아갔다.

진입점은 어떤 테스트도 import하지 않으니(화면을 그린다) 소스로 확인한다.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRY = next(ROOT / name for name in ("creative_dashboard.py", "app.py")
             if (ROOT / name).exists())
SOURCE = ENTRY.read_text(encoding="utf-8")

#: 값을 계속 들고 있어야 하는 사이드바 위젯. 라벨로 찾는다.
STATEFUL_SIDEBAR_WIDGETS = [
    "구글시트 링크",
    "리포트 월",
    "구글 비용 마크업 배율",
]


@pytest.mark.parametrize("label", STATEFUL_SIDEBAR_WIDGETS)
def test_widget_has_an_explicit_key(label: str):
    index = SOURCE.find(f'"{label}"')
    assert index >= 0, f"{label} 위젯을 찾지 못했습니다"
    # 위젯 호출 한 덩어리 안에 key가 있어야 한다.
    chunk = SOURCE[index:index + 500]
    end = chunk.find("\n    )")
    call = chunk[:end if end > 0 else 400]
    assert "key=" in call, f"{label} 위젯에 key가 없습니다 — 값이 기본값으로 되돌아갑니다"


def test_markup_default_is_documented():
    """기본값을 바꿀 때 실측 근거를 잃지 않게 한다."""
    assert "1.0830" in SOURCE
