"""공개 배포 접근 제한 — 직접 구현한 Google OAuth 2.0 로그인 게이트.

ASA 위클리 대시보드의 `asa_auth.py`(2026-08-31 실전 검증)를 이 리포트로 옮긴 것이다.
그쪽에서 얻은 교훈을 그대로 지키면서 **의존성만 더 줄였다.**

## 왜 Streamlit 네이티브 `st.login()`을 쓰지 않는가

Authlib이 설치돼 있어야 동작하는데, madup.app 컨테이너는 `requirements.txt`에 패키지를
추가해도 **재빌드되지 않은 채 뜬다**(ASA에서 실측). `/auth/login`이 상세 없는 순수 500으로
죽는다. 컨테이너 재빌드는 이 저장소에서 손댈 수 없는 영역이다.

## 왜 `google-auth-oauthlib`도 쓰지 않는가 (ASA와 다른 점)

ASA는 `google_auth_oauthlib.flow.Flow`를 썼다. 그쪽 `requirements.txt`에는 이미 있어서
안전했지만, **이 프로젝트에는 없다.** 위와 같은 이유로 새 패키지를 추가하면 컨테이너가
재빌드되지 않아 `ImportError`로 로그인이 통째로 죽을 수 있다. Flow가 해 주는 일은
①인증 URL 조립 ②토큰 엔드포인트에 POST 두 가지뿐이라, **표준 라이브러리(`urllib`,
`hashlib`, `base64`)로 직접 한다.** id_token 검증만 `google-auth`를 쓰는데, 그건
`google_sheets_readonly.py`가 이미 쓰고 있어 확실히 설치돼 있다.

## 리다이렉트 처리 방식

Streamlit에 커스텀 서버 라우트를 만들 방법이 없으므로 redirect_uri를 앱의 **루트 URL**로
등록한다. 구글이 `?code=...&state=...`를 달고 루트로 돌아오면 스크립트가 처음부터 다시
실행되면서 `st.query_params`로 그 code를 읽어 교환을 마친다 — 콜백 라우트가 필요 없다.

## ⚠ `st.session_state`는 이 왕복 동안 못 믿는다 (ASA 실측)

같은 브라우저 탭인데도 구글로 나갔다 돌아오면 세션이 완전히 새로 시작된다. PKCE
`code_verifier`를 세션에 저장했다 콜백에서 읽는 방식은 **반드시 실패한다.** 그래서
`code_verifier`를 OAuth `state` 파라미터에 실어 왕복시킨다 — `state`는 스펙상 구글이 그대로
에코해 주는 것이 보장된 유일한 값이다. 서명·암호화는 하지 않는다(base64+json). 이 값이
노출돼도 얻는 것은 "우리 client_id로 자기 계정으로 로그인을 완료하는 능력"뿐이고, 그 뒤에
**도메인 허용 목록 검사**를 통과해야 하므로 권한 상승으로 이어지지 않는다.

## 게이팅 원칙

1. `[google_login]` Secrets가 없으면 이 게이트는 **아무 것도 하지 않는다**(opt-in).
   `auth.py`가 그때 예전 비밀번호 게이트로 넘긴다.
2. 설정이 있는데 이메일이 허용 도메인이 아니면 **반드시 막는다**(fail-closed).
3. 막을 때는 `st.stop()`으로 렌더 자체를 건너뛴다 — CSS로 감추지 않는다.
4. 실패 사유를 화면에 그대로 찍는다. madup.app에는 서버 로그를 볼 화면이 없어
   **이게 유일한 진단 수단**이다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets as _secrets_mod
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

from ui import logo_data_uri

#: 허용 이메일 도메인 기본값. `[auth_allowlist].domains`로 배포별로 덮어쓴다.
DEFAULT_ALLOWED_DOMAINS = ("madup.com",)

SESSION_EMAIL_KEY = "_google_login_email"

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)


def _secret_table(section: str):
    """secrets.toml이 아예 없는 로컬 실행에서도 조용히 None을 돌려준다."""
    try:
        return st.secrets.get(section)
    except Exception:  # noqa: BLE001 - secrets 파일 자체가 없으면 접근에서 예외가 난다
        return None


def is_configured() -> bool:
    """이 배포가 `[google_login]` Secrets를 갖고 있는가 — 있으면 게이트가 켜진다."""
    try:
        return "google_login" in st.secrets
    except Exception:  # noqa: BLE001
        return False


def allowed_domains() -> tuple:
    """허용 이메일 도메인. `[auth_allowlist].domains`가 있으면 그걸, 없으면 기본값."""
    table = _secret_table("auth_allowlist")
    domains = table.get("domains") if table else None
    if not domains:
        return DEFAULT_ALLOWED_DOMAINS
    return tuple(str(d).strip().lower() for d in domains if str(d).strip())


def is_authorized_email(email, domains: tuple = DEFAULT_ALLOWED_DOMAINS) -> bool:
    """이메일이 허용 도메인에 속하는가. 순수 함수 — pytest 대상.

    로컬 파트(@ 앞)가 비어 있으면 거부한다 — `"@madup.com"` 같은 값이 통과하던 것을
    테스트가 잡았다. 구글이 그런 값을 돌려줄 일은 없지만, 게이트는 좁게 잠근다.
    """
    text = str(email or "").strip()
    if "@" not in text:
        return False
    local, _, domain = text.rpartition("@")
    if not local.strip():
        return False
    return domain.strip().lower() in domains


# --------------------------------------------------------------------------- #
# PKCE + state (전부 순수 함수 — 실제 네트워크 없이 테스트한다)
# --------------------------------------------------------------------------- #


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def make_code_verifier() -> str:
    """RFC 7636의 code_verifier (43~128자의 unreserved 문자)."""
    return _b64url(_secrets_mod.token_bytes(64))[:128]


def code_challenge(verifier: str) -> str:
    """S256 방식 code_challenge. `google-auth-oauthlib` 없이 직접 만든다."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def encode_state(verifier: str) -> str:
    """code_verifier를 state 파라미터 값 하나로 감싼다. 순수 함수."""
    payload = json.dumps({"n": _secrets_mod.token_urlsafe(12), "v": verifier})
    return _b64url(payload.encode())


def decode_state(state) -> str | None:
    """`encode_state`의 역함수. 손상·위조된 값이면 None. 순수 함수."""
    try:
        text = str(state)
        padded = text + "=" * (-len(text) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        verifier = payload.get("v")
        return verifier if isinstance(verifier, str) and verifier else None
    except Exception:  # noqa: BLE001 - 변조/손상된 state는 그냥 실패로 처리
        return None


def build_auth_url(cfg, verifier: str) -> str:
    """구글 로그인 화면으로 보낼 URL. 순수 함수 — 네트워크를 타지 않는다."""
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": encode_state(verifier),
        "code_challenge": code_challenge(verifier),
        "code_challenge_method": "S256",
        "access_type": "online",
        "include_granted_scopes": "true",
        # 여러 구글 계정을 쓰는 사람이 많다 — 매번 계정을 고르게 한다.
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


# --------------------------------------------------------------------------- #
# 토큰 교환
# --------------------------------------------------------------------------- #


def _post_token(cfg, code: str, verifier: str) -> tuple[dict | None, str | None]:
    """토큰 엔드포인트에 교환 요청. 표준 라이브러리만 쓴다."""
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"],
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode()
    request = urllib.request.Request(
        TOKEN_ENDPOINT, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode()), None
    except urllib.error.HTTPError as error:
        # 구글의 에러 본문에 실제 원인이 들어 있다(redirect_uri 불일치, code 재사용 등).
        # madup.app에는 로그 화면이 없으니 이 문구가 유일한 단서가 된다.
        detail = ""
        try:
            detail = error.read().decode()[:300]
        except Exception:  # noqa: BLE001, S110
            pass
        return None, f"토큰 교환 실패 (HTTP {error.code}) {detail}"
    except Exception as error:  # noqa: BLE001
        return None, f"토큰 교환 실패: {type(error).__name__}: {error}"


def exchange_code_for_email(cfg, code: str, state) -> tuple[str | None, str | None]:
    """authorization code를 검증된 이메일로 바꾼다. 실패면 `(None, 사유)`."""
    verifier = decode_state(state) if state else None
    if not verifier:
        return None, "state 파라미터가 없거나 우리가 발급한 값이 아닙니다."

    payload, reason = _post_token(cfg, code, verifier)
    if payload is None:
        return None, reason

    raw_id_token = payload.get("id_token")
    if not raw_id_token:
        return None, "구글 응답에 id_token이 없습니다(scope 설정을 확인하세요)."

    # 검증은 google-auth로 한다 — 이 프로젝트가 이미 쓰는 패키지다(새 의존성 없음).
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = google_id_token.verify_oauth2_token(
            raw_id_token, google_requests.Request(), cfg["client_id"]
        )
    except Exception as error:  # noqa: BLE001 - 위조·만료된 토큰
        return None, f"id_token 검증 실패: {error}"

    email = claims.get("email")
    if not email:
        return None, "id_token에 email 정보가 없습니다."
    return email, None


# --------------------------------------------------------------------------- #
# 화면
# --------------------------------------------------------------------------- #

#: 구글 4색 "G" — 로그인 버튼 안에서만 쓰는 인라인 SVG.
_GOOGLE_G = (
    '<svg width="16" height="16" viewBox="0 0 48 48" style="flex:none">'
    '<path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.6 29.3 36 24 36c-6.6 0-12-5.4-12-12'
    's5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6.5 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 '
    '20-8.9 20-20c0-1.3-.1-2.7-.4-3.5z"/>'
    '<path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7'
    'C34.6 6.5 29.6 4 24 4c-7.6 0-14.1 4.3-17.7 10.7z"/>'
    '<path fill="#4CAF50" d="M24 44c5.5 0 10.4-1.9 14.2-5.1l-6.6-5.4C29.7 34.9 27 36 24 36c-5.3 0-9.7'
    '-3.4-11.3-8.1l-6.6 5.1C9.8 39.5 16.4 44 24 44z"/>'
    '<path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.7l6.6 5.4C41.7 36 44 '
    '30.6 44 24c0-1.3-.1-2.7-.4-3.5z"/>'
    "</svg>"
)

#: ASA 로그인 화면(좌우 분할, 2026-08-31 사용자 확정)과 같은 구조·톤. 이 리포트의
#: 디자인 시스템 값(브랜드 그린 #00DC64, Pretendard, 정수 radius)에 맞춰 옮겼다.
_LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
[data-testid="stHeader"] { display: none !important; }
[data-testid="stMainBlockContainer"] { padding: 0 !important; max-width: none !important; }
.login-stage {
    position: fixed; inset: 0; z-index: 9999; background: #ffffff;
    display: grid; grid-template-columns: 1.05fr 1fr; font-family: Pretendard, sans-serif;
}
.login-brand {
    padding: 0 6vw; display: flex; flex-direction: column; justify-content: center;
    border-right: 1px solid #e5e7eb; background: #fafafa;
}
.login-brand img { height: 30px; width: auto; margin-bottom: 26px; }
.login-brand h2 {
    font-size: 27px; font-weight: 800; line-height: 1.42; color: #111827; margin: 0;
    letter-spacing: -0.4px;
}
.login-brand p {
    font-size: 13.5px; color: #4b5563; margin-top: 14px; line-height: 1.78; max-width: 380px;
}
.login-form {
    padding: 0 6vw; display: flex; flex-direction: column; justify-content: center;
}
.login-title { font-size: 20px; font-weight: 800; color: #111827; }
.login-sub { font-size: 13px; color: #6b7280; margin-top: 9px; line-height: 1.7; }
.login-btn, .login-btn:link, .login-btn:visited, .login-btn:hover, .login-btn:active {
    display: inline-flex; align-items: center; gap: 9px; margin-top: 22px;
    padding: 11px 18px; border-radius: 3px; background: #00A94C; color: #ffffff !important;
    font-size: 13.5px; font-weight: 700; text-decoration: none !important; width: fit-content;
}
.login-btn:hover { background: #00913F; }
.login-fail {
    background: #fdf1f1; border: 1px solid #f3c8c8; color: #8a1f1f; border-radius: 3px;
    padding: 10px 12px; font-size: 12.5px; line-height: 1.6; margin-bottom: 18px;
    word-break: break-all;
}
.login-foot { font-size: 11px; color: #9ca3af; margin-top: 20px; }
@media (max-width: 820px) {
    .login-stage { grid-template-columns: 1fr; overflow-y: auto; }
    .login-brand { border-right: none; border-bottom: 1px solid #e5e7eb; padding: 7vh 8vw 5vh; }
    .login-form { padding: 5vh 8vw 7vh; }
}
</style>
"""


def _show_login_screen(cfg, fail_reason: str | None) -> None:
    verifier = make_code_verifier()
    auth_url = build_auth_url(cfg, verifier)

    logo = logo_data_uri()
    logo_html = f'<img src="{logo}" alt="">' if logo else ""
    # 실패 배너는 .login-stage 안(오른쪽 패널)에 둔다 — 바깥 형제로 두면 고정 오버레이에
    # 가려 안 보인다(ASA에서 실제로 그랬다).
    fail_html = (f'<div class="login-fail">로그인에 실패했습니다: {fail_reason}</div>'
                 if fail_reason else "")

    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="login-stage">'
        '<div class="login-brand">'
        f"{logo_html}"
        "<h2>네이버웹툰 대만<br>먼슬리 크리에이티브 리포트</h2>"
        "<p>매체별 소재 성과와 제작 인사이트를 정리한 월간 리포트입니다. "
        "매드업·광고주 공용 페이지입니다.</p>"
        "</div>"
        '<div class="login-form">'
        f"{fail_html}"
        '<div class="login-title">로그인이 필요합니다</div>'
        '<div class="login-sub">매드업 구성원 또는 초대된 광고주만 볼 수 있는 페이지입니다.'
        "<br>Google 계정으로 로그인해 주세요.</div>"
        f'<a class="login-btn" href="{auth_url}" target="_self">'
        f"{_GOOGLE_G}Google 계정으로 로그인</a>"
        '<div class="login-foot">문제가 있으면 매드업 담당자에게 문의해 주세요</div>'
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def require_login() -> None:
    """로그인 게이트. 사이드바·본문을 그리기 **전에** 호출한다.

    `[google_login]` Secrets가 없으면 아무 것도 하지 않는다(opt-in) — 그 경우
    `auth.py`가 예전 비밀번호 게이트로 넘긴다.
    """
    if not is_configured():
        return

    cfg = _secret_table("google_login")

    if not st.session_state.get(SESSION_EMAIL_KEY):
        code = st.query_params.get("code")
        if code:
            email, reason = exchange_code_for_email(
                cfg, code, st.query_params.get("state")
            )
            st.query_params.clear()
            if email:
                st.session_state[SESSION_EMAIL_KEY] = email
                st.rerun()
            _show_login_screen(cfg, reason)
            st.stop()
        _show_login_screen(cfg, None)
        st.stop()

    email = st.session_state[SESSION_EMAIL_KEY]
    if not is_authorized_email(email, allowed_domains()):
        st.title("접근 권한이 없습니다")
        st.error(f"{email} 계정은 이 페이지에 대한 접근 권한이 없습니다.")
        if st.button("다른 계정으로 로그인"):
            st.session_state.pop(SESSION_EMAIL_KEY, None)
            st.rerun()
        st.stop()


def current_email() -> str | None:
    """로그인한 사용자의 이메일(게이트가 꺼져 있으면 None)."""
    return st.session_state.get(SESSION_EMAIL_KEY)
