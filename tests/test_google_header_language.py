# -*- coding: utf-8 -*-
"""구글 애셋 보고서는 **한글·영문 헤더를 둘 다** 읽어야 한다.

## 왜 생겼나 (2026-09-30 실측 사고)

담당자가 구글 광고 UI 언어를 바꾸면 CSV 헤더가 통째로 영문이 된다. 별칭에 한글만
있어서 **영문 파일 32개가 조용히 버려졌다** — `asset_type`·`cost`가 전부 결측이 되고
`month`가 `None`이라 모든 월 필터에서 빠졌다.

**9월 구글 애셋 소진 ₩104,234,720(실제의 66%)이 화면에서 사라져 있었다.**
에러는 나지 않았다. 이 저장소가 가장 두려워하는 "조용히 틀린 숫자"다.
"""
import io

import pandas as pd
import pytest

import google_ads_report as g


EN_HEADER = ("Asset status\tAsset\tStatus\tAsset type\tPerformance\tAsset name\t"
             "Impr.\tClicks\tCurrency code\tCost\tInstalls\tIn-app actions")
KR_HEADER = ("애셋 상태\t확장 소재\t상태\t애셋 유형\t실적\t애셋 이름\t"
             "노출수\t클릭수\t통화 코드\t비용\t설치\t인앱 액션")


def write(tmp_path, name, period, header, rows):
    """UTF-16 탭 구분 — 실제 구글 보고서와 같은 형식."""
    body = "\n".join(["Asset details report", period, header, *rows])
    path = tmp_path / name
    io.open(path, "w", encoding="utf-16").write(body)
    return path


EN_ROW = ("Enabled\thttps://www.youtube.com/watch?v=abc\tEligible\tYouTube video\t"
          "Good\t11224_勇者之歌_VID_Webtoon-VS_Trend_16X9_2\t1000\t10\tKRW\t50000\t5\t1")
KR_ROW = ("사용 설정됨\thttps://tpc.googlesyndication.com/simgad/1\t사용 가능\t이미지\t"
          "학습\t11224_勇者之歌_IMG_Madup_SingleImage_1X1_TITLE1.jpg\t900\t9\tKRW\t40000\t4\t0")


# ------------------------------------------------------------- 기간 파싱

def test_영문_기간을_읽는다():
    assert g.parse_period_month('"September 1, 2026 - September 27, 2026"') == 9
    assert g.parse_period_month("October 1, 2026 - October 31, 2026") == 10


def test_한글_기간도_그대로_읽는다():
    assert g.parse_period_month("2026년 7월 1일 - 2026년 7월 31일") == 7


def test_기간을_못_읽으면_None():
    assert g.parse_period_month("") is None
    assert g.parse_period_month("알 수 없는 형식") is None


def test_시작_월만_본다():
    """⚠ `9월 1일 ~ 10월 1일` 처럼 달을 걸친 추출은 9가 된다 — 화면은 그 사실을
    알 길이 없다. 기간을 늘려 내려받을 때 주의해야 한다는 계약을 고정한다."""
    assert g.parse_period_month("September 1, 2026 - October 1, 2026") == 9


# ------------------------------------------------------------- 헤더 읽기

def test_영문_헤더_파일을_읽는다(tmp_path):
    path = write(tmp_path, "ACa Coin 캠페인_용사의 발라드.csv",
                 '"September 1, 2026 - September 27, 2026"', EN_HEADER, [EN_ROW])
    out = g.read_asset_report(path)
    assert len(out) == 1
    assert out["month"].iat[0] == 9
    assert out["cost"].iat[0] == 50000
    assert out["total install"].iat[0] == 5


def test_영문_애셋_유형이_한글로_정규화된다(tmp_path):
    """아래 모든 코드가 한글 값을 전제한다(`CREATIVE_ASSET_TYPES`,
    `title_from_asset_name`). 한 곳에서 맞춰야 빠뜨리는 데가 없다."""
    path = write(tmp_path, "ACa Coin 캠페인_용사의 발라드.csv",
                 '"September 1, 2026 - September 27, 2026"', EN_HEADER, [EN_ROW])
    out = g.read_asset_report(path)
    assert out["asset_type"].iat[0] == "YouTube 동영상"
    assert out["asset_type"].iat[0] in g.CREATIVE_ASSET_TYPES


def test_한글_헤더는_그대로_읽힌다(tmp_path):
    path = write(tmp_path, "ACa Coin 캠페인_용사의 발라드.csv",
                 "2026년 9월 1일 - 2026년 9월 27일", KR_HEADER, [KR_ROW])
    out = g.read_asset_report(path)
    assert out["asset_type"].iat[0] == "이미지"
    assert out["cost"].iat[0] == 40000


def test_두_언어가_한_폴더에_섞여도_된다(tmp_path):
    folder = tmp_path / "AOS ACa"
    folder.mkdir()
    write(folder, "ACa Coin 캠페인_용사의 발라드.csv",
          '"September 1, 2026 - September 27, 2026"', EN_HEADER, [EN_ROW])
    write(folder, "ACa Read 캠페인_용사의 발라드.csv",
          "2026년 9월 1일 - 2026년 9월 27일", KR_HEADER, [KR_ROW])
    out = g.load_google_ads_folder(tmp_path, cost_markup=1.0)
    assert len(out) == 2
    assert out["cost"].sum() == 90000
    assert not out.attrs.get("failures")


# ------------------------------------- 다음에 또 모르는 헤더가 오면 **시끄럽게**

def test_알_수_없는_헤더는_조용히_넘어가지_않는다(tmp_path):
    """이번 사고의 재발 방지다. 예전에는 빈 컬럼만 만들고 통과했다."""
    path = write(tmp_path, "ACa Coin 캠페인_용사의 발라드.csv",
                 '"September 1, 2026 - September 27, 2026"',
                 "Foo\tBar\tBaz", ["1\t2\t3"])
    with pytest.raises(ValueError, match="헤더"):
        g.read_asset_report(path)


def test_읽지_못한_파일은_failures로_올라간다(tmp_path):
    folder = tmp_path / "AOS ACa"
    folder.mkdir()
    write(folder, "ACa Coin 캠페인_용사의 발라드.csv",
          '"September 1, 2026 - September 27, 2026"', EN_HEADER, [EN_ROW])
    write(folder, "ACa Read 캠페인_망가진파일.csv",
          '"September 1, 2026 - September 27, 2026"', "Foo\tBar", ["1\t2"])
    out = g.load_google_ads_folder(folder.parent, cost_markup=1.0)
    assert len(out) == 1                      # 멀쩡한 파일은 그대로 읽힌다
    failures = out.attrs.get("failures") or []
    assert len(failures) == 1 and "망가진파일" in failures[0]


def test_월을_못_읽어도_시끄럽다(tmp_path):
    path = write(tmp_path, "ACa Coin 캠페인_용사의 발라드.csv",
                 "기간을 알 수 없음", EN_HEADER, [EN_ROW])
    with pytest.raises(ValueError, match="월"):
        g.read_asset_report(path)


# ------------------------------------------- 작품명 표기 (2026-09-30 추가 발견)

def test_숫자로_시작해도_한글이_있으면_작품명이다():
    """⚠ `44교시 생존수업`이 **이상값으로 오판**돼 애셋 이름의 중국어
    `第44節生存課`로 덮여 광고주 화면에 나가고 있었다(9월 소진 ₩33.7M).

    숫자 접두 규칙은 `365dtg`·`2608 EPUB` 같은 파일명 쓰레기값을 잡으려던 것이다.
    """
    assert not g.is_placeholder_title("44교시 생존수업")
    assert not g.is_placeholder_title("44교시 생존 수업")
    assert not g.is_placeholder_title("맹종")           # 두 글자 작품명
    assert not g.is_placeholder_title("第44節生存課")     # 중국어 제목


def test_쓰레기값은_여전히_이상값이다():
    """한글·한자가 없으면 예전 규칙 그대로다 — 이게 풀리면 `365dtg`가 표에 남는다."""
    for junk in ("365dtg", "2608 EPUB", "special", "situationship",
                 "1200x1500", "-", "", "   "):
        assert g.is_placeholder_title(junk), junk


def test_작품명_표기를_MediaRAW에_맞춘다():
    """구글 작품명은 **담당자가 지은 파일 이름**에서 온다 — 띄어쓰기만 달라도
    같은 작품이 두 줄로 갈린다."""
    media_raw = pd.DataFrame({
        "ad": ["11224_勇者之歌_VID_a_b_c_1"],
        "title_kr": ["쪽팔려게임"],
        "cost": [1_000_000.0],
    })
    frame = pd.DataFrame({
        "title_kr": ["쪽팔려 게임", "쪽팔려게임"],
        "asset_name": ["--", "--"],
        "asset_type": ["이미지", "이미지"],
    })
    out = g.fill_titles(frame, media_raw)
    assert list(out["title_kr"]) == ["쪽팔려게임", "쪽팔려게임"]


def test_MediaRAW에_없는_작품은_안_건드린다():
    """구글에서만 집행한 작품은 그 이름이 유일하게 정확하다."""
    media_raw = pd.DataFrame({"ad": ["1_가_b_c_d_e_1"], "title_kr": ["다른작품"],
                              "cost": [1.0]})
    frame = pd.DataFrame({"title_kr": ["구글전용 작품"], "asset_name": ["--"],
                          "asset_type": ["이미지"]})
    assert g.fill_titles(frame, media_raw)["title_kr"].iat[0] == "구글전용 작품"


def test_정본은_소진이_큰_표기다():
    """개수로 고르면 소액 캠페인의 오타가 정본이 될 수 있다."""
    media_raw = pd.DataFrame({
        "ad": ["1_가_b_c_d_e_1"] * 3,
        "title_kr": ["쪽팔려 게임", "쪽팔려게임", "쪽팔려 게임"],
        "cost": [10.0, 9_000_000.0, 10.0],
    })
    assert g.canonical_titles(media_raw)["쪽팔려게임"] == "쪽팔려게임"


# ------------------------------------------- 소재명 축 (규리님 2026-09-30 요청)

REAL_IMAGE = "11224_勇者之歌_IMG_Madup_SingleImage_4X5_TITLE2.jpg"
REAL_VIDEO = ("百年後重生的絕世殺人魔，能成為英雄嗎？ GLOBAL DROP 正統奇幻"
              "《勇者之歌》今晚登場！ 11224_勇者之歌_VID_Webtoon-VS_Trend_16X9_2")


def test_이미지_애셋에서_소재명을_뽑는다():
    assert (g.creative_name_from_asset(REAL_IMAGE, "이미지")
            == "11224_勇者之歌_IMG_Madup_SingleImage_4X5_TITLE2")


def test_영상_애셋은_광고_문안_뒤의_소재명을_찾는다():
    """영상 애셋 이름은 중국어 광고 문안이고 소재명이 **그 뒤에** 붙는다."""
    assert (g.creative_name_from_asset(REAL_VIDEO, "YouTube 동영상")
            == "11224_勇者之歌_VID_Webtoon-VS_Trend_16X9_2")


def test_파일명_조각은_소재명이_아니다():
    """토큰 수 문턱이 없으면 `1200x1500_2026-03-05.jpg` 가 소재명으로 들어온다."""
    assert g.creative_name_from_asset("1200x1500_2026-03-05.jpg", "이미지") is None
    assert g.creative_name_from_asset("--", "설명") is None
    assert g.creative_name_from_asset("", "이미지") is None
    assert g.creative_name_from_asset(None, "이미지") is None
    assert g.creative_name_from_asset(pd.NA, "이미지") is None


def test_작품명_추출과_섞이지_않는다():
    """`title_from_asset_name`은 **작품명**을 뽑는 다른 함수다 — 합치지 말 것."""
    assert g.title_from_asset_name(REAL_VIDEO, "YouTube 동영상") == "勇者之歌"
    assert g.creative_name_from_asset(REAL_VIDEO, "YouTube 동영상").startswith("11224_")


def _frame(names):
    return pd.DataFrame({
        "asset_type": ["이미지"] * len(names),
        "creative_name": [g.creative_name_from_asset(n, "이미지") for n in names],
    })


def test_커버리지가_높으면_소재명_축이_열린다():
    frame = _frame([REAL_IMAGE] * 10)
    assert g.creative_name_coverage(frame) == 1.0
    assert "creative_name" in g.google_dimensions_for(frame)


def test_커버리지가_낮으면_축을_아예_안_띄운다():
    """⚠ 이 게이트가 없으면 절반이 가짜 `미분류`가 된다(`883600f` 유형).

    9월 실측: 전체 창작 애셋 커버리지 55%, 작품 31종 중 90% 이상은 6종뿐이다.
    """
    frame = _frame([REAL_IMAGE] * 5 + ["--"] * 5)
    assert g.creative_name_coverage(frame) == 0.5
    assert "creative_name" not in g.google_dimensions_for(frame)


def test_텍스트_애셋은_커버리지_계산에서_뺀다():
    """설명·광고 제목은 애셋 이름이 `--`라 애초에 소재명이 없다 — 세면 커버리지가
    부당하게 낮아져 쓸 수 있는 표에서도 축이 안 열린다."""
    frame = pd.DataFrame({
        "asset_type": ["이미지", "이미지", "설명", "광고 제목"],
        "creative_name": [g.creative_name_from_asset(REAL_IMAGE, "이미지")] * 2 + [None, None],
    })
    assert g.creative_name_coverage(frame) == 1.0


def test_라벨은_축이_안_열려도_있어야_한다():
    """이미 저장된 뷰가 `creative_name`을 들고 있으면 표 머리에 그대로 찍힌다."""
    assert g.GOOGLE_DIMENSION_LABELS["creative_name"] == "소재명"


def test_빈_표는_커버리지_0():
    assert g.creative_name_coverage(pd.DataFrame()) == 0.0
    assert g.creative_name_coverage(None) == 0.0
