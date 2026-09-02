# -*- coding: utf-8 -*-
"""편집 잠금의 소유자를 **계정**으로 잡는다.

예전에는 세션마다 새로 뽑는 uuid였다(로그인이 없던 시절 설계). 그래서 혼자 쓰는데도
재배포·새로고침·새 탭·웹소켓 재접속마다 토큰이 바뀌어, 방금까지 자기가 쥔 잠금이
"다른 창에서 편집 중"으로 보였다.

⚠ 이건 안전장치다. 계정을 못 읽을 때 아무 값이나 돌려주면 **두 사람이 같은 글을
동시에 덮어쓸 수 있다.** 그래서 "로그인이 꺼져 있으면 None"을 명시적으로 지킨다.
"""
import auth
import google_login


def test_로그인이_꺼져_있으면_None이다(monkeypatch):
    """비밀번호 게이트만 있는 배포판 — 예전처럼 세션 토큰으로 떨어진다."""
    monkeypatch.setattr(google_login, "is_configured", lambda: False)
    assert auth.current_editor() is None


def test_로그인한_이메일을_돌려준다(monkeypatch):
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "a@madup.com")
    assert auth.current_editor() == "a@madup.com"


def test_로그인은_켜졌지만_이메일이_없으면_None이다(monkeypatch):
    """세션이 아직 안 잡힌 순간이다. 빈 문자열을 소유자로 쓰면 **모든 사람이 같은
    소유자**가 되어 잠금이 통째로 무력해진다."""
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: None)
    assert auth.current_editor() is None
    monkeypatch.setattr(google_login, "current_email", lambda: "")
    assert auth.current_editor() is None


def test_다른_계정은_다른_소유자다(monkeypatch):
    monkeypatch.setattr(google_login, "is_configured", lambda: True)
    monkeypatch.setattr(google_login, "current_email", lambda: "a@madup.com")
    first = auth.current_editor()
    monkeypatch.setattr(google_login, "current_email", lambda: "b@madup.com")
    assert first != auth.current_editor()
