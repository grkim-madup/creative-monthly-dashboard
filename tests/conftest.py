"""모든 테스트를 실제 구글시트에서 격리한다 (fail-closed).

왜 이 파일이 있는가: 저장소를 로컬 파일에서 시트로 옮기자, `configured()`가 True인
개발 PC(실제 secrets.toml이 있는 곳)에서 테스트가 **운영 스냅샷 시트에 그대로 쓰기 시작했다.**
실제로 한 번 그렇게 됐고(테스트 fixture 값이 시트에 행으로 남았다, 2026-08-28) 테스트
한 파일이 100초 넘게 걸리는 것으로 드러났다.

그래서 여기서 기본값을 강제로 "시트 없음"으로 만든다. 시트 백엔드를 검증하는 테스트는
`tests/fake_sheets.install(...)`로 인메모리 가짜 시트를 명시적으로 붙여서 쓴다 —
실수로 빠뜨렸을 때 조용히 운영 시트로 가지 않고, 아예 예외가 난다.

이 안전장치는 제거하거나 우회하지 말 것.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import blocks  # noqa: E402
import google_sheets_writer  # noqa: E402
import highlights  # noqa: E402
import locks  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_sheet(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError(
            "테스트가 실제 구글시트에 접근하려 했습니다. "
            "시트 백엔드를 검증하려면 tests/fake_sheets.install(monkeypatch, "
            "google_sheets_writer)를 쓰세요."
        )

    monkeypatch.setattr(google_sheets_writer, "configured", lambda: False)
    monkeypatch.setattr(google_sheets_writer, "_service", _forbidden)
    monkeypatch.setattr(google_sheets_writer, "_service_account_info", lambda: None)

    # 모듈 전역 캐시는 테스트 사이에 그대로 남아, 앞 테스트의 상태가 뒤 테스트의 결과를
    # 바꾼다(실제로 잠금 테스트 3개가 이렇게 어긋났다). 앞뒤로 비운다.
    locks.reset_state()
    highlights.clear_cache()
    blocks.clear_state_cache()
    google_sheets_writer.clear_image_cache()
    yield
    locks.reset_state()
    highlights.clear_cache()
    blocks.clear_state_cache()
    google_sheets_writer.clear_image_cache()
