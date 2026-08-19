"""구글 광고 애셋 리포트의 월별 스냅샷(고정) 저장소.

담당자가 드롭박스 폴더를 다음 달 데이터로 덮어쓰면, 실시간 연동 구조상 지난 달 숫자가
그대로 사라진다(CLAUDE.md에 이미 기록된 알려진 위험 — "과거 월을 다시 보려면 월별로
하위 폴더를 두는 편이 안전하다"). 리포트 히스토리를 남기려면 그 달이 끝나는 시점의
값을 별도로 얼려 둬야 한다.

정책:
- 최신 달(리포트 월 선택지의 마지막 값)은 아직 진행 중이라 항상 실시간 값을 쓴다.
- 최신이 아닌 달은 스냅샷이 있으면 반드시 스냅샷만 쓴다 — 라이브 폴더에 그 달 파일이
  우연히 남아있어도 무시한다. 한 번 고정되면 그 이후로 절대 안 바뀌는 게 이 기능의 목적이다.
- 스냅샷이 아직 없는 지난 달을 처음 열면, 그 순간의 라이브 값으로 자동 고정한다(지연
  평가 방식의 "월이 지나면 자동 고정"). 라이브 폴더에 이미 그 달 데이터가 없으면(담당자가
  이미 다음 달 파일로 덮어씀) 고정할 게 없으므로 건너뛴다 — 이 경우는 이미 늦은 것이다.
- 사용자가 "지금 시점으로 고정" 버튼을 누르면 최신 달이라도 그 시점 값을 강제로 얼릴 수
  있다(다음 달로 넘어가기 전에 미리 확정해 두고 싶을 때).

저장 형식: 원본 CSV 폴더 구조를 그대로 복사한다. 별도 집계 포맷을 새로 만들면 스냅샷과
실시간 경로의 파싱 결과가 어긋날 위험이 있어, 같은 `google_ads_report.load_google_ads_folder`
로직을 두 경우 모두 그대로 재사용하게 한다.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).resolve().parent / "notes" / "google_snapshots"
_STAMP_FILE = "_frozen_at.txt"


def path(month: int) -> Path:
    return SNAPSHOT_DIR / str(int(month))


def exists(month: int) -> bool:
    p = path(month)
    return p.exists() and any(p.rglob("*.csv"))


def frozen_at(month: int) -> str | None:
    """이 달이 고정된 시각(문자열). 아직 안 고정됐으면 None."""
    stamp = path(month) / _STAMP_FILE
    return stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None


def save(month: int, source_dir: Path | str) -> None:
    """`source_dir`(현재 라이브 폴더)의 내용을 이 달 스냅샷으로 통째로 복사해 고정한다.

    이미 스냅샷이 있으면 지우고 새로 뜬다 — 명시적 재고정 버튼도 같은 함수를 쓴다.
    """
    dest = path(month)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, dest, dirs_exist_ok=True)
    (dest / _STAMP_FILE).write_text(
        dt.datetime.now().strftime("%Y-%m-%d %H:%M"), encoding="utf-8"
    )
