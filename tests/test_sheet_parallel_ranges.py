"""행 구간 분할 — 빈틈이 생기면 소재가 조용히 사라지고, 겹치면 이중 집계된다.
두 실패 방식 모두 에러 없이 틀린 숫자를 만들기 때문에 여기서 못 박아 둔다."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_sheets_readonly import PARALLEL_CHUNKS, column_letter, row_chunks  # noqa: E402


def test_column_letter_matches_a1_notation():
    assert column_letter(1) == "A"
    assert column_letter(26) == "Z"
    assert column_letter(27) == "AA"
    assert column_letter(49) == "AW"  # 실제 Media_RAW 열 수


def test_column_letter_rejects_zero_or_negative():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            column_letter(bad)


@pytest.mark.parametrize("total", [1, 2, 5, 7, 100, 126_788, 140_001])
def test_chunks_cover_every_row_exactly_once(total):
    chunks = row_chunks(total)
    covered = []
    for start, end in chunks:
        assert start <= end
        covered.extend(range(start, end + 1))
    assert covered == list(range(1, total + 1))


def test_chunks_are_contiguous_with_no_gap_or_overlap():
    chunks = row_chunks(126_788)
    assert chunks[0][0] == 1
    assert chunks[-1][1] == 126_788
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert next_start == prev_end + 1


def test_chunk_count_never_exceeds_requested_or_row_count():
    assert len(row_chunks(126_788)) <= PARALLEL_CHUNKS
    assert len(row_chunks(3, chunks=6)) == 3  # 행보다 많이 쪼개지 않는다
    assert len(row_chunks(1)) == 1


def test_empty_sheet_yields_no_ranges():
    assert row_chunks(0) == []
    assert row_chunks(-5) == []
