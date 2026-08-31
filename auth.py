"""공개 배포용 접근 게이트 — Google 로그인 우선, 없으면 비밀번호.

`[google_login]` Secrets가 있으면 **Google 로그인**(`google_login.py`)을 쓰고,
없으면 아래 비밀번호 게이트로 넘어간다. 두 경로를 함께 두는 이유:
  - madup.app·Streamlit Cloud 배포는 Google 로그인으로 도메인 허용 목록을 적용한다
    (매드업 + 광고주 `webtoonscorp.com`). 비밀번호를 공유·회전할 필요가 없다.
  - 로컬 개발과 Google 로그인을 아직 설정하지 않은 배포는 예전대로 동작한다.
**둘 다 없으면 통과가 아니라 차단이다**(fail-closed) — 아래 참고.

--- 이하 비밀번호 게이트 설명 (Google 로그인이 없을 때만 쓰인다) ---

Streamlit Community Cloud 무료 요금제는 계정당 프라이빗 앱을 1개까지만 허용하는데,
그 자리를 이미 다른 대시보드가 쓰고 있어 이 앱은 공개(public)로 배포해야 한다. URL을 아는
사람이라면 로그인 화면까지는 보게 되므로, 그 뒤에서 고객사 실데이터를 막는 최소한의 장치다.

비밀번호는 절대 코드에 넣지 않는다 — Streamlit Cloud의 앱별 Secrets(비공개, 저장소에
커밋되지 않음)에만 `DASHBOARD_PASSWORD`로 등록한다.

혼자 쓰는 로컬 개발에서는 매번 비밀번호를 넣는 게 번거로우니 `.streamlit/secrets.toml`
(gitignore 대상)에 `DASHBOARD_NO_AUTH = true`를 넣어 게이트를 끌 수 있다.

**둘 다 없으면 통과시키지 않고 막는다(fail-closed).** 예전에는 비밀번호가 없으면 그냥
통과시켰는데, 그러면 배포판 Secrets에서 비밀번호가 실수로 지워지는 순간 고객사 실데이터가
그대로 공개된다. 게이트를 끄는 건 반드시 명시적인 선언(DASHBOARD_NO_AUTH)이어야 한다.
"""

from __future__ import annotations

import hmac

import streamlit as st

import google_login
from ui import logo_data_uri

SESSION_KEY = "_authed"


def _secret(name: str):
    """secrets.toml이 아예 없는 환경에서도 조용히 None을 돌려준다."""
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001 - secrets 파일 자체가 없으면 접근에서 예외가 난다
        return None


def _configured_password() -> str | None:
    value = _secret("DASHBOARD_PASSWORD")
    return str(value) if value else None


def _auth_disabled() -> bool:
    """게이트를 끄겠다고 명시적으로 선언했는지. 로컬 단독 사용 편의를 위한 장치다."""
    value = _secret("DASHBOARD_NO_AUTH")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"} if value is not None else False


def require_password() -> None:
    """인증 전까지 이후 코드를 실행하지 않는다.

    DASHBOARD_NO_AUTH가 켜져 있으면 게이트를 건너뛰고, 비밀번호가 없으면 통과가 아니라
    차단한다 — 배포 환경에서 비밀번호가 빠졌을 때 데이터가 공개되는 걸 막기 위해서다.
    """
    if _auth_disabled():
        return

    # Google 로그인이 설정돼 있으면 그쪽이 게이트다. 통과하면 그대로 반환한다.
    if google_login.is_configured():
        google_login.require_login()
        return

    if st.session_state.get(SESSION_KEY):
        return

    password = _configured_password()
    if password is None:
        st.error(
            "접근 제한이 설정되지 않아 리포트를 열 수 없습니다. Secrets에 "
            "[google_login](권장) 또는 DASHBOARD_PASSWORD를 등록하거나, "
            "혼자 쓰는 로컬이라면 DASHBOARD_NO_AUTH = true 를 넣어 주세요."
        )
        st.stop()

    # 컨테이너 폭 축소는 테스트 대상 Streamlit 버전 기준 실제 testid로 잡는다(구버전 문서의
    # ".main .block-container" 셀렉터는 여기서 매치되지 않는다). 480px로 넉넉히 잡아 제목이
    # 세 줄로 접히지 않게 한다("네이버웹툰 대만 · 먼슬리 크리에이티브 리포트"가 380px에서는
    # 어색하게 줄바꿈됐다). 폼 제출 버튼은 kind="primary"가 아니라 "primaryFormSubmit"로
    # 렌더된다(st.form_submit_button 전용 kind) — 일반 st.button용 전역 CSS(.stButton 스코프,
    # kind="primary")가 여기엔 안 걸려서 이 kind를 직접 지정해 브랜드 그린을 입힌다.
    st.markdown(
        """
        <style>
        /* margin:auto는 사이드바를 숨겨도 그 접기 화살표(collapsedControl)가 옆에 남아
           flex 형제 요소로 폭을 조금 뺏어가는 바람에 살짝 오른쪽으로 치우쳐 보였다.
           뷰포트 기준으로 강제 고정하면 사이드바 잔여 요소와 무관하게 항상 정중앙이다. */
        [data-testid="stMainBlockContainer"] {
            /* 제목 한 줄("네이버웹툰 대만 · 먼슬리 크리에이티브 리포트")이 nowrap으로
               강제된 채 이 컨테이너의 실제 콘텐츠 폭(패딩 제외 320px)보다 넓어서
               (실측 scrollWidth 357px) 오른쪽으로 넘쳤다. 패딩(좌우 80px씩)까지 감안해
               560px로 넉넉히 잡아 어떤 폰트 렌더링에서도 한 줄 안에 다 들어오게 한다. */
            max-width: 560px !important;
            position: fixed !important; left: 50% !important; top: 12vh !important;
            transform: translateX(-50%) !important;
        }
        /* 로그인 전에는 본문 사이드바가 의미 없다 — 아예 숨긴다(접기 화살표까지 포함). */
        [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
        .auth-logo { display: flex; justify-content: center; margin-bottom: 18px; }
        .auth-logo img { height: 40px; }
        .auth-title { text-align: center; font-size: 19px; font-weight: 700;
            margin-bottom: 6px; white-space: nowrap; }
        .auth-caption { text-align: center; color: var(--ink-2, #4b5563);
            font-size: 13px; margin-bottom: 18px; }
        button[data-testid="stBaseButton-primaryFormSubmit"] {
            background-color: var(--brand, #00DC64) !important;
            border-color: var(--brand, #00DC64) !important;
        }
        button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
            background-color: var(--brand-deep, #00A94C) !important;
            border-color: var(--brand-deep, #00A94C) !important;
        }
        /* Streamlit이 입력칸 안에 "Press Enter to submit form" 안내를 겹쳐서 그리는데,
           이 폭에서는 눈(비밀번호 표시) 아이콘과 자리가 겹쳐 텍스트 정렬이 깨지고 아이콘
           클릭도 막힌다. 아래에 이미 제출 버튼이 보이니 이 안내는 없어도 된다. 부모 스코프를
           좁게 잡았다가 안 먹힌 적이 있어(중첩 구조가 버전에 따라 달라짐) 테스트id 하나로 넓게
           잡는다. */
        div[data-testid="InputInstructions"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    logo = logo_data_uri()
    if logo:
        st.markdown(f'<div class="auth-logo"><img src="{logo}" alt=""></div>',
                    unsafe_allow_html=True)
    st.markdown('<div class="auth-title">네이버웹툰 대만 · 먼슬리 크리에이티브 리포트</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="auth-caption">내부 공유용 대시보드입니다. 비밀번호를 입력하세요.</div>',
                unsafe_allow_html=True)
    with st.form("auth_gate_form", border=True):
        entered = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                                 placeholder="비밀번호")
        submitted = st.form_submit_button("입장", type="primary", width="stretch")

    if submitted:
        # compare_digest는 str끼리 비교할 때 ASCII만 허용한다 — 한글 비밀번호를 쓰면
        # TypeError로 죽는다. bytes로 인코딩해서 비교하면 어떤 문자든 안전하다.
        if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")

    st.stop()
