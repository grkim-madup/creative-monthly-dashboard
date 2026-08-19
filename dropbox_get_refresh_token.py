"""Dropbox refresh token을 한 번만 발급받는 헬퍼.

배포 서버는 브라우저 로그인을 할 수 없으니, 이 스크립트를 **로컬 PC에서 딱 한 번** 실행해
refresh token을 받아두고 그 값을 배포 환경의 secrets/환경변수로 등록한다. 이후로는 다시 실행할
필요 없다(refresh token은 만료되지 않는다 — 팀에서 앱 접근을 회수하기 전까지 유효).

사전 준비 (Dropbox App Console, https://www.dropbox.com/developers/apps):
1. "Create app" → API: Scoped access, 접근 범위: "App folder"가 아니라 팀 폴더를 읽어야 하므로
   "Full Dropbox" 선택 (읽기 전용 스코프만 부여하므로 다른 파일은 건드리지 않음).
2. Permissions 탭에서 `files.metadata.read`, `files.content.read` 두 개만 체크(쓰기 권한 금지).
3. Settings 탭의 App key / App secret을 아래 입력창에 사용.

실행: python dropbox_get_refresh_token.py
"""

from __future__ import annotations

import dropbox

APP_KEY = input("App key: ").strip()
APP_SECRET = input("App secret: ").strip()

auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(
    APP_KEY, APP_SECRET, token_access_type="offline"
)
print("\n1) 아래 URL을 브라우저에서 열고 이 앱 접근을 허용하세요:")
print(auth_flow.start())
auth_code = input("\n2) 인증 후 나오는 코드를 붙여넣으세요: ").strip()

result = auth_flow.finish(auth_code)

print("\n=== 아래 값을 배포 환경의 secrets/환경변수로 등록하세요 (다시 보여주지 않습니다) ===")
print(f"DROPBOX_APP_KEY={APP_KEY}")
print(f"DROPBOX_APP_SECRET={APP_SECRET}")
print(f"DROPBOX_REFRESH_TOKEN={result.refresh_token}")
print("DROPBOX_FOLDER_PATH=/광고사업부/4. 광고주/네이버 웹툰 대만/8. 기타/구글 먼슬리 크리")
print("(팀 드롭박스 표시 이름이 아니라 실제 API 경로 기준입니다 — 다르면 대시보드 실행 후 "
      "에러 메시지의 폴더 경로로 조정하세요.)")
