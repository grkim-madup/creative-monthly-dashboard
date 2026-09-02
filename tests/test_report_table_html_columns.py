# -*- coding: utf-8 -*-
"""`report_table`의 `html_columns` — 대조군 표의 매체 셀만 마크업을 직접 넣는다.

⚠ 이 통로는 이스케이프를 건너뛴다. **우리가 조립한 마크업만** 들어가야 하고,
밖에서 온 문자열(소재명·시트 값)이 이 컬럼에 실리면 표 안으로 임의의 HTML이 들어온다.
그래서 "지정한 컬럼만 통과하고 나머지는 여전히 막힌다"를 테스트로 못박는다.
"""
import pytest

import ui


@pytest.fixture()
def rendered(monkeypatch):
    captured = []
    monkeypatch.setattr(ui.st, "markdown",
                        lambda html, **kw: captured.append(html))
    return captured


def test_지정한_컬럼만_마크업으로_들어간다(rendered):
    ui.report_table(
        [['<span class="ct-dot"></span><b>Meta</b>', "<b>주의</b>"]],
        ["매체", "구분"], html_columns={"매체"},
    )
    html = rendered[0]
    assert '<span class="ct-dot"></span><b>Meta</b>' in html
    # 지정하지 않은 컬럼은 그대로 막힌다.
    assert "&lt;b&gt;주의&lt;/b&gt;" in html
    assert "<b>주의</b>" not in html


def test_기본값은_전부_이스케이프한다(rendered):
    ui.report_table([["<script>x</script>"]], ["매체"])
    assert "<script>" not in rendered[0]
    assert "&lt;script&gt;" in rendered[0]


def test_행_클래스와_셀_스타일이_함께_적용된다(rendered):
    ui.report_table(
        [["Meta", "-"], ["", "차이"]], ["매체", "구분"],
        row_classes=["ct-grp", "ct-delta"],
        cell_styles=[{}, {"구분": "background-color:#fdf3f3"}],
    )
    html = rendered[0]
    assert 'class="ct-grp"' in html
    assert 'class="ct-delta"' in html
    assert "background-color:#fdf3f3" in html


def test_대조군_표는_매체마다_3줄이다(rendered):
    """지표를 몇 개 고르든 세로 높이가 안 늘어난다 — 그게 B안을 고른 이유다."""
    metrics = ["소진액", "노출", "설치", "CTR", "CPI", "D0 Read CVR", "D0 Coin CVR"]
    rows = [["Meta", "epn"] + ["-"] * 7,
            ["", "그 외"] + ["-"] * 7,
            ["", "차이"] + ["-"] * 7]
    ui.report_table(rows, ["매체", "구분"] + metrics, html_columns={"매체"})
    assert rendered[0].count("<tr") == 4  # 헤더 1 + 본문 3


def test_rowspan으로_셀을_병합한다(rendered):
    """대조군 표의 매체 셀 — 세 줄이 한 매체라는 걸 병합으로 보여준다.

    0은 "위 행이 덮는 자리"라 `<td>`를 아예 그리지 않는다. 빈 문자열로 두면
    빈 칸이 그려져서 병합이 안 된다.
    """
    ui.report_table(
        [["Meta", "epn"], ["", "그 외"], ["", "차이"]],
        ["매체", "구분"],
        row_spans=[{"매체": 3}, {"매체": 0}, {"매체": 0}],
    )
    html = rendered[0]
    assert 'rowspan="3"' in html
    # 첫 줄 2칸(매체+구분) + 나머지 두 줄 각 1칸 = 4. 병합이 안 되면 6이 된다.
    assert html.count("<td") == 4


def test_병합해도_셀_스타일이_어긋나지_않는다(rendered):
    ui.report_table(
        [["Meta", "-"], ["", "차이"]], ["매체", "구분"],
        row_spans=[{"매체": 2}, {"매체": 0}],
        cell_styles=[{}, {"구분": "background-color:#fdf3f3"}],
    )
    assert "background-color:#fdf3f3" in rendered[0]
