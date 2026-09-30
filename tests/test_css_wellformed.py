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


def test_스트림릿_컨테이너에_본문_글꼴을_되돌려_준다():
    """Streamlit이 자기 컨테이너에 `Source Sans` 를 직접 걸어 `body` 선언을 덮는다.

    실측 2026-09-30: 화면 글자 **1,332개**가 Source Sans였다. 그 글꼴에는 한글이
    없어 시스템 대체 글꼴로 떨어지고, `소진액`과 `₩8,239,106`이 서로 다른 글꼴로
    그려져 두께·높이가 어긋났다. 광고주가 보는 본문 대부분이 그랬다.
    """
    import pathlib

    css = (pathlib.Path(__file__).resolve().parent.parent / "ui.py").read_text(
        encoding="utf-8")
    assert "--font:" in css, "글꼴 스택은 변수 하나로 둔다(두 군데가 갈리면 한쪽만 고친다)"
    assert '[data-testid="stMarkdownContainer"],' in css
    assert "font-family: var(--font) !important;" in css


def test_아이콘_글꼴을_싹_덮지_않는다():
    """Streamlit 아이콘은 `Material Symbols Rounded` **합자**다.

    `*` 로 글꼴을 덮으면 `keyboard_arrow_right` 같은 아이콘 이름이 글자로 그대로
    나온다. 아이콘 요소는 자기 `font-family` 를 갖고 있어 **상속으로는 안 깨지므로**,
    컨테이너만 지정하고 전역 `*` 는 쓰지 않는다.
    """
    import pathlib
    import re

    css = (pathlib.Path(__file__).resolve().parent.parent / "ui.py").read_text(
        encoding="utf-8")
    for line in css.splitlines():
        if "font-family" not in line:
            continue
        selector_blob = line
        assert not re.search(r"\.stApp\s+\*|^\s*\*\s*\{", selector_blob), (
            f"글꼴을 전역으로 덮으면 아이콘이 글자로 나옵니다: {line.strip()}"
        )
