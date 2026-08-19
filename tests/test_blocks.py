import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import blocks  # noqa: E402
import next_step  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, "BLOCKS_DIR", tmp_path / "notes")
    monkeypatch.setattr(next_step, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(next_step, "IMAGES_DIR", tmp_path / "notes" / "images")


def test_load_returns_empty_slots_when_missing():
    data = blocks.load_blocks(7)
    assert data == {blocks.SLOT_ANALYSIS: [], blocks.SLOT_NEXT_STEP: []}


def test_add_block_returns_unique_ids():
    data = blocks.empty_blocks()
    first = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "TEXT 유형")
    second = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "SNS 유형")
    assert first != second
    assert [b["title"] for b in data[blocks.SLOT_ANALYSIS]] == ["TEXT 유형", "SNS 유형"]


def test_new_query_block_has_expected_shape():
    data = blocks.empty_blocks()
    block_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    block = blocks.find_block(data, blocks.SLOT_ANALYSIS, block_id)
    assert block["type"] == "creative_query"
    assert block["conditions"] == {} and block["comment"] == ""
    assert block["show_table"] is True


def test_add_block_inserts_at_position():
    data = blocks.empty_blocks()
    first = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "1")
    third = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "3")
    blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "2", position=1)
    assert [b["title"] for b in data[blocks.SLOT_ANALYSIS]] == ["1", "2", "3"]
    assert data[blocks.SLOT_ANALYSIS][0]["id"] == first
    assert data[blocks.SLOT_ANALYSIS][2]["id"] == third


def test_add_block_position_past_end_appends():
    data = blocks.empty_blocks()
    blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "1")
    blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "2", position=99)
    assert [b["title"] for b in data[blocks.SLOT_ANALYSIS]] == ["1", "2"]


def test_remove_block():
    data = blocks.empty_blocks()
    block_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    blocks.remove_block(data, blocks.SLOT_ANALYSIS, block_id)
    assert data[blocks.SLOT_ANALYSIS] == []


def test_remove_unknown_block_is_safe():
    data = blocks.empty_blocks()
    blocks.remove_block(data, blocks.SLOT_ANALYSIS, "nope")


def test_move_block_up_and_down():
    data = blocks.empty_blocks()
    first = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "1")
    second = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "2")
    blocks.move_block(data, blocks.SLOT_ANALYSIS, second, -1)
    assert [b["id"] for b in data[blocks.SLOT_ANALYSIS]] == [second, first]
    blocks.move_block(data, blocks.SLOT_ANALYSIS, second, 1)
    assert [b["id"] for b in data[blocks.SLOT_ANALYSIS]] == [first, second]


def test_move_block_at_boundary_does_nothing():
    data = blocks.empty_blocks()
    first = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    blocks.move_block(data, blocks.SLOT_ANALYSIS, first, -1)
    assert [b["id"] for b in data[blocks.SLOT_ANALYSIS]] == [first]


def test_update_block_only_writes_known_fields():
    data = blocks.empty_blocks()
    block_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    blocks.update_block(
        data, blocks.SLOT_ANALYSIS, block_id,
        title="TEXT", conditions={"extra_info_tag": ["text"]}, 쓸데없는키="x",
    )
    block = blocks.find_block(data, blocks.SLOT_ANALYSIS, block_id)
    assert block["title"] == "TEXT"
    assert block["conditions"] == {"extra_info_tag": ["text"]}
    assert "쓸데없는키" not in block


def test_slots_do_not_interfere():
    data = blocks.empty_blocks()
    blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    blocks.add_block(data, blocks.SLOT_NEXT_STEP, "note")
    assert len(data[blocks.SLOT_ANALYSIS]) == 1
    assert len(data[blocks.SLOT_NEXT_STEP]) == 1


def test_months_are_stored_separately():
    july = blocks.empty_blocks()
    blocks.add_block(july, blocks.SLOT_ANALYSIS, "creative_query", "7월 블록")
    blocks.save_blocks(7, july)
    assert blocks.load_blocks(8)[blocks.SLOT_ANALYSIS] == []
    assert blocks.load_blocks(7)[blocks.SLOT_ANALYSIS][0]["title"] == "7월 블록"


def test_corrupted_file_falls_back_to_empty_slots():
    blocks.BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    blocks.blocks_path(7).write_text("{깨진 json", encoding="utf-8")
    assert blocks.load_blocks(7) == {blocks.SLOT_ANALYSIS: [], blocks.SLOT_NEXT_STEP: []}


def test_legacy_insight_note_becomes_analysis_block():
    next_step.save_note(7, {"markdown": "<p>인사이트 원문</p>"}, kind="insight")
    data = blocks.load_blocks(7)
    block = data[blocks.SLOT_ANALYSIS][0]
    assert block["comment"] == "<p>인사이트 원문</p>"
    assert block["title"] == "제작 인사이트"
    assert block["show_table"] is False


def test_legacy_next_step_note_becomes_note_block():
    next_step.save_note(7, {"markdown": "<p>다음 달</p>", "image_max_height": 300})
    data = blocks.load_blocks(7)
    block = data[blocks.SLOT_NEXT_STEP][0]
    assert block["type"] == "note"
    assert block["comment"] == "<p>다음 달</p>"
    assert block["image_max_height"] == 300


def test_blocks_do_not_share_default_mutable_state():
    """같은 타입 블록끼리 conditions/images 객체를 공유하면 안 된다 (얕은 복사 회귀 방지)."""
    data = blocks.empty_blocks()
    first_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    second_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query")
    first = blocks.find_block(data, blocks.SLOT_ANALYSIS, first_id)
    second = blocks.find_block(data, blocks.SLOT_ANALYSIS, second_id)
    first["conditions"]["extra_info_tag"] = ["text"]
    assert second["conditions"] == {}

    note_first_id = blocks.add_block(data, blocks.SLOT_NEXT_STEP, "note")
    note_second_id = blocks.add_block(data, blocks.SLOT_NEXT_STEP, "note")
    note_first = blocks.find_block(data, blocks.SLOT_NEXT_STEP, note_first_id)
    note_second = blocks.find_block(data, blocks.SLOT_NEXT_STEP, note_second_id)
    note_first["images"].append("img1.png")
    assert note_second["images"] == []


def test_mutate_does_not_revert_another_session_save():
    """A가 화면을 연 뒤 B가 자기 블록을 저장해도, A의 저장이 B의 글을 되돌리면 안 된다."""
    data = blocks.empty_blocks()
    a_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "A 블록")
    b_id = blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "B 블록")
    blocks.save_blocks(7, data)

    stale = blocks.load_blocks(7)  # A가 화면을 열 때 읽은 스냅샷

    # B가 먼저 저장
    blocks.mutate(7, lambda d: blocks.update_block(
        d, blocks.SLOT_ANALYSIS, b_id, comment="B가 쓴 글"))

    # A가 나중에 저장 — 자기 블록만 바뀌어야 한다
    blocks.mutate(7, lambda d: blocks.update_block(
        d, blocks.SLOT_ANALYSIS, a_id, comment="A가 쓴 글"))

    saved = blocks.load_blocks(7)
    assert blocks.find_block(saved, blocks.SLOT_ANALYSIS, a_id)["comment"] == "A가 쓴 글"
    assert blocks.find_block(saved, blocks.SLOT_ANALYSIS, b_id)["comment"] == "B가 쓴 글"
    # 스냅샷은 그대로 낡은 상태여야 한다(mutate가 이걸 쓰지 않았다는 확인)
    assert blocks.find_block(stale, blocks.SLOT_ANALYSIS, b_id)["comment"] == ""


def test_mutate_returns_fresh_state():
    blocks.save_blocks(7, blocks.empty_blocks())
    result = blocks.mutate(7, lambda d: blocks.add_block(
        d, blocks.SLOT_ANALYSIS, "creative_query", "새 블록"))
    assert [b["title"] for b in result[blocks.SLOT_ANALYSIS]] == ["새 블록"]


def test_save_blocks_leaves_no_temp_file():
    blocks.save_blocks(7, blocks.empty_blocks())
    assert list(blocks.BLOCKS_DIR.glob("*.tmp")) == []


def test_save_blocks_replaces_atomically():
    """임시 파일에 쓰다 끊겨도 기존 파일은 온전해야 한다."""
    data = blocks.empty_blocks()
    blocks.add_block(data, blocks.SLOT_ANALYSIS, "creative_query", "원본")
    blocks.save_blocks(7, data)

    def boom(self, *args, **kwargs):
        raise OSError("디스크 가득 참")

    # 별도 MonkeyPatch 컨텍스트를 쓴다 — 픽스처와 같은 monkeypatch 인스턴스에 undo를 부르면
    # BLOCKS_DIR 격리까지 함께 풀려서 실제 notes 폴더를 읽게 된다.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "write_text", boom)
        with pytest.raises(OSError):
            blocks.save_blocks(7, blocks.empty_blocks())
    assert blocks.load_blocks(7)[blocks.SLOT_ANALYSIS][0]["title"] == "원본"


def test_corrupted_file_is_quarantined_not_overwritten():
    blocks.BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    blocks.blocks_path(7).write_text('{"analysis": [깨짐', encoding="utf-8")

    assert blocks.load_blocks(7) == blocks.empty_blocks()

    quarantined = list(blocks.BLOCKS_DIR.glob("blocks_7.corrupt-*.json"))
    assert len(quarantined) == 1
    assert "깨짐" in quarantined[0].read_text(encoding="utf-8")
    # 대시보드가 화면에 알릴 수 있도록 한 번만 꺼내진다
    assert blocks.pop_corruption(7) == str(quarantined[0])
    assert blocks.pop_corruption(7) is None


def test_legacy_note_with_only_attachments_is_migrated():
    """본문 없이 이미지·표만 있는 예전 노트도 이관돼야 한다(놓치면 되돌릴 기회가 없다)."""
    next_step.save_note(7, {"markdown": "", "images": ["7_1_a.png"], "tables": ["a\tb"]})
    data = blocks.load_blocks(7)
    assert len(data[blocks.SLOT_NEXT_STEP]) == 1
    block = data[blocks.SLOT_NEXT_STEP][0]
    assert block["images"] == ["7_1_a.png"]
    assert block["tables"] == ["a\tb"]


def test_truly_empty_legacy_notes_are_not_migrated():
    assert blocks.migrate_legacy_notes(7) is None


def test_migration_runs_only_once():
    next_step.save_note(7, {"markdown": "<p>인사이트</p>"}, kind="insight")
    blocks.load_blocks(7)
    blocks.load_blocks(7)
    assert len(blocks.load_blocks(7)[blocks.SLOT_ANALYSIS]) == 1
