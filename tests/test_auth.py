"""비밀번호 게이트의 판단 로직 — 잘못 열리면 고객사 데이터가 공개되므로 분기를 못 박아 둔다."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth  # noqa: E402


@pytest.fixture
def secrets(monkeypatch):
    """st.secrets를 흉내내는 dict. auth._secret이 이 값을 읽게 한다."""
    store: dict = {}
    monkeypatch.setattr(auth, "_secret", lambda name: store.get(name))
    return store


def test_no_auth_flag_disables_gate(secrets):
    secrets["DASHBOARD_NO_AUTH"] = True
    assert auth._auth_disabled() is True


def test_no_auth_accepts_string_true(secrets):
    # secrets.toml에 문자열로 들어오는 경우(TOML 실수 포함)도 받아준다
    for value in ("true", "True", "TRUE", "1", "yes"):
        secrets["DASHBOARD_NO_AUTH"] = value
        assert auth._auth_disabled() is True, value


def test_no_auth_false_keeps_gate(secrets):
    for value in (False, "false", "0", "no", ""):
        secrets["DASHBOARD_NO_AUTH"] = value
        assert auth._auth_disabled() is False, value


def test_gate_stays_on_when_flag_absent(secrets):
    assert auth._auth_disabled() is False


def test_password_read_from_secrets(secrets):
    secrets["DASHBOARD_PASSWORD"] = "hunter2"
    assert auth._configured_password() == "hunter2"


def test_password_is_none_when_absent(secrets):
    assert auth._configured_password() is None


def test_password_is_none_when_blank(secrets):
    # 빈 문자열을 비밀번호로 인정하면 아무 입력 없이 통과할 수 있다
    secrets["DASHBOARD_PASSWORD"] = ""
    assert auth._configured_password() is None


def test_missing_secrets_file_does_not_raise(monkeypatch):
    """secrets.toml이 아예 없는 환경에서 st.secrets 접근은 예외를 던진다 — 삼켜야 한다."""
    class Boom:
        def get(self, name):
            raise FileNotFoundError("no secrets.toml")

    monkeypatch.setattr(auth.st, "secrets", Boom())
    assert auth._secret("DASHBOARD_PASSWORD") is None
    assert auth._configured_password() is None
    assert auth._auth_disabled() is False  # 못 읽으면 게이트를 여는 게 아니라 유지한다
