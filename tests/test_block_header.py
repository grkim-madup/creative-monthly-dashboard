# -*- coding: utf-8 -*-
"""블록 헤더 — 섹션·블록·표 세 급이 **형태**로 갈려야 한다.

규리님(2026-09-08): *"메인 제목의 숫자와 블록의 숫자가 너무 겹치지 않을까?
디자인이 똑같잖아"* — 초록 번호를 그대로 축소하면 위계가 안 생기고, 액센트가
세 급에서 반복돼 흔해진다. 그래서 블록은 **회색 칩**이다.
"""
import pathlib
import re

import ui

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestStripNumberPrefix:
    """제목에 손으로 적어 둔 순번은 화면에서만 뗀다 — 저장된 글은 안 건드린다."""

    def test_실제_제목들(self):
        cases = {
            "신규 USP 제안 1: POV 형 상단 텍스트 영상 소재": "POV 형 상단 텍스트 영상 소재",
            "제안 2: 주요 회차 큐레이션형 6초 소재": "주요 회차 큐레이션형 6초 소재",
            "1) 정방형 / GIF 소재 성과": "정방형 / GIF 소재 성과",
            "주제 3 - TEXT형": "TEXT형",
        }
        for given, want in cases.items():
            assert ui.strip_number_prefix(given) == want, given

    def test_순번이_없으면_그대로(self):
        for title in ("정방형 / GIF 소재 성과", "TEXT형 소재 성과", "6초 소재"):
            assert ui.strip_number_prefix(title) == title

    def test_접두어만_있으면_원문을_살린다(self):
        """제목이 통째로 사라지는 게 중복보다 나쁘다."""
        assert ui.strip_number_prefix("제안 1:") == "제안 1:"
        assert ui.strip_number_prefix("1)") == "1)"

    def test_빈_값에도_안전하다(self):
        assert ui.strip_number_prefix("") == ""
        assert ui.strip_number_prefix(None) == ""

    def test_작품명_숫자를_먹지_않는다(self):
        """`6초 소재`의 6이나 작품 코드가 순번으로 오해되면 제목이 잘린다."""
        assert ui.strip_number_prefix("6초 소재 성과") == "6초 소재 성과"
        assert ui.strip_number_prefix("10398 소재") == "10398 소재"


class TestTone:
    """하우스 톤 규칙을 CSS에 대고 확인한다."""

    def css(self) -> str:
        return (ROOT / "ui.py").read_text(encoding="utf-8")

    def test_블록_칩은_초록이_아니다(self):
        """섹션(.sec-n)과 표(.tbl-title-bar)가 이미 브랜드 그린을 쓴다."""
        block = re.search(r"\.nh-num \{(.+?)\}", self.css(), re.S)
        assert block, ".nh-num 규칙이 없습니다"
        body = block.group(1)
        for green in ("--brand", "#00DC64", "#00A94C"):
            assert green not in body, f".nh-num 에 {green} 이 들어 있습니다"

    def test_세_급의_크기가_내려간다(self):
        css = self.css()
        def size(selector: str) -> float:
            rule = re.search(re.escape(selector) + r" \{(.+?)\}", css, re.S)
            assert rule, selector
            found = re.search(r"font-size: ([\d.]+)px", rule.group(1))
            assert found, selector
            return float(found.group(1))
        assert size(".sec-t") > size(".nh-t") > size(".tbl-title")

    def test_블록_사이_간격이_있다(self):
        rule = re.search(r"\.blockgap \{(.+?)\}", self.css(), re.S)
        assert rule, ".blockgap 이 없습니다"
        height = re.search(r"height: (\d+)px", rule.group(1))
        # 예전에는 래퍼가 아예 없어 두 블록이 바로 붙었다.
        assert height and int(height.group(1)) >= 24


def test_이모지를_쓰지_않는다():
    """하우스 룰. 자물쇠 이모지를 고정 패널에 썼다가 걷어냈다(2026-09-08)."""
    def emoji(ch: str) -> bool:
        return 0x1F000 <= ord(ch) <= 0x1FAFF
    for name in ("ui.py", "creative_dashboard.py", "app.py", "insight_draft.py"):
        path = ROOT / name
        if not path.exists():
            continue
        found = {ch for ch in path.read_text(encoding="utf-8") if emoji(ch)}
        assert not found, f"{name} 에 이모지: {found}"


def test_두_섹션이_같은_부품을_쓴다():
    """4번(주제)·6번(제안)이 각자 헤더를 만들면 다시 갈라진다.

    ⚠ **진입점 파일명을 하드코딩하지 말 것.** madup.app 배포판은 같은 파일이
      `app.py`로 이름만 바뀌어 들어간다 — `creative_dashboard.py`로 못 박으면
      배포 게이트가 `FileNotFoundError`로 막는다(2026-09-08에 실제로 막혔다).
    """
    checked = 0
    for name in ("creative_dashboard.py", "app.py"):
        path = ROOT / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert 'number=(f"주제 {number}" if number else None)' in source, name
        assert 'number=(f"제안 {number}" if number else None)' in source, name
        # 두 루프 모두 같은 간격 부품을 쓴다
        assert source.count("block_gap(first=(index == 0))") == 2, name
        checked += 1
    assert checked, "진입점 파일을 찾지 못했습니다"
