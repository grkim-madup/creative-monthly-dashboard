import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_ads_report import (  # noqa: E402
    DEFAULT_COST_MARKUP,
    aggregate_google,
    creative_assets,
    load_google_ads_folder,
    parse_meta_from_path,
    parse_period_month,
    read_asset_report,
)

AOS_HEADER = (
    "애셋 상태\t확장 소재\t상태\t애셋 유형\t실적\t방향\t클릭수\t클릭률(CTR)\t노출수\t"
    "모든 전환 가치\t통화 코드\t비용\t평균 CPC\t설치\t비용/설치\t인앱 액션\t비용/인앱 액션\t"
    "전환율(설치)\t전환율(인앱 액션)\t\"(1,000회) 노출당 설치 수\""
)
IOS_HEADER = (
    "애셋 상태\t확장 소재\t상태\t애셋 유형\t실적\t애셋 이름\t\"(1,000회) 노출당 설치 수\"\t"
    "노출수\t클릭수\t통화 코드\t비용\t설치\t비용/설치\t인앱 액션\t전환율(설치)\t"
    "전환율(인앱 액션)\t비용/인앱 액션\t모든 전환"
)


def _write(tmp_path: Path, folder: str, name: str, header: str, rows: list[str]) -> Path:
    directory = tmp_path / folder
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    body = "\n".join(
        ["애셋 세부정보 보고서", "2026년 7월 1일 - 2026년 7월 31일", header, *rows]
    )
    path.write_bytes(body.encode("utf-16"))  # 실제 파일이 UTF-16이다
    return path


def _aos_file(tmp_path: Path) -> Path:
    return _write(
        tmp_path, "AOS ACa", "AOS ACa Coin 캠페인_도굴왕.csv", AOS_HEADER,
        [
            "사용 설정됨\thttps://www.youtube.com/watch?v=abc123\t사용 가능\tYouTube 동영상\t"
            "인기순\t세로\t340\t0.53%\t\"64,468\"\t1026.00\tKRW\t141045\t415\t23.00\t6132\t"
            "\"1,333\"\t106\t6.76%\t4.10%\t3.18",
            "사용 설정됨\t설명 텍스트입니다\t사용 가능\t설명\t인기순\t --\t10\t1.00%\t"
            "\"1,000\"\t0.00\tKRW\t5000\t500\t1.00\t5000\t0\t0\t0%\t0%\t0",
        ],
    )


def test_parse_period_month():
    assert parse_period_month("2026년 7월 1일 - 2026년 7월 31일") == 7
    assert parse_period_month("기간 없음") is None


def test_parse_meta_from_path_reads_os_objective_and_title(tmp_path):
    meta = parse_meta_from_path(Path("AOS ACa/AOS ACa Read 여성향 캠페인_녹음의 관.csv"))
    assert meta["os"] == "AOS"
    assert meta["objective"] == "ACa (액션)"
    assert meta["title_kr"] == "녹음의 관"
    assert meta["segment"] == "여성향"

    meta = parse_meta_from_path(Path("iOS ACi 캠페인/IOS ACi 여성향 캠페인_클래스메이트.csv"))
    assert meta["os"] == "iOS"
    assert meta["objective"] == "ACi (설치)"


def test_read_asset_report_parses_utf16_and_third_row_header(tmp_path):
    df = read_asset_report(_aos_file(tmp_path))
    assert len(df) == 2
    row = df.iloc[0]
    assert row["asset"] == "https://www.youtube.com/watch?v=abc123"
    assert row["impression"] == pytest.approx(64468)
    assert row["click"] == pytest.approx(340)
    assert row["cost"] == pytest.approx(141045)
    assert row["total install"] == pytest.approx(23)
    assert row["in_app_action"] == pytest.approx(1333)
    assert row["direction"] == "세로"
    assert row["month"] == 7
    assert row["os"] == "AOS"
    assert row["title_kr"] == "도굴왕"


def test_ios_direction_falls_back_to_size_in_asset_name(tmp_path):
    path = _write(
        tmp_path, "iOS ACa coin 캠페인", "iOS ACa coin 캠페인_벙커의 낮.csv", IOS_HEADER,
        [
            "사용 설정됨\thttps://tpc.googlesyndication.com/simgad/99\t사용 가능\t이미지\t"
            "학습\t1200x1500_2026-05-15.jpg\t0.00\t193\t0\tKRW\t0\t0.00\t0\t0.00\t --\t --\t0\t0.00",
        ],
    )
    df = read_asset_report(path)
    assert df.loc[0, "direction"] == "세로"  # 1200x1500 → 세로
    assert df.loc[0, "os"] == "iOS"


def test_aos_file_without_asset_name_column_does_not_crash(tmp_path):
    df = read_asset_report(_aos_file(tmp_path))
    assert df["direction"].tolist() == ["세로", None]


def test_creative_assets_drops_text_assets(tmp_path):
    df = read_asset_report(_aos_file(tmp_path))
    assert len(creative_assets(df)) == 1
    assert creative_assets(df).loc[0, "asset_type"] == "YouTube 동영상"


def test_load_folder_applies_cost_markup(tmp_path):
    _aos_file(tmp_path)
    df = load_google_ads_folder(tmp_path)
    row = df[df["asset_type"] == "YouTube 동영상"].iloc[0]
    assert row["cost_raw"] == pytest.approx(141045)
    assert row["cost"] == pytest.approx(141045 * DEFAULT_COST_MARKUP)
    # 시트의 'cost (마크업 포함)' 값과 맞아야 한다.
    assert round(row["cost"]) == 152752


def test_load_folder_reports_unreadable_files_instead_of_hiding_them(tmp_path):
    _aos_file(tmp_path)
    (tmp_path / "AOS ACa" / "broken.csv").write_bytes(b"\x00\x01")
    df = load_google_ads_folder(tmp_path)
    assert not df.empty  # 정상 파일은 그대로 읽힌다


def test_load_folder_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_google_ads_folder(tmp_path / "없는폴더")


def test_aggregate_google_recomputes_ratios_from_sums(tmp_path):
    _aos_file(tmp_path)
    df = creative_assets(load_google_ads_folder(tmp_path, cost_markup=1.0))
    agg = aggregate_google(df, ["direction"])
    row = agg.iloc[0]
    assert row["CTR"] == pytest.approx(340 / 64468)
    assert row["CPI"] == pytest.approx(141045 / 23)
    assert row["인앱 CPA"] == pytest.approx(141045 / 1333)
