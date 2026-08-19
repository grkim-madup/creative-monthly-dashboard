"""구글 광고 애셋 리포트의 월별 스냅샷(고정) 저장소.

담당자가 드롭박스 폴더를 다음 달 데이터로 덮어쓰면, 실시간 연동 구조상 지난 달 숫자가
그대로 사라진다(CLAUDE.md에 이미 기록된 알려진 위험 — "과거 월을 다시 보려면 월별로
하위 폴더를 두는 편이 안전하다"). 리포트 히스토리를 남기려면 그 달이 끝나는 시점의
값을 별도로 얼려 둬야 한다.

정책:
- 스냅샷이 있는 달은 무조건 스냅샷만 쓴다 — 라이브 폴더에 그 달 파일이 남아있어도 무시한다.
  한 번 고정되면 그 이후로 절대 안 바뀌는 게 이 기능의 목적이다.
- 자동 고정은 하지 않는다(2026-08-20 결정) — 오직 "지금 시점으로 고정" 버튼을 눌렀을
  때만 얼린다. 스냅샷이 없는 달은 그냥 계속 라이브 값을 보여준다.
- 사용자가 버튼을 누르면 그 시점 값을 얼린다(최신 달이든 지난 달이든 상관없다). 이미
  고정된 달을 다시 누르면 그 시점 값으로 재고정된다.

저장 백엔드는 두 가지이고, `google_sheets_writer.configured()`로 자동 선택된다:
- **구글시트 스냅샷 탭** (설정돼 있으면 우선) — 이 시트 하나에만 공유된 서비스 계정으로
  쓴다. Streamlit Cloud처럼 재시작하면 로컬 디스크가 초기화되는 배포 환경에서도 이력이
  남는다. 원가(마크업 적용 전)로 저장하고, 읽을 때 현재 마크업을 곱한다.
- **로컬 폴더 복사** (서비스 계정 미설정 시 폴백, 로컬 개발용) — 원본 CSV 폴더 구조를
  그대로 복사한다. 재시작하면 사라질 수 있어 배포 환경에는 권장하지 않는다.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pandas as pd

import google_sheets_writer
from google_ads_report import load_google_ads_folder

SNAPSHOT_DIR = Path(__file__).resolve().parent / "notes" / "google_snapshots"
_STAMP_FILE = "_frozen_at.txt"


def path(month: int) -> Path:
    """로컬 폴더 백엔드에서 이 달 스냅샷이 저장되는 경로."""
    return SNAPSHOT_DIR / str(int(month))


def exists(month: int) -> bool:
    if google_sheets_writer.configured():
        return google_sheets_writer.month_exists(month)
    p = path(month)
    return p.exists() and any(p.rglob("*.csv"))


def frozen_at(month: int) -> str | None:
    """이 달이 고정된 시각(문자열). 아직 안 고정됐으면 None."""
    if google_sheets_writer.configured():
        return google_sheets_writer.frozen_at(month)
    stamp = path(month) / _STAMP_FILE
    return stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None


def source_label(month: int) -> str:
    """사이드바 도움말에 보여줄 "어디서 읽었는지" 문구."""
    if google_sheets_writer.configured():
        return f"구글시트 스냅샷 탭 (snapshot_{int(month)})"
    return str(path(month))


def save(month: int, live_folder: Path | str) -> None:
    """`live_folder`(현재 라이브 드롭박스/로컬 폴더)의 이 달 값을 스냅샷으로 고정한다.

    이미 스냅샷이 있으면 덮어쓴다 — 명시적 재고정 버튼도 같은 함수를 쓴다.
    """
    if google_sheets_writer.configured():
        df = load_google_ads_folder(live_folder, cost_markup=1.0)
        df = df[df["month"] == month] if not df.empty else df
        if df.empty:
            raise RuntimeError(
                f"라이브 폴더에 {month}월 데이터가 없어 고정할 수 없습니다: {live_folder}"
            )
        google_sheets_writer.write_month(month, df)
        return

    dest = path(month)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(live_folder, dest, dirs_exist_ok=True)
    (dest / _STAMP_FILE).write_text(
        dt.datetime.now().strftime("%Y-%m-%d %H:%M"), encoding="utf-8"
    )


def load(month: int, cost_markup: float) -> pd.DataFrame:
    """이 달 스냅샷을 현재 마크업이 반영된 최종 DataFrame으로 돌려준다.

    호출 전 `exists(month)`가 True인지 확인해야 한다. 원가를 저장해 두고 여기서
    마크업을 곱하므로, 라이브 경로와 마찬가지로 마크업 슬라이더를 바꾸면 값이 따라
    바뀐다 — 고정되는 건 원본 수치이지 그 시점의 마크업 계산 결과가 아니다.
    """
    if google_sheets_writer.configured():
        df = google_sheets_writer.read_month(month)
        if df is None:
            raise RuntimeError(f"{month}월 스냅샷 탭을 찾을 수 없습니다.")
        df = df.copy()
        df["cost"] = df["cost_raw"] * cost_markup
        return df

    df = load_google_ads_folder(path(month), cost_markup=cost_markup)
    return df[df["month"] == month] if not df.empty else df
