# -*- coding: utf-8 -*-
"""CSS가 `<style>` 안에 들어 있는지.

`</style>` 뒤에 규칙을 붙이면 브라우저가 그걸 **본문 텍스트로 그린다** — 실제로
대조군·썸네일 규칙이 그렇게 들어가 화면 맨 위에 CSS 소스가 통째로 노출됐다.
예외도 에러도 나지 않아서 화면을 열어 볼 때까지 아무도 모른다.
"""
import re

import ui


def test_style_태그가_한_쌍이다():
    assert ui.CSS.count("<style>") == 1
    assert ui.CSS.count("</style>") == 1


def test_닫는_태그_뒤에_규칙이_없다():
    tail = ui.CSS.split("</style>", 1)[1]
    assert "{" not in tail and "/*" not in tail, f"</style> 뒤에 CSS가 남았다: {tail[:120]!r}"
    assert tail.strip() == ""


def test_여는_태그_앞에도_규칙이_없다():
    head = ui.CSS.split("<style>", 1)[0]
    assert "{" not in head and "/*" not in head


def test_중괄호가_짝을_이룬다():
    body = ui.CSS.split("<style>", 1)[1].split("</style>", 1)[0]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    assert body.count("{") == body.count("}")
