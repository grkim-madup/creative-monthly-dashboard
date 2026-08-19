import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_data import (  # noqa: E402
    find_google_blocks,
    load_google_creatives,
    normalize_google_block,
    youtube_id,
)

U1 = "https://www.youtube.com/watch?v=kvCMdANbai0"
U2 = "https://www.youtube.com/watch?v=aU3YQHf07jY"


def _sheet():
    """실제 리포트 탭 구조를 축소 재현: 앞에 소제목 행, 왼쪽 빈 컬럼, AOS/iOS 블록."""
    return [
        ["", "* 구글 AOS", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],
        ["", "확장 소재", "매체명", "실적", "cost (마크업 포함)", "impression", "click"],
        ["", U1, "Google", "인기순", "152,752", "64,468", "340"],
        ["", U2, "Google", "낮음", "64,681", "28,022", "162"],
        ["", "", "", "", "", "", ""],
        ["■ 틱톡/메타 iOS - total install 기준 top10 소재", "", "", "", "", "", ""],
        ["ad", "cost (마크업 포함)", "impression", "click", "매체 Install", "", ""],
        [U1, "10,000", "5,000", "50", "5", "", ""],
    ]


def test_find_google_blocks_detects_both_blocks():
    blocks = find_google_blocks(_sheet())
    assert len(blocks) == 2
    assert len(blocks[0]) == 2
    assert len(blocks[1]) == 1


def test_block_columns_start_at_url_column_not_sheet_column_a():
    blocks = find_google_blocks(_sheet())
    assert list(blocks[0].columns)[0] == "확장 소재"


def test_ignores_url_rows_without_a_findable_header():
    values = [["", ""], [U1, "123"]]
    assert find_google_blocks(values) == []


def test_normalize_recomputes_ratios_instead_of_trusting_pasted_values():
    block = find_google_blocks(_sheet())[0]
    out = normalize_google_block(block)
    assert out.loc[0, "ad"] == U1
    assert out.loc[0, "cost"] == pytest.approx(152752)
    assert out.loc[0, "impression"] == pytest.approx(64468)
    assert out.loc[0, "CTR"] == pytest.approx(340 / 64468)
    assert out.loc[0, "CPC"] == pytest.approx(152752 / 340)
    assert out.loc[0, "media"] == "Google"
    assert out.loc[0, "rating"] == "인기순"


def test_blocks_are_tagged_with_their_os_heading():
    blocks = find_google_blocks(_sheet())
    assert blocks[0].attrs["os"] == "AOS"
    assert blocks[1].attrs["os"] == "iOS"


def test_load_google_creatives_sums_across_os():
    out = load_google_creatives(_sheet())
    row = out[out["ad"] == U1].iloc[0]
    assert row["cost"] == pytest.approx(152752 + 10000)
    assert row["impression"] == pytest.approx(64468 + 5000)
    assert row["click"] == pytest.approx(340 + 50)
    # 합산 후 비율도 다시 계산돼야 한다.
    assert row["CTR"] == pytest.approx(390 / 69468)


def test_duplicate_url_within_one_os_is_not_double_counted():
    """같은 OS 안에서 install TOP10과 coin TOP10에 같은 소재가 겹쳐도 소진액이 부풀지 않아야 한다."""
    sheet = [
        ["* 구글 AOS - total install 기준", "", "", ""],
        ["ad", "cost (마크업 포함)", "impression", "click"],
        [U1, "100,000", "50,000", "500"],
        ["", "", "", ""],
        ["* 구글 AOS - D0 coin 기준", "", "", ""],
        ["ad", "cost (마크업 포함)", "impression", "click"],
        [U1, "100,000", "50,000", "500"],
    ]
    out = load_google_creatives(sheet)
    assert len(out) == 1
    assert out.loc[0, "cost"] == pytest.approx(100_000)
    assert out.loc[0, "impression"] == pytest.approx(50_000)


def test_load_google_creatives_empty_when_no_google_data():
    assert load_google_creatives([["월", "매체명"], ["7", "TikTok"]]).empty


def test_youtube_id():
    assert youtube_id(U1) == "kvCMdANbai0"
    assert youtube_id("https://youtu.be/abc123XY") == "abc123XY"
    assert youtube_id("소재명_아님") is None
