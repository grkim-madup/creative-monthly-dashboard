"""Google 로그인 게이트 — 네트워크 없이 검증할 수 있는 부분을 전부 고정한다.

이 게이트가 뚫리면 **광고주 실데이터가 공개 URL에 그대로 노출된다.** 그래서 "설정이
없으면 막는다", "도메인이 다르면 막는다"를 테스트로 못 박는다.

PKCE·state 왕복은 순수 함수로 떼어 놨다 — ASA에서는 `st.session_state`에 의존하다
실패했고(구글 리다이렉트 후 세션이 새로 시작된다), 그 교훈으로 `state`에 실어 보내는
구조가 됐다. 그 왕복이 실제로 복원되는지가 이 파일의 핵심이다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse

import pytest

import google_login as gl


# --------------------------------------------------------------------------- #
# 허용 도메인 — 뚫리면 데이터가 공개된다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("email", [
    "someone@madup.com",
    "SOMEONE@MADUP.COM",
    "  hello@madup.com  ",
])
def test_허용_도메인은_통과한다(email):
    assert gl.is_authorized_email(email, ("madup.com",)) is True


@pytest.mark.parametrize("email", [
    None, "", "no-at-sign", "someone@gmail.com", "someone@madup.com.evil.com",
    "someone@notmadup.com", "@madup.com",
])
def test_그_외에는_전부_막는다(email):
    assert gl.is_authorized_email(email, ("madup.com",)) is False


def test_광고주_도메인을_함께_허용할_수_있다():
    """이 리포트는 사내용이 아니라 광고주가 직접 본다."""
    domains = ("madup.com", "webtoonscorp.com")
    assert gl.is_authorized_email("pm@webtoonscorp.com", domains) is True
    assert gl.is_authorized_email("pm@webtoonscorp.co.kr", domains) is False


def test_기본_허용_도메인은_매드업뿐():
    """Secrets에 목록이 없을 때 광고주 도메인까지 열려 있으면 안 된다."""
    assert gl.DEFAULT_ALLOWED_DOMAINS == ("madup.com",)


# --------------------------------------------------------------------------- #
# PKCE + state 왕복 (ASA에서 세션 의존으로 실패했던 지점)
# --------------------------------------------------------------------------- #


def test_code_verifier는_규격_길이다():
    for _ in range(20):
        verifier = gl.make_code_verifier()
        assert 43 <= len(verifier) <= 128, "RFC 7636 범위를 벗어났다"
        assert set(verifier) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        ), "unreserved 문자만 쓸 수 있다"


def test_code_challenge가_S256_규격이다():
    verifier = "abc123"
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert gl.code_challenge(verifier) == expected
    assert "=" not in gl.code_challenge(verifier), "패딩이 남으면 구글이 거부한다"


def test_state에_실은_verifier가_그대로_돌아온다():
    """세션에 저장하지 않고 state로 왕복시키는 것이 이 구조의 전부다."""
    verifier = gl.make_code_verifier()
    assert gl.decode_state(gl.encode_state(verifier)) == verifier


def test_같은_verifier라도_state는_매번_다르다():
    """nonce가 없으면 state가 재사용 가능한 상수가 된다."""
    verifier = "same-verifier-value"
    assert gl.encode_state(verifier) != gl.encode_state(verifier)


@pytest.mark.parametrize("bad", [
    "", "not-base64!!", None,
    base64.urlsafe_b64encode(b"not json").decode(),
    base64.urlsafe_b64encode(json.dumps({"v": ""}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"x": "y"}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"v": 123}).encode()).decode(),
])
def test_손상되거나_위조된_state는_None(bad):
    assert gl.decode_state(bad) is None


# --------------------------------------------------------------------------- #
# 인증 URL — 잘못 조립하면 구글이 거부하거나(더 나쁘게) PKCE가 무력화된다
# --------------------------------------------------------------------------- #


CFG = {
    "client_id": "test-client-id.apps.googleusercontent.com",
    "client_secret": "test-secret",
    "redirect_uri": "https://tw-webtoon-creative.madup.app/",
}


def test_인증_URL이_필요한_것을_전부_담는다():
    verifier = gl.make_code_verifier()
    url = gl.build_auth_url(CFG, verifier)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert url.startswith(gl.AUTH_ENDPOINT)
    assert query["client_id"] == [CFG["client_id"]]
    assert query["redirect_uri"] == [CFG["redirect_uri"]]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [gl.code_challenge(verifier)]
    assert gl.decode_state(query["state"][0]) == verifier
    assert set(query["scope"][0].split()) == set(gl.SCOPES)


def test_인증_URL에_client_secret이_들어가지_않는다():
    """인증 URL은 브라우저 주소창에 그대로 노출된다."""
    url = gl.build_auth_url(CFG, gl.make_code_verifier())
    assert CFG["client_secret"] not in url


def test_verifier_원문이_URL에_그대로_노출되지_않는다():
    """challenge는 해시여야 한다 — 원문이 나가면 PKCE가 무의미하다."""
    verifier = gl.make_code_verifier()
    url = gl.build_auth_url(CFG, verifier)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert verifier not in query["code_challenge"][0]


# --------------------------------------------------------------------------- #
# 토큰 교환 — 실패 경로가 조용히 통과되지 않아야 한다
# --------------------------------------------------------------------------- #


def test_state가_없으면_교환을_시도조차_하지_않는다(monkeypatch):
    called = []
    monkeypatch.setattr(gl, "_post_token",
                        lambda *a, **k: called.append(1) or ({}, None))
    email, reason = gl.exchange_code_for_email(CFG, "some-code", None)
    assert email is None and reason
    assert not called, "state가 없는데 토큰 엔드포인트를 때렸다"


def test_id_token이_없으면_실패로_처리한다(monkeypatch):
    verifier = gl.make_code_verifier()
    monkeypatch.setattr(gl, "_post_token",
                        lambda *a, **k: ({"access_token": "x"}, None))
    email, reason = gl.exchange_code_for_email(
        CFG, "code", gl.encode_state(verifier)
    )
    assert email is None
    assert "id_token" in reason


def test_토큰_교환_실패_사유가_그대로_올라온다(monkeypatch):
    """madup.app에는 로그 화면이 없어 이 문구가 유일한 진단 수단이다."""
    verifier = gl.make_code_verifier()
    monkeypatch.setattr(gl, "_post_token",
                        lambda *a, **k: (None, "토큰 교환 실패 (HTTP 400) redirect_uri_mismatch"))
    email, reason = gl.exchange_code_for_email(
        CFG, "code", gl.encode_state(verifier)
    )
    assert email is None
    assert "redirect_uri_mismatch" in reason


def test_id_token_검증_실패는_로그인_실패다(monkeypatch):
    """검증을 건너뛰면 위조된 토큰으로 아무나 들어올 수 있다."""
    verifier = gl.make_code_verifier()
    monkeypatch.setattr(gl, "_post_token",
                        lambda *a, **k: ({"id_token": "forged"}, None))

    import google.oauth2.id_token as real

    def boom(*_a, **_k):
        raise ValueError("Token signature invalid")

    monkeypatch.setattr(real, "verify_oauth2_token", boom)
    email, reason = gl.exchange_code_for_email(
        CFG, "code", gl.encode_state(verifier)
    )
    assert email is None
    assert "id_token 검증 실패" in reason


def test_검증된_이메일이_그대로_돌아온다(monkeypatch):
    verifier = gl.make_code_verifier()
    monkeypatch.setattr(gl, "_post_token",
                        lambda *a, **k: ({"id_token": "ok"}, None))

    import google.oauth2.id_token as real

    monkeypatch.setattr(real, "verify_oauth2_token",
                        lambda *_a, **_k: {"email": "pm@webtoonscorp.com"})
    email, reason = gl.exchange_code_for_email(
        CFG, "code", gl.encode_state(verifier)
    )
    assert (email, reason) == ("pm@webtoonscorp.com", None)


# --------------------------------------------------------------------------- #
# 게이트 자체가 opt-in인지 / 새 의존성이 없는지
# --------------------------------------------------------------------------- #


def test_secrets가_없으면_게이트가_꺼진다():
    """로컬 개발이 지금과 똑같이 동작해야 한다(설정이 없을 때만)."""
    assert gl.is_configured() is False


def test_google_auth_oauthlib에_의존하지_않는다():
    """madup.app 컨테이너는 requirements 변경 후 재빌드되지 않는다(ASA 실측).

    이 모듈이 그 패키지를 쓰기 시작하면 배포판에서 ImportError로 로그인이 통째로 죽는다.
    """
    import ast

    tree = ast.parse(open(gl.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = {name for name in imported if "oauthlib" in name or "authlib" in name}
    assert not offenders, f"새 의존성이 들어왔다: {offenders}"

    # requirements.txt에도 들어가 있지 않아야 한다(들어가면 재빌드 문제를 다시 만난다).
    from pathlib import Path

    reqs = (Path(gl.__file__).resolve().parent / "requirements.txt")
    if reqs.exists():
        text = reqs.read_text(encoding="utf-8").lower()
        assert "oauthlib" not in text and "authlib" not in text
