"""구글 광고 '애셋 세부정보 보고서' 폴더 로더.

구글 소재 성과는 `Media_RAW`에 없다. 담당자가 구글 광고에서 캠페인별로 '애셋 세부정보 보고서'를
내려받아 드롭박스 폴더에 모아두고, 그 값을 리포트 시트에 붙여넣어 왔다. 이 모듈은 붙여넣기 결과가
아니라 **그 원본 CSV 폴더를 직접 읽는다.**

파일 규칙(2026-08 확인):
- 전부 UTF-16 · 탭 구분 · 1행 보고서명 / 2행 기간 / **3행 헤더**.
- 폴더명이 OS와 캠페인 목적을 담는다 — `AOS ACa`, `AOS ACi`, `iOS ACa coin 캠페인`, `iOS ACi 캠페인`.
  (ACi = 설치 목적, ACa = 액션(코인/열람) 목적)
- 파일명이 캠페인 구분과 작품명을 담는다 — `AOS ACa Read 여성향 캠페인_녹음의 관.csv`.
- **AOS와 iOS의 컬럼 구성이 다르다**: AOS에는 `방향`이 있고, iOS에는 대신 `애셋 이름`(파일명에
  `1200x1500` 같은 규격이 들어있음)이 있으며 CTR·평균 CPC 컬럼이 없다. 비율은 어차피 합계에서
  다시 계산하므로 문제되지 않는다.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pandas as pd

from creative_data import add_derived_metrics, size_orientation, to_number

HEADER_ROW_INDEX = 2
ENCODINGS = ("utf-16", "utf-8-sig", "cp949")

# 보고서의 `비용`은 구글 원가다. 리포트 시트의 `cost (마크업 포함)`은 여기에 마크업을 얹은 값이며,
# 2026-07 실측으로 배율이 정확히 1.0830임을 확인했다(여러 소재에서 소수점까지 일치).
DEFAULT_COST_MARKUP = 1.0830

#: ⚠ **한글·영문 헤더를 둘 다 받는다.** 담당자가 구글 광고 UI 언어를 바꾸면 내려받는
#: CSV 헤더가 통째로 영문이 된다. 예전에는 한글 이름만 있어서 **영문 파일 32개가 조용히
#: 버려졌다** — 9월 구글 애셋 소진 ₩104,234,720(실제의 66%)이 화면에서 통째로 빠져 있었다
#: (2026-09-30 발견). 에러도 안 났다. `asset_type`·`cost`가 전부 결측이 되고 `month`가
#: `None`이라 모든 월 필터에서 빠졌을 뿐이다.
#:
#: ⚠ `_find`는 공백을 지우고 **정확히** 일치시킨다 — `Asset` / `Asset status` /
#:   `Asset type` / `Asset name`이 서로 안 섞인다. 부분 일치로 바꾸지 말 것.
COLUMN_ALIASES = {
    "asset": ["확장 소재", "Asset"],
    "asset_type": ["애셋 유형", "Asset type"],
    "asset_name": ["애셋 이름", "Asset name"],
    "rating": ["실적", "Performance"],
    "direction": ["방향", "Direction"],
    "impression": ["노출수", "Impr."],
    "click": ["클릭수", "Clicks"],
    "cost": ["비용", "Cost"],
    "total install": ["설치", "Installs"],
    "in_app_action": ["인앱 액션", "In-app actions"],
    "status": ["상태", "Status"],
}

#: 애셋 유형을 **한글 표기로 정규화**한다. 이 한 곳에서만 바꾸면 아래 모든 코드
#: (`CREATIVE_ASSET_TYPES`·`title_from_asset_name`·화면 라벨)가 그대로 돈다 —
#: 영문 값을 여기저기서 따로 처리하면 한 곳만 빠뜨렸을 때 조용히 틀린다.
ASSET_TYPE_ALIASES = {
    "YouTube video": "YouTube 동영상",
    "Image": "이미지",
    "Description": "설명",
    "Headline": "광고 제목",
    "App deep link": "앱 딥 링크",
}

# 구글 표기 → 대시보드 표기
DIRECTION_ALIASES = {
    "가로 모드": "가로",
    "가로": "가로",
    "세로": "세로",
    "정사각형": "정방형",
}

CREATIVE_ASSET_TYPES = ("YouTube 동영상", "이미지")

_PERIOD_PATTERN = re.compile(r"(\d{4})년\s*(\d{1,2})월")

#: 영문 보고서의 기간 줄: `"September 1, 2026 - September 27, 2026"`.
_PERIOD_PATTERN_EN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2},\s*(\d{4})", re.IGNORECASE)
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_SIZE_IN_NAME = re.compile(r"(\d{2,4})[xX](\d{2,4})")


def _decode(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _find(columns, target: str):
    normalized = {re.sub(r"\s+", "", c): c for c in columns}
    return normalized.get(re.sub(r"\s+", "", target))


def parse_period_month(text: str) -> int | None:
    """기간 줄에서 **시작 월**을 읽는다. 한글·영문 둘 다 받는다.

    `'2026년 7월 1일 - 2026년 7월 31일'` → 7
    `'"September 1, 2026 - September 27, 2026"'` → 9

    ⚠ **시작 월만 본다.** `9월 1일 ~ 10월 1일` 처럼 달을 걸친 추출은 `9`가 되고,
      화면은 그 사실을 알 길이 없다. 기간을 늘려 내려받을 때 주의할 것.
    """
    korean = _PERIOD_PATTERN.search(text or "")
    if korean:
        return int(korean.group(2))
    english = _PERIOD_PATTERN_EN.search(text or "")
    if english:
        return _EN_MONTHS.get(english.group(1).lower())
    return None


def parse_meta_from_path(path: Path) -> dict:
    """폴더/파일 이름에서 OS·캠페인 목적·작품명을 뽑는다."""
    folder = path.parent.name
    stem = path.stem

    os_name = "iOS" if "ios" in folder.lower() else "AOS" if "aos" in folder.lower() else None
    upper = f"{folder} {stem}".upper()
    if "ACA" in upper:
        objective = "ACa (액션)"
    elif "ACI" in upper:
        objective = "ACi (설치)"
    else:
        objective = None

    title = stem.split("_", 1)[1].strip() if "_" in stem else None
    campaign = stem.split("_", 1)[0].strip()

    segment = None
    for keyword in ("남성향", "여성향", "Coin", "coin", "install", "Read"):
        if keyword in stem:
            segment = {"Coin": "코인", "coin": "코인", "install": "설치", "Read": "열람"}.get(
                keyword, keyword
            )
            break

    return {
        "os": os_name,
        "objective": objective,
        "campaign": campaign,
        "title_kr": title,
        "segment": segment,
    }


#: 작품명 자리에 들어온 **분명히 작품명이 아닌 값**. `title_kr`은 파일명에서 오므로
#: 담당자가 폴더/파일을 어떻게 이름 지었는지에 따라 이런 값이 섞인다(2026-09-09 실측:
#: `365dtg` · `2608 EPUB` · `special` · `situationship`, 302행 · 소진 ₩15,938,116).
#:
#: ⚠ **"Media_RAW 작품명 목록에 없으면 이상값"으로 판정하지 말 것.** 구글에서만
#:   집행된 작품(`울어봐 빌어도 좋고`)까지 덮어쓴다. 그리고 `맹종`처럼 두 글자
#:   작품명도 있어서 길이로도 못 가른다 — 실제로 그 규칙을 썼다가 정상 작품명을
#:   덮어쓸 뻔했다.
#: 작품을 특정할 수 없는 소재의 표기. 브랜드·이벤트 광고가 여기 들어온다.
UNKNOWN_TITLE = "미분류"

_PLACEHOLDER_TITLE = re.compile(r"^\s*$|^[-–—]+$|^\d|^[a-z]+$")

#: 한글이나 한자가 하나라도 있으면 사람이 읽는 작품명이다.
_HAS_KOREAN_OR_HANJA = re.compile(r"[가-힣㐀-鿿]")


def is_placeholder_title(value) -> bool:
    """이 값이 작품명 자리에 잘못 들어온 것인가.

    ⚠ **숫자로 시작해도 한글·한자가 있으면 작품명이다.** 숫자 접두 규칙은 `365dtg`·
      `2608 EPUB` 같은 파일명 쓰레기값을 잡으려던 것인데, **`44교시 생존수업`처럼
      숫자로 시작하는 진짜 작품명까지 걸렸다**(2026-09-30 발견).

      그래서 그 작품이 화면에 중국어 `第44節生存課`로 나가고 있었다 — 정상 작품명을
      이상값으로 보고 애셋 이름의 중국어로 덮어썼기 때문이다. 9월 소진 ₩33.7M.
    """
    if value is None or (isinstance(value, float) and value != value):
        return True
    text = str(value).strip()
    if _HAS_KOREAN_OR_HANJA.search(text):
        # 한글·한자가 있으면 빈 값·하이픈만 아니면 작품명으로 본다.
        return not text or bool(re.match(r"^[-–—]+$", text))
    return bool(_PLACEHOLDER_TITLE.match(text))


#: 이미지 애셋 이름은 `작품명_USP_규격.jpg` 규칙이다 — 첫 토큰이 작품명(한글).
#: 실측 커버리지: 603행 중 558행(93%) · **소진 기준 97%**.
#: 앞에 작품 코드가 붙는 변형도 있다(`10398_검술명가의 네크로맨서_TITLE1-MEN_new_…`).
_IMAGE_TITLE = re.compile(r"^(?:\d{3,6}_)?([^_]+)_")

#: 영상 애셋 이름은 파일명이 아니라 **중국어 광고 문안**이고, 작품명이 겹화살괄호
#: 안에 들어 있다(`《男女授受不親》`). 실측 1,201행 중 881행(73%) · **소진 기준 84%**.
_VIDEO_TITLE = re.compile(r"《([^》]+)》")


#: 작품명 자리에서 뽑혔지만 **작품명이 아닌 것**. 실측(2026-09-09)으로 걸러야 했던 것:
#: 규격(`1200x1500`·`1080x1080`) · 이벤트명(`EPUB INAPP EVENT`) · 날짜 접두.
#: 규격은 `1200x1500_2026-03-05_14-55-39.jpg`처럼 **작품명 자리에 규격이 온** 경우다.
_NOT_A_TITLE = re.compile(r"^\d+\s*[xX×]\s*\d+$|^\d{6,}")


def looks_like_title(value) -> bool:
    """뽑아낸 값이 작품명으로 볼 수 있는가.

    ⚠ 한글이나 한자가 **하나도 없으면** 작품명으로 보지 않는다. 실측에서
      `EPUB INAPP EVENT`·`App store TW`처럼 영문 이벤트·브랜드 문구가 걸렸다.
    """
    text = str(value or "").strip()
    if not text or is_placeholder_title(text) or _NOT_A_TITLE.match(text):
        return False
    return bool(re.search(r"[가-힣㐀-鿿]", text))


def title_from_asset_name(asset_name, asset_type) -> str | None:
    """애셋 이름에서 작품명을 뽑는다. 못 뽑으면 None.

    ⚠ 추측하지 않는다. 규칙에 안 맞으면 None을 돌려주고 호출자가 기존 값을 유지한다 —
      광고주에게 가는 표라서, 틀린 작품명이 들어가는 것이 비어 있는 것보다 나쁘다.

    이미지는 **한글** 작품명, 영상은 **중국어** 작품명이 나온다. 합치려면
    `tw_to_kr_map()`의 대응표로 변환해야 한다.
    """
    name = str(asset_name or "").strip()
    if not name or name in {"-", "--"}:
        return None
    kind = str(asset_type or "")
    if "이미지" in kind:
        found = _IMAGE_TITLE.match(name)
        got = found.group(1).strip() if found else None
        return got if looks_like_title(got) else None
    if "동영상" in kind:
        found = _VIDEO_TITLE.search(name)
        got = found.group(1).strip() if found else None
        return got if looks_like_title(got) else None
    # 텍스트 애셋(광고 제목·설명·앱 딥 링크)은 값이 전부 `--`다 — 애초에 집계에서 뺀다.
    return None


#: 애셋 이름 안에 들어 있는 **소재명**. `11224_勇者之歌_VID_Webtoon-VS_Trend_16X9_2`
#: 처럼 작품코드로 시작하는 토큰을 찾는다.
_CREATIVE_NAME = re.compile(r"(\d{3,6}_[^\s]+)")
_MEDIA_EXT = re.compile(r"\.(jpg|jpeg|png|gif|mp4|mov)$", re.IGNORECASE)

#: 소재명으로 인정할 최소 토큰 수(`코드_작품명_포맷_제작주체_유형…`).
#: 낮추면 `1200x1500_2026-03-05.jpg` 같은 파일명 조각이 소재명으로 들어온다.
CREATIVE_NAME_MIN_TOKENS = 5


def creative_name_from_asset(asset_name, asset_type=None) -> str | None:
    """애셋 이름에서 **소재명**을 뽑는다. 못 뽑으면 None.

    규리님(2026-09-30): *"구글 시트에서 에셋 이름 행을 보면 소재명 유추 가능."*

    ```
    이미지  11224_勇者之歌_IMG_Madup_SingleImage_4X5_TITLE2.jpg
    영상    百年後重生的…《勇者之歌》今晚登場！ 11224_勇者之歌_VID_Webtoon-VS_Trend_16X9_2
    ```

    영상은 애셋 이름이 **중국어 광고 문안**이고 그 **뒤에** 소재명이 붙는 경우가 있다.
    그래서 문안을 건너뛰고 작품코드로 시작하는 토큰을 찾는다.

    ⚠ **`title_from_asset_name`과 다른 일을 한다.** 그쪽은 *작품명*을 뽑고 영상은
      《》 안을 본다. 두 함수를 합치지 말 것 — 목적도 규칙도 다르다.

    ⚠ **전 작품에 통하지 않는다.** 9월 창작 애셋 1,765행 중 969행(55%)만 뽑힌다.
      작품에 따라 담당자가 소재명을 붙이기도, 안 붙이기도 했다. 축으로 쓸 수 있는지는
      `creative_name_coverage`로 **표마다 재서** 판단한다.
    """
    # ⚠ `str(asset_name or "")` 로 쓰면 `pd.NA` 에서 터진다
    #   (TypeError: boolean value of NA is ambiguous).
    text = "" if asset_name is None or pd.isna(asset_name) else str(asset_name)
    found = _CREATIVE_NAME.search(text)
    if not found:
        return None
    name = _MEDIA_EXT.sub("", found.group(1)).strip()
    if name.count("_") + 1 < CREATIVE_NAME_MIN_TOKENS:
        return None
    return name or None


#: 소재명 축을 열어 줄 최소 커버리지.
#:
#: ⚠ **이 게이트가 없으면 `883600f`와 같은 사고가 난다.** 구글 소재 식별자는 URL이라
#:   소재명 축이 비면 **가짜 `미분류` 버킷**이 생긴다. 9월 실측으로 작품 31종 중
#:   90% 이상은 6종뿐이고 전체 평균은 55%다 — 전역으로 열면 절반이 미분류가 된다.
#:   용사의 발라드는 79행 **100%** 라 통과한다.
CREATIVE_NAME_MIN_COVERAGE = 0.9


def creative_name_coverage(frame: pd.DataFrame) -> float:
    """이 표에서 소재명이 뽑히는 비율. 창작 애셋(영상·이미지)만 센다."""
    if frame is None or getattr(frame, "empty", True):
        return 0.0
    if "creative_name" not in frame.columns:
        return 0.0
    rows = frame
    if "asset_type" in frame.columns:
        rows = frame[frame["asset_type"].isin(CREATIVE_ASSET_TYPES)]
    if rows.empty:
        return 0.0
    return float(rows["creative_name"].notna().mean())


def google_dimensions_for(frame: pd.DataFrame) -> dict[str, str]:
    """이 표에서 **실제로 쓸 수 있는** 축 목록.

    소재명은 커버리지가 충분할 때만 넣는다 — 문턱 미만이면 **아예 안 띄운다**
    (비활성보다 미표시가 맞다는 이 저장소 관행).
    """
    dimensions = dict(GOOGLE_DIMENSIONS)
    if creative_name_coverage(frame) >= CREATIVE_NAME_MIN_COVERAGE:
        dimensions["creative_name"] = "소재명"
    return dimensions


#: 구글 창작 애셋을 **소재 단위 프레임 모양**으로 바꿀 때 쓰는 컬럼 대응.
#: 구글 애셋에는 없는 지표(`D0 read`·`D0 coin`·`D7 coin`)는 **비운다** —
#: 0으로 채우면 "전환이 0건이었다"로 읽혀 CVR이 0%로 찍힌다(구조적 부재와 실제 0은 다르다).
_CREATIVE_ROW_METRICS = ("impression", "click", "cost", "total install")


def as_creative_rows(frame: pd.DataFrame, month: int | None = None) -> pd.DataFrame:
    """구글 **영상·이미지** 애셋을 소재 단위 프레임(`named_overview`) 모양으로.

    규리님(2026-10-01): *"소재명으로 묶어도 구글이 나와야 해."*

    소재명은 애셋 이름에서 온다(`creative_name_from_asset`). 그 이름이 메타·틱톡과
    **같은 명명 규칙**이라, 붙여 놓으면 `attach_creative_attributes`가 포맷·유형·규격을
    그대로 파싱한다.

    ## ⚠ 이 프레임은 구글 집행의 일부만 담는다 (실측 2026-09-30)

    구글은 캠페인 비용을 **애셋 유형별로 배분**하는데, 소재명이 있는 것은 영상·이미지뿐이다:

    | 애셋 유형 | 9월 소진 | 소재명 |
    |---|---|---|
    | YouTube 동영상 | ₩55,875,766 (33%) | ✅ |
    | 광고 제목·설명·앱 딥 링크 | ₩106,605,098 (64%) | ❌ |
    | 이미지 | ₩5,194,217 (3%) | ✅ |

    즉 소재 단위로 넣으면 **구글 소진의 36%만** 보인다(용사의 발라드는 26%).
    규리님이 그 대가를 알고 선택했다 — 화면은 각주로 그 사실을 밝혀야 한다.

    ⚠ **CPI도 배분 왜곡을 탄다**(애셋 단위가 실제보다 33% 낮다). 메타·틱톡 소재와 한
      표에서 CPI로 줄세우면 구글이 부당하게 좋아 보인다.
    """
    if frame is None or getattr(frame, "empty", True):
        return pd.DataFrame()
    rows = frame
    if month is not None and "month" in rows.columns:
        rows = rows[rows["month"] == int(month)]
    if "asset_type" in rows.columns:
        rows = rows[rows["asset_type"].isin(CREATIVE_ASSET_TYPES)]
    if "creative_name" not in rows.columns:
        return pd.DataFrame()
    rows = rows[rows["creative_name"].notna()]
    if rows.empty:
        return pd.DataFrame()

    # 같은 소재가 캠페인·파일별로 여러 줄이다 — 소재 × OS로 합친다.
    keys = [k for k in ("creative_name", "os") if k in rows.columns]
    out = rows.groupby(keys, as_index=False)[
        [m for m in _CREATIVE_ROW_METRICS if m in rows.columns]].sum()
    out = out.rename(columns={"creative_name": "ad"})
    out["media"] = "Google"
    out["ua_type"] = "UA"
    if month is not None:
        out["month"] = float(month)
    # 구글 애셋 데이터에는 날짜가 없다(리포트 헤더의 월만) — 비워 둔다.
    out["date"] = ""
    for missing in ("D0 read", "D0 coin", "D7 coin", "D7 read"):
        out[missing] = pd.NA
    return out


def _squeeze(value) -> str:
    """공백을 없앤 비교용 키. `쪽팔려 게임`과 `쪽팔려게임`은 같은 작품이다(실측)."""
    return re.sub(r"\s+", "", str(value or ""))


def tw_to_kr_map(media_raw: pd.DataFrame) -> dict[str, str]:
    """중국어 작품명 → 한글 작품명 대응표를 **Media_RAW에서 만든다.**

    소재명 두 번째 토큰이 중국어 제목이고 같은 행의 `title_kr`이 한글 제목이다
    (`10398_劍術名門的死靈法師_GIF_…` + `검술명가의 네크로맨서`).
    실측 2026-09-08월: **50종, 한 중국어 제목이 여러 한글로 갈리는 경우 0건.**

    ⚠ 표를 코드에 박지 않는다. 작품이 추가되면 자동으로 따라와야 한다.
    """
    if media_raw is None or media_raw.empty or "ad" not in media_raw.columns:
        return {}
    tokens = media_raw["ad"].astype(str).str.split("_")
    pairs: dict[str, str] = {}
    for parts, korean in zip(tokens, media_raw.get("title_kr", pd.Series(dtype=object))):
        if len(parts) < 2:
            continue
        chinese, korean = parts[1].strip(), str(korean or "").strip()
        if len(chinese) > 1 and len(korean) > 1 and not is_placeholder_title(korean):
            pairs.setdefault(chinese, korean)
    return pairs


def canonical_titles(media_raw: pd.DataFrame | None) -> dict[str, str]:
    """공백을 지운 키 → **Media_RAW의 표기**. 없으면 빈 표.

    구글 쪽 작품명은 **담당자가 지은 파일 이름**에서 온다(`parse_meta_from_path`).
    그래서 같은 작품이 Media_RAW와 띄어쓰기만 다른 일이 생긴다 — 실측(2026-09-30):

    ```
    애셋 리포트   44교시 생존 수업   ₩22,096,962   ← 파일명에 공백이 있다
                 44교시 생존수업    ₩11,624,985
    Media_RAW    44교시 생존수업    ₩12,882,198   ← 붙여쓰기만 존재
    ```

    구글 표에서 **한 작품이 두 줄로 갈리고**, Media_RAW와 대조하면 한쪽이 안 맞는다.

    ⚠ 같은 키에 표기가 여럿이면 **소진이 큰 쪽**을 정본으로 본다. 개수로 고르면
      소액 캠페인의 오타가 정본이 될 수 있다.
    """
    if media_raw is None or media_raw.empty or "title_kr" not in media_raw.columns:
        return {}
    frame = media_raw[["title_kr"]].copy()
    frame["_cost"] = (pd.to_numeric(media_raw.get("cost"), errors="coerce").fillna(0.0)
                      if "cost" in media_raw.columns else 1.0)
    frame = frame[frame["title_kr"].astype(str).str.strip().astype(bool)]
    if frame.empty:
        return {}
    weight = frame.groupby("title_kr")["_cost"].sum().sort_values(ascending=False)
    out: dict[str, str] = {}
    for title in weight.index:
        text = str(title).strip()
        if is_placeholder_title(text):
            continue
        out.setdefault(_squeeze(text), text)
    return out


def fill_titles(frame: pd.DataFrame, media_raw: pd.DataFrame | None = None) -> pd.DataFrame:
    """`title_kr`이 작품명이 아닌 행만 **애셋 이름에서 뽑은 값으로** 채운다.

    정상 작품명은 건드리지 않는다. 못 뽑으면 원본을 그대로 둔다.
    """
    if frame is None or frame.empty or "asset_name" not in frame.columns:
        return frame
    out = frame.copy()
    tw_kr = tw_to_kr_map(media_raw) if media_raw is not None else {}
    # 공백만 다른 표기를 흡수한다(`쪽팔려 게임` ↔ `쪽팔려게임`).
    by_squeezed = {_squeeze(v): v for v in tw_kr.values()}

    def resolve(row):
        current = row.get("title_kr")
        if not is_placeholder_title(current):
            return current
        found = title_from_asset_name(row.get("asset_name"), row.get("asset_type"))
        if not found:
            return current
        # 중국어로 나온 것은 대응표로 한글로 바꾼다.
        if found in tw_kr:
            return tw_kr[found]
        squeezed = _squeeze(found)
        if squeezed in by_squeezed:
            return by_squeezed[squeezed]
        # 대응표에 없으면 **뽑은 값을 그대로 쓴다.** 한글 제목이 없는 작품
        # (구글에서만 집행)은 중국어 제목이 유일하게 정확한 이름이고, 광고주는
        # 그 제목으로 작품을 안다 — `365dtg`가 표에 남는 것보다 낫다.
        return found

    filled = out.apply(resolve, axis=1)
    # 끝까지 작품을 특정할 수 없는 소재는 **`미분류`로 못 박는다.** 실측 105행은
    # 일본만화 프로모션·App store 브랜드 광고로 **애초에 작품 광고가 아니다** —
    # 파일명에서 온 `365dtg` 같은 값을 그대로 두면 광고주가 작품명으로 읽는다.
    out["title_kr"] = [UNKNOWN_TITLE if is_placeholder_title(v) else v for v in filled]

    # 표기를 Media_RAW 쪽으로 맞춘다 — 띄어쓰기만 다른 같은 작품이 두 줄로 갈리지
    # 않게 한다. ⚠ **Media_RAW에 없는 작품은 건드리지 않는다**(구글에서만 집행한
    # 작품은 그 이름이 유일하게 정확하다).
    canonical = canonical_titles(media_raw)
    if canonical:
        out["title_kr"] = [canonical.get(_squeeze(v), v) for v in out["title_kr"]]
    return out


def read_asset_report(path: Path) -> pd.DataFrame:
    """애셋 세부정보 보고서 CSV 하나를 표준 스키마로 읽는다."""
    text = _decode(Path(path))
    lines = text.splitlines()
    if len(lines) <= HEADER_ROW_INDEX:
        return pd.DataFrame()

    month = parse_period_month(lines[1] if len(lines) > 1 else "")
    reader = csv.reader(lines[HEADER_ROW_INDEX:], delimiter="\t")
    rows = list(reader)
    if not rows:
        return pd.DataFrame()

    header = rows[0]
    body = [r + [""] * (len(header) - len(r)) for r in rows[1:] if any(c.strip() for c in r)]
    if not body:
        return pd.DataFrame()

    raw = pd.DataFrame([r[:len(header)] for r in body], columns=header)

    out = pd.DataFrame(index=raw.index)
    for target, aliases in COLUMN_ALIASES.items():
        column = next((_find(raw.columns, a) for a in aliases if _find(raw.columns, a)), None)
        if column is None:
            out[target] = pd.NA
            continue
        if target in ("impression", "click", "cost", "total install", "in_app_action"):
            out[target] = raw[column].map(to_number)
        else:
            out[target] = raw[column].astype(str).str.strip()

    # 애셋 유형을 한글 표기로 맞춘다 — 아래 모든 코드가 한글 값을 전제한다.
    out["asset_type"] = out["asset_type"].map(
        lambda v: ASSET_TYPE_ALIASES.get(str(v).strip(), v) if pd.notna(v) else v)

    # ⚠ **헤더를 못 읽은 파일을 조용히 넘기지 않는다.** 2026-09-30에 영문 헤더 파일
    #   32개가 빈 컬럼만 만든 채 통과했고, 9월 구글 애셋 소진 ₩104,234,720이 화면에서
    #   사라졌다. 에러가 없어서 아무도 몰랐다. 이제는 `failures`로 올라가 화면에 뜬다.
    unreadable = [name for name in ("asset", "asset_type", "cost")
                  if out[name].isna().all()]
    if unreadable:
        raise ValueError(
            "헤더를 알아보지 못했습니다(" + ", ".join(unreadable) + ") — 실제 헤더: "
            + " | ".join(str(c) for c in raw.columns[:8]))
    if month is None:
        raise ValueError(
            "기간 줄에서 월을 읽지 못했습니다: "
            + (lines[1].strip()[:60] if len(lines) > 1 else "(빈 줄)"))

    # 소재명을 함께 뽑아 둔다. 뽑히지 않으면 `None`이고, 축으로 쓸지는
    # `google_dimensions_for`가 표마다 커버리지를 재서 판단한다.
    out["creative_name"] = [
        creative_name_from_asset(name, kind)
        for name, kind in zip(out["asset_name"], out["asset_type"])
    ]

    meta = parse_meta_from_path(Path(path))
    for key, value in meta.items():
        out[key] = value
    out["month"] = month
    out["media"] = "Google"
    out["source_file"] = Path(path).name

    # AOS는 '방향' 컬럼, iOS는 '애셋 이름'의 규격(1200x1500)에서 방향을 유도한다.
    direction = out["direction"].map(
        lambda v: DIRECTION_ALIASES.get(str(v).strip()) if pd.notna(v) else None
    )
    out["direction"] = direction.fillna(out["asset_name"].map(_orientation_from_name))
    out["direction"] = out["direction"].astype("object").where(out["direction"].notna(), None)

    out = out[out["asset"].astype(str).str.strip().astype(bool)]
    return out.reset_index(drop=True)


def _orientation_from_name(name) -> str | None:
    if name is None or pd.isna(name):
        return None
    match = _SIZE_IN_NAME.search(str(name))
    if not match:
        return None
    return size_orientation(f"{match.group(1)}X{match.group(2)}")


def load_google_ads_folder(
    folder: str | Path, cost_markup: float = DEFAULT_COST_MARKUP
) -> pd.DataFrame:
    """폴더(하위 폴더 포함)의 모든 애셋 보고서를 읽어 하나로 합친다.

    `cost_markup`을 곱해 리포트 시트의 `cost (마크업 포함)` 기준과 맞춘다.
    """
    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {root}")

    frames = []
    failures = []
    for path in sorted(root.rglob("*.csv")):
        try:
            frame = read_asset_report(path)
        except Exception as error:  # 한 파일이 깨져도 나머지는 읽되, 무엇이 빠졌는지는 남긴다
            failures.append(f"{path.name}: {error}")
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        combined = pd.DataFrame()
    else:
        combined = pd.concat(frames, ignore_index=True)
        combined["cost_raw"] = combined["cost"]
        combined["cost"] = combined["cost"] * cost_markup
    combined.attrs["failures"] = failures
    return combined


def creative_assets(df: pd.DataFrame) -> pd.DataFrame:
    """영상·이미지 애셋만 남긴다(설명·제목·앱 딥 링크 등 텍스트 애셋 제외)."""
    if df.empty:
        return df
    return df[df["asset_type"].isin(CREATIVE_ASSET_TYPES)].reset_index(drop=True)


def aggregate_google(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """키 기준 합산 후 비율 재계산. 다른 섹션과 동일하게 비율은 절대 평균내지 않는다."""
    if df.empty:
        return df
    metrics = ["impression", "click", "cost", "total install", "in_app_action"]
    present = [m for m in metrics if m in df.columns]
    grouped = (
        df.groupby(keys, dropna=False)[present]
        .sum(min_count=1)
        .reset_index()
        .sort_values("cost", ascending=False)
    )
    for column in ("D0 read", "D0 coin", "D7 coin"):
        grouped[column] = pd.NA
    grouped = add_derived_metrics(grouped)
    if "in_app_action" in grouped.columns:
        grouped["인앱 CPA"] = grouped["cost"] / grouped["in_app_action"].replace(0, pd.NA)
    return grouped.reset_index(drop=True)


# --------------------------------------------------------------------------- A안
# 섹션 3(신규 소재 유형별)에 구글을 **같은 블록 안 별도 표**로 넣기 위한 어휘와 집계.
# 규리님 승인 2026-09-10(A안).
#
# ⚠ **메타/틱톡과 같은 표에 합치지 않는다.** 구글은 한 캠페인 비용이 애셋 유형별로
#   나뉘어 배분되고, 소진과 설치가 **다른 비율**로 배분된다. 그래서 애셋 단위 CPI는
#   실제보다 33% 낮다(실측 2026-08: 애셋 ₩2,429 vs Media_RAW 구글 ₩3,624).
#   한 표에 넣으면 광고주 발송물에서 구글이 부당하게 좋아 보인다.
#
# ⚠ 진입점 배선은 아직 하지 않았다 — 다른 세션이 `creative_dashboard.py`를 대규모로
#   리팩터 중이라 동시에 쓰면 반쯤 쓰인 파일을 Streamlit이 읽어 죽는다(전례 있음).

#: 구글 표에서 쓸 수 있는 구분 축.
#:
#: ⚠ 소재명 파싱에서 오는 축(`creative_type`·`format`·`size`·`usp`·`extra_info_tag`·
#:   `producer_group`·`mix_group`)은 **넣지 않는다.** 구글은 소재 식별자가 URL이라
#:   그 축이 전부 빈 값이 되고, 예전에 그렇게 넣었다가 가짜 `미분류` 버킷이 생겼다
#:   (커밋 `883600f`). Extra Info는 애셋 이름에도 5%뿐이라 축으로 못 쓴다(2026-09-09 실측).
GOOGLE_DIMENSIONS = {
    "title_kr": "작품",
    "asset_type": "애셋 유형",
    "objective": "캠페인 목적",
    "os": "OS",
    "campaign": "캠페인",
    "asset": "소재 링크",
}

#: 화면에 찍을 **라벨**. 축으로 고를 수 있는지(`google_dimensions_for`)와는 별개다 —
#: 이미 저장된 뷰가 `creative_name`을 들고 있을 수 있고, 그때 라벨이 없으면 표 머리에
#: `creative_name`이 그대로 나온다.
GOOGLE_DIMENSION_LABELS = {**GOOGLE_DIMENSIONS, "creative_name": "소재명"}

#: 구글 표에서 쓸 수 있는 지표.
#:
#: ⚠ `D0 read`·`D0 coin`·`D7 coin`과 그 CVR은 **넣지 않는다.** 애셋 단위에는 그
#:   값이 없어서 `aggregate_google`이 `pd.NA`를 박는다(구조적 부재). 대신 구글에는
#:   `in_app_action`과 파생 `인앱 CPA`가 있다.
GOOGLE_METRIC_COLUMNS = [
    "cost", "impression", "click", "CTR", "CPC",
    "total install", "CPI", "in_app_action", "인앱 CPA",
]

#: 기본 축은 **작품**이다(2026-09-09에 작품명 보정이 들어가 쓸 수 있게 됐다).
GOOGLE_DEFAULT_ROWS = ["title_kr"]
GOOGLE_DEFAULT_VALUES = ["cost", "impression", "CTR", "total install", "CPI",
                         "in_app_action", "인앱 CPA"]


def google_filtered_scope(df: pd.DataFrame, filters: dict | None = None) -> pd.DataFrame:
    """필터를 AND로 적용한다 — 메타/틱톡 `filtered_scope`와 같은 의미.

    빈 값·빈 리스트는 아무것도 걸지 않는다(사용자가 안 고른 것이다).
    """
    if df is None or df.empty:
        return df
    out = df
    for field, wanted in (filters or {}).items():
        if not wanted or field not in out.columns:
            continue
        values = [wanted] if isinstance(wanted, str) else list(wanted)
        if not values:
            continue
        out = out[out[field].astype(str).isin([str(v) for v in values])]
    return out


def google_pivot(df: pd.DataFrame, rows: list[str] | None = None,
                 values: list[str] | None = None, filters: dict | None = None,
                 creative_only: bool = True) -> pd.DataFrame:
    """구글 애셋을 축 기준으로 집계한다.

    `creative_only`면 영상·이미지만 본다 — 텍스트 애셋(광고 제목·설명·앱 딥 링크)은
    `asset_name`이 전부 `--`이고 소재로 볼 수 없다.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    scope = creative_assets(df) if creative_only else df
    scope = google_filtered_scope(scope, filters)
    if scope is None or scope.empty:
        return pd.DataFrame()
    keys = [r for r in (rows or GOOGLE_DEFAULT_ROWS) if r in scope.columns]
    if not keys:
        return pd.DataFrame()
    table = aggregate_google(scope, keys)
    wanted = [v for v in (values or GOOGLE_DEFAULT_VALUES) if v in table.columns]
    # 화면 순서는 **정본 목록 순서**다(고른 순서가 아니다) — 다른 표와 같은 규칙.
    ordered = [c for c in GOOGLE_METRIC_COLUMNS if c in wanted]
    return table[keys + ordered]


def allocation_gap(asset_df: pd.DataFrame, media_google: pd.DataFrame) -> dict:
    """애셋 단위 합계가 진짜 집행액보다 얼마나 부풀었는지.

    각주에 **매달 계산해서** 찍는다 — 숫자를 박아두면 다음 달에 거짓말이 된다.
    2026-08 실측: cost 1.71배 · install 2.12배 · CPI 0.67배(즉 33% 낮게 보인다).

    `media_google`은 `Media_RAW`의 구글 행(진짜 집행액). 없으면 비율을 내지 않는다 —
    추정해서 채우면 광고주에게 틀린 근거가 간다.
    """
    def total(frame, column):
        if frame is None or frame.empty or column not in frame.columns:
            return None
        value = pd.to_numeric(frame[column], errors="coerce").sum()
        return float(value) if value == value else None

    out: dict[str, float | None] = {}
    for key, column in (("cost", "cost"), ("install", "total install")):
        asset, real = total(asset_df, column), total(media_google, column)
        out[f"asset_{key}"] = asset
        out[f"real_{key}"] = real
        out[f"{key}_ratio"] = (asset / real) if (asset and real) else None
    asset_cpi = ((out["asset_cost"] / out["asset_install"])
                 if out.get("asset_cost") and out.get("asset_install") else None)
    real_cpi = ((out["real_cost"] / out["real_install"])
                if out.get("real_cost") and out.get("real_install") else None)
    out["asset_cpi"] = asset_cpi
    out["real_cpi"] = real_cpi
    out["cpi_ratio"] = (asset_cpi / real_cpi) if (asset_cpi and real_cpi) else None
    return out


#: 구글 표 아래에 **광고주에게도 보이게** 붙이는 각주. 편집 모드 안에 감싸면 안 된다.
GOOGLE_ALLOCATION_NOTE = (
    "구글은 캠페인 비용이 애셋 유형(동영상·설명·광고제목·앱딥링크·이미지)별로 나뉘어 "
    "배분됩니다. 이 표의 소진·설치는 애셋 단위 배분값이라 총괄의 구글 실적과 "
    "일치하지 않으며, 매체 간 CPI 비교에 쓸 수 없습니다."
)
