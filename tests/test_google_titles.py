# -*- coding: utf-8 -*-
"""구글 `작품` 컬럼을 애셋 이름으로 보정한다 (규리님 요청 2026-09-09).

`title_kr`은 드롭박스 **파일명**에서 온다. 담당자가 폴더를 어떻게 이름 지었는지에
따라 작품명 자리에 `365dtg`·`2608 EPUB` 같은 값이 들어왔다 — 광고주 표와 소재 카드
제목에 그대로 나갔다(2026-09-09 실측 302행 · 소진 ₩15,938,116).

이 파일이 지키는 것:
  · 정상 작품명은 **절대 건드리지 않는다** (`맹종`처럼 두 글자 작품명이 있다)
  · 못 뽑으면 추측하지 않고 `미분류`로 둔다
  · 대응표를 코드에 박지 않는다 (작품이 추가되면 자동으로 따라와야 한다)
"""
from __future__ import annotations

import pandas as pd

import google_ads_report as G


# ------------------------------------------------------- 이상값 판정

def test_작품명이_아닌_값을_잡는다():
    for value in ("365dtg", "2608 EPUB", "special", "situationship",
                  "", "   ", "-", "--", None):
        assert G.is_placeholder_title(value), value


def test_실제_작품명은_잡지_않는다():
    """⚠ 여기서 한 번 틀렸다. "두 글자 이하는 이상값"으로 잡았다가 `맹종`을
    덮어쓸 뻔했고, "Media_RAW에 없으면 이상값"으로 잡았다가 구글에서만 집행된
    `울어봐 빌어도 좋고`를 덮어쓸 뻔했다."""
    for value in ("맹종", "시크릿레이디", "쪽팔려 게임", "울어봐 빌어도 좋고",
                  "검술명가의 네크로맨서", "那種關係"):
        assert not G.is_placeholder_title(value), value


# ------------------------------------------------------- 애셋 이름에서 뽑기

def test_이미지는_첫_토큰이_작품명이다():
    got = G.title_from_asset_name("남녀칠세부동석_TITLE1_960x1200.jpg", "이미지")
    assert got == "남녀칠세부동석"


def test_이미지_앞에_작품_코드가_붙어도_된다():
    got = G.title_from_asset_name(
        "10398_검술명가의 네크로맨서_TITLE1-MEN_new_1200x628.jpg", "이미지")
    assert got == "검술명가의 네크로맨서"


def test_영상은_겹화살괄호_안이_작품명이다():
    """영상 애셋 이름은 파일명이 아니라 **중국어 광고 문안**이다."""
    got = G.title_from_asset_name(
        "沒有血緣關係的姊弟戀《綠蔭之冠》立即觀看！", "YouTube 동영상")
    assert got == "綠蔭之冠"


def test_작품명이_없는_광고_문안은_None():
    """작품 광고가 아닌 브랜드·카테고리 광고가 실제로 있다(일본만화 프로모션)."""
    assert G.title_from_asset_name(
        "動漫迷絕對不能錯過！日本超人氣話題作，現在立即觀看！", "YouTube 동영상") is None


def test_규격이_작품명_자리에_와도_뽑지_않는다():
    """⚠ 실제로 이걸 놓쳐서 `1200x1500`·`1080x1080`이 작품명으로 들어갔다."""
    for name in ("1200x1500_2026-03-05_14-55-39.jpg",
                 "1080x1080_2026-03-05_14-55-39.jpg"):
        assert G.title_from_asset_name(name, "이미지") is None, name


def test_영문_이벤트명은_작품명이_아니다():
    """한글도 한자도 없으면 작품명으로 보지 않는다."""
    assert G.title_from_asset_name("EPUB INAPP EVENT_1080x1350.png", "이미지") is None


def test_텍스트_애셋은_뽑지_않는다():
    """광고 제목·설명·앱 딥 링크는 값이 전부 `--`다(실측)."""
    for kind in ("광고 제목", "설명", "앱 딥 링크"):
        assert G.title_from_asset_name("--", kind) is None


# ------------------------------------------------------- 대응표

def _media_raw() -> pd.DataFrame:
    return pd.DataFrame({
        "ad": ["10398_劍術名門的死靈法師_GIF_Madup_Visual_1X1_TITLE2",
               "9981_丟臉遊戲_VID_Webtoon_VoTrailer_9X16_1",
               "2401_極權教師_VID_Webtoon-EB_Highlight_9X16_7"],
        "title_kr": ["검술명가의 네크로맨서", "쪽팔려게임", "참교육"],
    })


def test_대응표를_소재명에서_만든다():
    """소재명 두 번째 토큰이 중국어 제목, 같은 행 `title_kr`이 한글 제목이다.

    ⚠ 표를 코드에 박지 않는다 — 작품이 추가되면 자동으로 따라와야 한다.
    """
    got = G.tw_to_kr_map(_media_raw())
    assert got["劍術名門的死靈法師"] == "검술명가의 네크로맨서"
    assert got["丟臉遊戲"] == "쪽팔려게임"


def test_대응표는_이상값을_담지_않는다():
    raw = pd.DataFrame({"ad": ["1_某作品_VID_x"], "title_kr": ["365dtg"]})
    assert G.tw_to_kr_map(raw) == {}


def test_빈_프레임에도_안전하다():
    assert G.tw_to_kr_map(pd.DataFrame()) == {}
    assert G.tw_to_kr_map(None) == {}


# ------------------------------------------------------- 채우기

def _google(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["title_kr", "asset_name", "asset_type"])


def test_이상값만_채운다():
    frame = _google([
        ("365dtg", "沒有血緣關係的姊弟戀《丟臉遊戲》立即觀看！", "YouTube 동영상"),
        ("참교육", "무엇이든_TITLE1_1200x628.jpg", "이미지"),
    ])
    got = G.fill_titles(frame, _media_raw())
    assert got.loc[0, "title_kr"] == "쪽팔려게임"      # 중국어 → 한글 변환
    assert got.loc[1, "title_kr"] == "참교육"          # 정상값은 그대로


def test_공백만_다른_표기를_흡수한다():
    """`쪽팔려 게임`과 `쪽팔려게임`은 같은 작품이다(실측)."""
    raw = pd.DataFrame({"ad": ["1_丟臉遊戲_VID_x"], "title_kr": ["쪽팔려 게임"]})
    frame = _google([("365dtg", "《丟臉遊戲》立即觀看", "YouTube 동영상")])
    assert G.fill_titles(frame, raw).loc[0, "title_kr"] == "쪽팔려 게임"


def test_한글_대응이_없으면_중국어_제목을_쓴다():
    """한글 제목이 어디에도 없는 작품(구글에서만 집행)은 중국어가 유일하게
    정확한 이름이다 — `365dtg`가 표에 남는 것보다 낫다."""
    frame = _google([("365dtg", "《那種關係》每週日更新", "YouTube 동영상")])
    assert G.fill_titles(frame, _media_raw()).loc[0, "title_kr"] == "那種關係"


def test_끝까지_못_뽑으면_미분류다():
    """추측해서 채우지 않는다. 파일명에서 온 값을 그대로 두면 광고주가
    작품명으로 읽는다."""
    frame = _google([("365dtg", "動漫迷絕對不能錯過！日本超人氣話題作", "YouTube 동영상")])
    assert G.fill_titles(frame, _media_raw()).loc[0, "title_kr"] == G.UNKNOWN_TITLE


def test_보정_후에는_쓰레기값이_남지_않는다():
    frame = _google([
        ("2608 EPUB", "1200x1500_2026-03-05.jpg", "이미지"),
        ("365dtg", "EPUB INAPP EVENT_1080x1350.png", "이미지"),
    ])
    got = G.fill_titles(frame, _media_raw())
    assert not got["title_kr"].map(G.is_placeholder_title).any()
    assert (got["title_kr"] == G.UNKNOWN_TITLE).all()


def test_애셋_이름_컬럼이_없으면_그대로_돌려준다():
    frame = pd.DataFrame({"title_kr": ["365dtg"]})
    assert G.fill_titles(frame, _media_raw()).loc[0, "title_kr"] == "365dtg"


def test_화면이_이_보정을_쓴다():
    """진입점에서 부르지 않으면 아무 효과가 없다."""
    import pathlib
    for name in ("creative_dashboard.py", "app.py"):
        path = pathlib.Path(name)
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "fill_titles(google_all, raw)" in source, name
