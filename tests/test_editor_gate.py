"""편집 권한 — 광고주는 보기만.

이 화면은 광고주에게 링크로 그대로 공유한다. 편집 도구·AI 초안 버튼·수동 분류 같은
사내 작업 흔적이 보이면 안 된다. 그래서 **토글을 숨기는 것으로 끝내지 않고**
`edit_mode`를 False로 못 박는다(진입점) — 여기서는 그 판정 함수를 고정한다.
"""
from __future__ import annotations

import auth
import google_login


def test_editor_domains_are_madup_only():
    """광고주 도메인이 편집자 목록에 들어가면 그 순간 편집 도구가 공개된다."""
    assert auth.EDITOR_DOMAINS == ("madup.com",)
    assert "webtoonscorp.com" not in auth.EDITOR_DOMAINS


def test_allows_everyone_when_google_login_is_not_configured(monkeypatch):
    """로컬 개발·비밀번호 게이트 배포는 애초에 사내만 들어온다."""
    monkeypatch.setattr(google_login, "is_configured", lambda: False)
    assert auth.can_edit() is True


def test_madup_account_can_edit(monkeypatch):
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "a@madup.com")
    assert auth.can_edit() is True


def test_client_account_cannot_edit(monkeypatch):
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "b@webtoonscorp.com")
    assert auth.can_edit() is False


def test_missing_email_is_blocked(monkeypatch):
    """로그인은 됐는데 이메일을 못 읽었으면 막는다 — 뚫리는 쪽으로 기울면 안 된다."""
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: None)
    assert auth.can_edit() is False


def test_domain_match_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "A@MADUP.COM")
    assert auth.can_edit() is True


def test_lookalike_domain_is_blocked(monkeypatch):
    """`madup.com.evil.com` 같은 값이 통과하면 안 된다 — 접미사 비교가 아니라 정확 일치."""
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "x@madup.com.evil.com")
    assert auth.can_edit() is False


def test_subdomain_is_blocked(monkeypatch):
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "x@mail.madup.com")
    assert auth.can_edit() is False


def test_editing_is_narrower_than_viewing():
    """편집(`EDITOR_DOMAINS`)과 열람(`allowed_domains`)은 **별개 목록**이다.

    광고주 도메인은 배포 Secrets의 `[auth_allowlist]`에 들어 있어 **열람은 허용**되고
    (그게 이 앱의 목적이다), 편집 목록에는 없다. 여기서는 기본값만 확인한다 —
    Secrets가 없는 환경에서는 열람도 매드업뿐이다.
    """
    assert "madup.com" in google_login.DEFAULT_ALLOWED_DOMAINS
    assert set(auth.EDITOR_DOMAINS) <= set(google_login.DEFAULT_ALLOWED_DOMAINS)
    assert auth.EDITOR_DOMAINS is not google_login.DEFAULT_ALLOWED_DOMAINS
