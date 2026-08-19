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
    # ".main .block-container" 셀렉터는 여기서 매치되지 않는다). 폼 버튼은 kind="primary"를
    # 줘도 이 앱 전역 CSS(.stButton 스코프)가 st.form_submit_button까지는 안 덮어써서
    # 브랜드 그린을 이 폼 key로 한정해 직접 입힌다.
    # 폼 제출 버튼은 kind="primary"가 아니라 "primaryFormSubmit"로 렌더된다(st.form_submit_button
    # 전용 kind) — 일반 st.button용 전역 CSS(.stButton 스코프, kind="primary")가 여기엔
    # 안 걸려서 이 kind를 직접 지정해 브랜드 그린을 입힌다. 사이드바가 남아 있으면 폭 제한만으론
    # 안 가운데로 보여서 margin:auto로 확실히 중앙 정렬한다.
    st.markdown(
        """
        <style>
        [data-testid="stMainBlockContainer"] {
            max-width: 380px !important; margin: 16vh auto 0 auto !important;
        }
        /* 로그인 전에는 본문 사이드바가 의미 없다 — 접힌 채로 남아 있으면 남은 폭 기준
           중앙 정렬이라 화면 전체로 보면 살짝 오른쪽으로 치우쳐 보인다. 아예 숨긴다. */
        [data-testid="stSidebar"] { display: none; }
        button[data-testid="stBaseButton-primaryFormSubmit"] {
            background-color: var(--brand, #00DC64) !important;
            border-color: var(--brand, #00DC64) !important;
        }
        button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
            background-color: var(--brand-deep, #00A94C) !important;
            border-color: var(--brand-deep, #00A94C) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("#### 네이버웹툰 대만 · 먼슬리 크리에이티브 리포트")
    st.caption("내부 공유용 대시보드입니다. 비밀번호를 입력하세요.")
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
