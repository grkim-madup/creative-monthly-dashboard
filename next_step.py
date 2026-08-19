"""리포트 하단 'NEXT STEP' 자유 편집 영역.

대시보드 안에서 직접 글을 쓰고, 레퍼런스 이미지를 붙이고, 표를 넣을 수 있게 한다.
내용은 **월별로 디스크에 저장**한다 — 세션 상태에만 두면 새로고침이나 서버 재시작에 날아간다.

저장 위치: `notes/next_step_<월>.json` (이미지는 `notes/images/`)
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

NOTES_DIR = Path(__file__).resolve().parent / "notes"
IMAGES_DIR = NOTES_DIR / "images"

# image_max_height: 미리보기에서 이미지 높이 상한(px). 대시보드에서 직접 조절한다.
DEFAULT_IMAGE_MAX_HEIGHT = 420
EMPTY_NOTE: dict = {
    "markdown": "",
    "images": [],
    "tables": [],
    "image_max_height": DEFAULT_IMAGE_MAX_HEIGHT,
    "updated_at": None,
}


def note_path(month: int, kind: str = "next_step") -> Path:
    """kind로 노트 종류를 가른다 — NEXT STEP과 제작 인사이트가 각각 따로 저장된다."""
    return NOTES_DIR / f"{kind}_{int(month)}.json"


def load_note(month: int, kind: str = "next_step") -> dict:
    """저장된 노트를 읽는다. 파일이 없거나 깨져 있으면 빈 노트를 돌려준다."""
    path = note_path(month, kind)
    if not path.exists():
        return dict(EMPTY_NOTE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(EMPTY_NOTE)
    note = dict(EMPTY_NOTE)
    note.update({k: v for k, v in data.items() if k in EMPTY_NOTE})
    return note


def save_note(month: int, note: dict, kind: str = "next_step") -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(EMPTY_NOTE)
    payload.update({k: v for k, v in note.items() if k in EMPTY_NOTE})
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = note_path(month, kind)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _safe_name(name: str) -> str:
    """파일명에 쓸 수 없는 문자를 걷어낸다(경로 탈출 방지 포함)."""
    cleaned = re.sub(r"[^\w.\-가-힣]", "_", Path(str(name)).name)
    return cleaned or "image"


def save_image(month: int, filename: str, data: bytes) -> str:
    """업로드 이미지를 저장하고 저장된 파일명을 돌려준다."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    stored = f"{int(month)}_{stamp}_{_safe_name(filename)}"
    (IMAGES_DIR / stored).write_bytes(data)
    return stored


def image_path(stored_name: str) -> Path:
    return IMAGES_DIR / stored_name


def delete_image(stored_name: str) -> None:
    target = image_path(stored_name)
    if target.exists():
        target.unlink()


def to_preview_html(content: str) -> str:
    """저장된 본문을 미리보기용 HTML로 만든다.

    에디터(Quill)는 HTML을 주지만, 예전에 `text_area`로 저장한 노트는 순수 텍스트다.
    그대로 HTML에 넣으면 줄바꿈이 통째로 무시돼 한 줄로 붙어버리므로 구분해서 처리한다.
    """
    text = (content or "").strip()
    if not text:
        return ""
    looks_like_html = text.startswith("<") or "</p>" in text or "<br" in text
    if looks_like_html:
        return text

    escaped = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return "<br>".join(escaped.splitlines())


def image_data_uri(stored_name: str) -> str:
    """이미지를 data URI로 바꾼다. HTML로 직접 렌더해야 CSS(높이 상한)를 걸 수 있다."""
    path = image_path(stored_name)
    if not path.exists():
        return ""
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def parse_pasted_table(text: str) -> pd.DataFrame:
    """엑셀·시트에서 복사한 내용을 표로 바꾼다.

    탭 구분(스프레드시트 복사)과 쉼표 구분을 자동으로 가려낸다. 첫 줄은 헤더로 본다.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return pd.DataFrame()

    first_line = cleaned.splitlines()[0]
    delimiter = "\t" if first_line.count("\t") >= first_line.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(cleaned), delimiter=delimiter) if any(r)]
    if not rows:
        return pd.DataFrame()

    header, *body = rows
    header = [h.strip() or f"열{i + 1}" for i, h in enumerate(header)]
    width = len(header)
    body = [(r + [""] * width)[:width] for r in body]
    return pd.DataFrame(body, columns=header)
