"""공개 배포용 비밀번호 게이트.

Streamlit Community Cloud 무료 요금제는 계정당 프라이빗 앱을 1개까지만 허용하는데,
그 자리를 이미 다른 대시보드가 쓰고 있어 이 앱은 공개(public)로 배포해야 한다. URL을 아는
사람이라면 로그인 화면까지는 보게 되므로, 그 뒤에서 고객사 실데이터를 막는 최소한의 장치다.

비밀번호는 절대 코드에 넣지 않는다 — Streamlit Cloud의 앱별 Secrets(비공개, 저장소에
커밋되지 않음)에만 `DASHBOARD_PASSWORD`로 등록한다. 로컬 개발 시에는
`.streamlit/secrets.toml`(gitignore 대상)에 같은 키를 넣으면 된다. Secrets가 아예
설정되지 않은 환경(예: 최초 로컬 셋업)에서는 게이트를 건너뛴다 — 그 상태에서는 배포된 게
아니라 개발자 본인 PC일 뿐이라는 뜻이다.
"""

from __future__ import annotations

import hmac

import streamlit as st

from ui import logo_data_uri

SESSION_KEY = "_authed"


def _configured_password() -> str | None:
    value = st.secrets.get("DASHBOARD_PASSWORD")
    return str(value) if value else None


def require_password() -> None:
    """비밀번호가 설정돼 있으면 인증 전까지 이후 코드를 실행하지 않는다."""
    password = _configured_password()
    if password is None:
        return  # 로컬 개발 등 secrets 미설정 환경 — 게이트 없이 통과
    if st.session_state.get(SESSION_KEY):
        return

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
            max-width: 480px !important;
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
