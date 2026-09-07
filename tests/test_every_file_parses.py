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
    """이 테스트가 진입점을 빠뜨리면 존재 이유가 없어진다 — 목록에 있는지 못 박는다.

    진입점 이름은 배포처마다 다르다: 로컬·Streamlit Cloud는 `creative_dashboard.py`,
    madup.app 포털은 규칙상 `app.py`로 이름을 바꿔 복사한다. 둘 중 하나는 반드시 있어야
    한다(이 테스트는 배포 폴더 안에서도 돌기 때문이다 — 실제로 여기서 한 번 오탐이 났다).
    """
    names = {path.name for path in _python_files()}
    assert names & {"creative_dashboard.py", "app.py"}, "진입점이 검사 대상에서 빠졌다"
    assert "auth.py" in names and "fs_store.py" in names


def test_진입점_파일명을_하드코딩한_테스트가_없다():
    """madup.app 배포판은 진입점이 `app.py`다 — 이름을 못 박으면 배포가 막힌다.

    2026-09-08에 두 번 막혔다(한 번은 소스 스캔 테스트, 한 번은 블록 헤더 테스트).
    파일을 읽을 때는 항상 두 이름을 순회하고 없는 쪽은 건너뛴다.
    """
    import pathlib
    import re

    tests_dir = pathlib.Path(__file__).resolve().parent
    bad = []
    for path in sorted(tests_dir.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(source.splitlines(), 1):
            if not re.search(r'"creative_dashboard\.py"', line):
                continue
            # 두 이름을 함께 순회하는 형태는 정상이다.
            if '"app.py"' in line:
                continue
            bad.append(f"{path.name}:{line_no} {line.strip()[:70]}")
    assert not bad, ("진입점 파일명을 단독으로 하드코딩했습니다 — "
                     "`(\"creative_dashboard.py\", \"app.py\")` 를 순회하세요:\n  "
                     + "\n  ".join(bad))


#: 배포 복사본에 들어가지 않는데 **저장소에는 커밋된 소스가 있는** 폴더.
#: 동기화 스크립트는 최상위 `*.py` 와 `tests/` 만 복사한다 — 여기 파일을 테스트가
#: 그냥 읽으면 배포 전 pytest가 `FileNotFoundError`로 막힌다(2026-09-08 실제로 막혔다).
#:
#: `notes/`·`.cache/`는 넣지 않는다 — 테스트가 그 이름을 쓰는 건 `tmp_path`로 갈아끼운
#: **쓰기 대상**이고 저장소 파일을 읽지 않는다(넣었더니 오탐 5건이 났다).
UNSHIPPED_DIRS = ("tools",)


def test_배포에_없는_폴더를_읽는_테스트는_존재를_확인한다():
    """저장소 위생 검사는 배포판에서 **건너뛰어야** 한다.

    진입점 파일명 하드코딩(`test_진입점_파일명을_하드코딩한_테스트가_없다`)과 같은
    뿌리다 — 배포 복사본은 저장소의 부분집합인데 테스트가 그걸 모른다.
    """
    import pathlib

    tests_dir = pathlib.Path(__file__).resolve().parent
    bad = []
    for path in sorted(tests_dir.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        # 실제 위험은 **저장소 파일을 읽는 것**이다. 이름만 등장하는 경우는 뺀다.
        if "read_text(" not in source:
            continue
        touched = [d for d in UNSHIPPED_DIRS if f'"{d}"' in source]
        if not touched:
            continue
        # `exists()` 확인이나 `skip` 이 같은 파일 안에 있어야 한다.
        if ".exists()" in source or "skip(" in source:
            continue
        bad.append(f"{path.name} — {', '.join(touched)} 를 읽는데 존재 확인이 없습니다")
    assert not bad, ("배포 복사본에 없는 폴더를 무조건 읽습니다:\n  "
                     + "\n  ".join(bad))
