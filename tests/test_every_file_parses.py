"""모든 파이썬 파일이 **문법적으로 성립하는지** 본다.

왜 이 파일이 있는가: `creative_dashboard.py`(진입점)에 들여쓰기 오류가 들어간 채로
1단계 커밋이 배포판에 올라갔고, **Streamlit Cloud 라이브 대시보드가 며칠간 깨져 있었다**
(2026-09-01에 madup.app 첫 배포 화면을 눈으로 확인하다 발견했다).

테스트 375개가 전부 통과했는데도 못 잡은 이유는 단순하다 — **어떤 테스트도 진입점을
import하지 않는다.** 진입점은 `import streamlit` 후 즉시 화면을 그리기 시작하므로
테스트에서 import할 수 없고, 그래서 아무도 이 파일을 건드리지 않았다.

`compile()`은 실행하지 않고 파싱만 한다 → 화면을 그리지 않고도 문법을 검증할 수 있다.
런타임 오류(잘못된 인자 등)는 여전히 못 잡지만, **"파일이 아예 안 열린다"**는
가장 치명적이고 가장 잡기 쉬운 종류를 막는다.

`sync_to_deploy.py`/`sync_to_madup_app.py`가 push 전에 pytest를 돌리므로,
이 테스트가 곧 **배포 게이트**가 된다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: 검사 대상 — 저장소 안의 모든 .py. 가상환경·캐시는 없다(이 프로젝트는 venv를 쓰지 않는다).
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", "notes"}


def _python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if set(path.relative_to(ROOT).parts) & SKIP_DIRS:
            continue
        yield path


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: p.name)
def test_파일이_파싱된다(path: Path):
    source = path.read_text(encoding="utf-8")
    try:
        compile(source, str(path), "exec")
    except SyntaxError as error:
        pytest.fail(
            f"{path.relative_to(ROOT)}:{error.lineno} 문법 오류 — {error.msg}\n"
            f"  {(error.text or '').rstrip()}\n"
            "  이 파일이 진입점이거나 진입점이 import하는 모듈이면 배포판이 아예 안 뜬다."
        )


def test_진입점이_실제로_검사_대상에_들어있다():
    """이 테스트가 진입점을 빠뜨리면 존재 이유가 없어진다 — 목록에 있는지 못 박는다."""
    names = {path.name for path in _python_files()}
    assert "creative_dashboard.py" in names, "진입점이 검사 대상에서 빠졌다"
    assert "auth.py" in names and "fs_store.py" in names
