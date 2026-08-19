import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import next_step  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """실제 notes/ 폴더를 건드리지 않도록 임시 경로로 갈아끼운다."""
    monkeypatch.setattr(next_step, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(next_step, "IMAGES_DIR", tmp_path / "notes" / "images")


def test_load_returns_empty_note_when_file_missing():
    note = next_step.load_note(7)
    assert note["markdown"] == ""
    assert note["images"] == [] and note["tables"] == []


def test_save_then_load_roundtrip():
    next_step.save_note(7, {"markdown": "다음 달엔 6초 컷다운 비중 확대", "tables": [], "images": []})
    note = next_step.load_note(7)
    assert note["markdown"] == "다음 달엔 6초 컷다운 비중 확대"
    assert note["updated_at"]


def test_notes_are_kept_per_month():
    next_step.save_note(7, {"markdown": "7월 노트"})
    next_step.save_note(8, {"markdown": "8월 노트"})
    assert next_step.load_note(7)["markdown"] == "7월 노트"
    assert next_step.load_note(8)["markdown"] == "8월 노트"


def test_kinds_are_stored_separately():
    """NEXT STEP과 제작 인사이트는 같은 달이어도 서로 덮어쓰면 안 된다."""
    next_step.save_note(7, {"markdown": "다음 달 액션"})
    next_step.save_note(7, {"markdown": "7월 제작 인사이트"}, kind="insight")
    assert next_step.load_note(7)["markdown"] == "다음 달 액션"
    assert next_step.load_note(7, kind="insight")["markdown"] == "7월 제작 인사이트"


def test_unknown_kind_loads_empty_note():
    assert next_step.load_note(7, kind="insight")["markdown"] == ""


def test_corrupted_file_falls_back_to_empty_note():
    next_step.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    next_step.note_path(7).write_text("{깨진 json", encoding="utf-8")
    assert next_step.load_note(7)["markdown"] == ""


def test_unknown_keys_are_not_persisted():
    next_step.save_note(7, {"markdown": "x", "쓸데없는키": "y"})
    assert "쓸데없는키" not in next_step.load_note(7)


def test_save_image_stores_bytes_and_returns_name():
    stored = next_step.save_image(7, "레퍼런스.png", b"\x89PNG-data")
    assert next_step.image_path(stored).read_bytes() == b"\x89PNG-data"
    assert stored.startswith("7_") and stored.endswith("레퍼런스.png")


def test_save_image_strips_path_traversal():
    stored = next_step.save_image(7, "../../evil.png", b"x")
    assert "/" not in stored and "\\" not in stored
    assert next_step.image_path(stored).exists()


def test_delete_image_is_safe_when_missing():
    next_step.delete_image("없는파일.png")  # 예외 없이 지나가야 한다


def test_parse_pasted_table_handles_tab_separated():
    df = next_step.parse_pasted_table("소재\t소진액\nA\t1000\nB\t2000")
    assert list(df.columns) == ["소재", "소진액"]
    assert df.shape == (2, 2)
    assert df.iloc[1]["소진액"] == "2000"


def test_parse_pasted_table_handles_comma_separated():
    df = next_step.parse_pasted_table("소재,소진액\nA,1000")
    assert list(df.columns) == ["소재", "소진액"]
    assert len(df) == 1


def test_parse_pasted_table_pads_short_rows():
    df = next_step.parse_pasted_table("a\tb\tc\n1\t2")
    assert df.shape == (1, 3)
    assert df.iloc[0]["c"] == ""


def test_parse_pasted_table_names_blank_headers():
    df = next_step.parse_pasted_table("소재\t\nA\t1")
    assert list(df.columns) == ["소재", "열2"]


def test_parse_pasted_table_empty_input():
    assert next_step.parse_pasted_table("   ").empty


def test_preview_keeps_editor_html_as_is():
    html = "<p>다음 달 <strong>USP</strong></p><ul><li>배너</li></ul>"
    assert next_step.to_preview_html(html) == html


def test_preview_converts_plain_text_newlines_to_br():
    """예전 text_area로 저장한 노트는 순수 텍스트라 <br>로 바꿔야 줄이 살아난다."""
    out = next_step.to_preview_html("다음 달 신규 제작 USP\n- COMIC 형 배너 소재 제작")
    assert "<br>" in out
    assert out.count("<br>") == 1


def test_preview_escapes_html_in_plain_text():
    out = next_step.to_preview_html("a < b & c")
    assert "&lt;" in out and "&amp;" in out


def test_preview_empty_input():
    assert next_step.to_preview_html("   ") == ""


def test_note_carries_adjustable_image_max_height():
    assert next_step.load_note(7)["image_max_height"] == next_step.DEFAULT_IMAGE_MAX_HEIGHT
    next_step.save_note(7, {"markdown": "x", "image_max_height": 700})
    assert next_step.load_note(7)["image_max_height"] == 700


def test_image_data_uri_roundtrip():
    stored = next_step.save_image(7, "ref.png", b"\x89PNG-bytes")
    uri = next_step.image_data_uri(stored)
    assert uri.startswith("data:image/png;base64,")


def test_image_data_uri_maps_jpg_to_jpeg_mime():
    stored = next_step.save_image(7, "ref.jpg", b"jpg-bytes")
    assert next_step.image_data_uri(stored).startswith("data:image/jpeg;base64,")


def test_image_data_uri_missing_file_returns_empty():
    assert next_step.image_data_uri("없는파일.png") == ""
