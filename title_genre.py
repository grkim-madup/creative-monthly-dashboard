"""작품 장르(CLUSTER) 데이터 계층 — 광고주 PM 시트에서 읽어 작품에 장르를 붙인다.

광고주 요청(2026-09-16): *"매체별 OS별로 작품의 장르별 우수 장르 성향 패턴이 있는지."*

작품이 67종이라 매체 3 × OS 2로 갈리면 칸마다 한두 소재뿐이라 패턴이 안 보인다.
장르로 묶으면 10칸이 되어 판단이 가능해진다.

원본은 광고주 시트 `(TW) PM KPI Dashboard`의 **`title_info` 탭**이다.
⚠ **광고주 소유 시트이므로 읽기만 한다.** 이 모듈에는 I/O가 아예 없고
(`sheet_loader.load_title_genres`가 읽어서 넘겨준다), 쓰기 경로는 어디에도 없다.

## 왜 I/O를 여기 두지 않았나

`tests/conftest.py`의 fail-closed 가드는 `google_sheets_writer`·`fs_store`를 막지만
**`google_sheets_readonly`는 막지 않는다.** 이 모듈에 시트 읽기를 넣으면 테스트가
광고주 시트를 실제로 때린다. `ios_cohort.py`와 같은 이유로 **순수 parse + apply**만 둔다.

## 왜 `유형`(`genre`) 컬럼을 안 쓰나

`creative_data.py`가 Media_RAW의 `유형` 컬럼을 이미 `genre`로 파싱하고 있는데,
**8월 소진의 100%가 빈값**이고 참조하는 코드도 없다(실측 2026-09-16). 죽은 컬럼이다.
이름이 겹치면 "값이 있는데 왜 안 보이나"로 헷갈리므로 **`genre_group`**을 새로 쓴다.

## 조인 규칙

**① `title_code` → ② 한글 제목 → ③ 중국어 제목** 순서다. 코드가 우선인 이유는 작품명
표기가 갈리기 때문이다(`쪽팔려 게임` / `쪽팔려게임`). 제목 폴백이 필요한 이유는 구글이다
— 구글 행은 소재명이 `-`라 `title_code`가 없고 `title_kr`만 있다.

실측 커버리지(8월 UA 소진 기준): TikTok 99.2% · Meta 97.3% · Google 80.4%.

**못 찾으면 `미분류`로 둔다. 추측해서 채우지 않는다** — 광고주가 장르로 읽는 값이다.
"""

from __future__ import annotations

import re

import pandas as pd

from creative_data import _find_column

# 광고주 시트의 탭·컬럼 이름. ⚠ 열 위치(A/B/C…)로 찾지 않는다 — 광고주가 열을 하나
# 추가하면 조용히 엉뚱한 값이 들어온다. `_find_column`이 대소문자·공백을 무시하므로
# 원본 표기 `TItle ID`(대문자 I가 두 번째다 — 오타가 아니라 실제 헤더)도 그대로 잡힌다.
TITLE_INFO_SHEET_NAME = "title_info"

COL_CODE = "TItle ID"
COL_NAME_KR = "TITLE(KR)"
COL_NAME_TW = "TITLE(TW)"
COL_CLUSTER = "CLUSTER"

GENRE_COLUMN = "genre_group"
UNKNOWN_GENRE = "미분류"

# 자리표시자 코드. `0000`은 소재명 파서가 작품코드를 못 읽었을 때 넣는 값이라 어떤 작품도
# 가리키지 않는다 — 이걸 매칭시키면 서로 다른 작품이 한 장르로 뭉친다.
_PLACEHOLDER_CODES = {"", "0", "nan", "none", "확인불가"}

_SPACE = re.compile(r"\s+")


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def normalize_code(value) -> str:
    """작품 코드를 비교 가능한 형태로. 앞의 `0`을 떼어 `0141`과 `141`을 같게 본다."""
    text = _clean(value)
    if not text:
        return ""
    # 소수점이 붙어 오는 경우가 있다(시트가 숫자로 읽어 `141.0`).
    if text.endswith(".0"):
        text = text[:-2]
    stripped = text.lstrip("0")
    if stripped.lower() in _PLACEHOLDER_CODES or text.lower() in _PLACEHOLDER_CODES:
        return ""
    return stripped


def normalize_name(value) -> str:
    """작품명을 비교 가능한 형태로. 공백을 모두 지우고 소문자로.

    `쪽팔려 게임`과 `쪽팔려게임`은 같은 작품이다(실측) — 구글 애셋 이름 보정에서 이미
    같은 문제를 겪었다.
    """
    text = _clean(value)
    if not text:
        return ""
    return _SPACE.sub("", text).lower()


def parse_title_genres(values: list[list[str]]) -> dict:
    """`title_info` 값 → 조인용 대응표.

    ⚠ **대응표를 코드에 박지 않는다.** 광고주가 신규 작품을 등재하면 자동으로 따라와야
    한다. 다만 광고주는 **작품을 런칭 전에 먼저 등재하고 CLUSTER는 나중에 채운다**
    (실측: 10월 런칭 44건 중 CLUSTER 0건). CLUSTER가 빈 행은 대응표에 넣지 않으므로
    그 작품은 채워질 때까지 `미분류`로 뜨고, 채워지면 다음 조회부터 저절로 맞아진다.

    돌려주는 것: `{"by_code": {...}, "by_name": {...}, "titles": 개수}`
    """
    empty = {"by_code": {}, "by_name": {}, "titles": 0}
    if not values or len(values) < 2:
        return empty

    header = values[0]
    code_col = _find_column(header, COL_CODE)
    cluster_col = _find_column(header, COL_CLUSTER)
    if cluster_col is None:
        # 장르 컬럼이 없으면 이 탭이 아니거나 광고주가 이름을 바꾼 것이다. 빈 표를
        # 돌려주면 화면은 전부 `미분류`가 되고, 감사 도구(G2)가 매칭률 0%로 잡는다.
        return empty
    kr_col = _find_column(header, COL_NAME_KR)
    tw_col = _find_column(header, COL_NAME_TW)

    index = {name: position for position, name in enumerate(header)}

    def cell(row: list, column) -> str:
        if column is None:
            return ""
        position = index[column]
        return _clean(row[position]) if position < len(row) else ""

    by_code: dict[str, str] = {}
    by_name: dict[str, str] = {}
    titles = 0

    for row in values[1:]:
        cluster = cell(row, cluster_col)
        if not cluster:
            continue
        titles += 1
        code = normalize_code(cell(row, code_col))
        if code:
            by_code.setdefault(code, cluster)
        for column in (kr_col, tw_col):
            name = normalize_name(cell(row, column))
            if name:
                by_name.setdefault(name, cluster)

    return {"by_code": by_code, "by_name": by_name, "titles": titles}


def lookup(table: dict, code, name) -> str | None:
    """작품 하나의 장르. 못 찾으면 `None`(호출부가 `미분류`로 채운다)."""
    if not table:
        return None
    by_code = table.get("by_code") or {}
    normalized = normalize_code(code)
    if normalized and normalized in by_code:
        return by_code[normalized]
    by_name = table.get("by_name") or {}
    key = normalize_name(name)
    if key and key in by_name:
        return by_name[key]
    return None


def attach_genre(frame: pd.DataFrame, table: dict) -> pd.DataFrame:
    """프레임에 `genre_group` 컬럼을 붙인다.

    ⚠ **원본을 고치지 않는다**(복사본을 돌려준다) — 이 프레임은 `st.cache_data`가 들고
    있어서 제자리에서 고치면 다음 리런이 이미 고친 것을 또 고친다.

    표가 비었거나 컬럼이 없어도 안전하다. 그 경우에도 `genre_group`은 만들어 둔다 —
    컬럼 자체가 없으면 축으로 고른 표가 `KeyError`가 아니라 빈 표로 조용히 죽는다.
    """
    if frame is None or getattr(frame, "empty", True):
        return frame

    out = frame.copy()
    if not table or not (table.get("by_code") or table.get("by_name")):
        out[GENRE_COLUMN] = UNKNOWN_GENRE
        return out

    codes = out["title_code"] if "title_code" in out.columns else pd.Series("", index=out.index)
    names = out["title_kr"] if "title_kr" in out.columns else pd.Series("", index=out.index)

    # 작품 수가 수십 종인데 행은 수만 개다 — 행마다 찾지 말고 **고유 조합만** 찾아 매핑한다
    # (8월 83,091행 → 고유 조합 100여 개).
    pairs = pd.DataFrame({"code": codes.astype(object), "name": names.astype(object)})
    unique = pairs.drop_duplicates()
    resolved = {
        (row.code, row.name): (lookup(table, row.code, row.name) or UNKNOWN_GENRE)
        for row in unique.itertuples(index=False)
    }
    out[GENRE_COLUMN] = [resolved[(c, n)] for c, n in zip(pairs["code"], pairs["name"])]
    return out


def attach_genre_by_month(frame: pd.DataFrame, live: dict,
                          frozen: dict[int, dict] | None = None) -> pd.DataFrame:
    """달마다 **그 달의 장르표**로 장르를 붙인다.

    ## 왜 달마다 다른 표를 쓰나 (규리님 선택 2026-09-16)

    장르 조인은 스냅샷을 적용한 **뒤**에 일어난다 — 그래야 이미 고정된 달에도 장르가
    붙는다(고정본에 `genre_group` 컬럼이 없기 때문). 그런데 그러면 광고주가 작품을
    재분류했을 때 **이미 보낸 리포트의 표가 조용히 달라진다.**

    그래서 고정할 때 그 시점의 장르표를 스냅샷 `settings`에 함께 저장하고, 여기서
    그 달만 저장본을 쓴다. 마크업·시트 링크를 이미 그렇게 저장하고 있다
    (*"사라지지 않는 것과 바뀌지 않는 것은 다르다"* — 2026-09-08에 마크업 고정이
    반쪽이라 같은 사고를 냈던 자리다).

    ⚠ **저장본이 없는 달은 라이브로 떨어진다.** 7·8월은 이 기능이 생기기 전에 고정돼서
    저장본이 없다 — 소급해서 넣을 방법은 없다(다시 고정하면 그 순간의 라이브 시트를
    다시 읽어 **광고주에게 이미 나간 숫자가 움직인다**).
    """
    if frame is None or getattr(frame, "empty", True):
        return frame
    if not frozen or "month" not in frame.columns:
        return attach_genre(frame, live)

    # 저장본이 있는 달만 따로 처리한다. 대부분의 달은 라이브 하나로 끝난다.
    special = {int(m): t for m, t in frozen.items()
               if t and (t.get("by_code") or t.get("by_name"))}
    if not special:
        return attach_genre(frame, live)

    out = attach_genre(frame, live)
    months = out["month"]
    for month, table in special.items():
        rows = months == month
        if not rows.any():
            continue
        out.loc[rows, GENRE_COLUMN] = attach_genre(out[rows], table)[GENRE_COLUMN]
    return out


def unregistered(frame: pd.DataFrame) -> pd.DataFrame:
    """장르가 안 붙은 작품을 소진액 큰 순으로. 편집자 경고에 쓴다.

    광고주 화면에는 쓰지 않는다 — 호출부가 `auth.can_edit()`로 가린다.
    """
    if frame is None or getattr(frame, "empty", True):
        return pd.DataFrame(columns=["title_kr", "cost"])
    if GENRE_COLUMN not in frame.columns:
        return pd.DataFrame(columns=["title_kr", "cost"])

    rows = frame[frame[GENRE_COLUMN] == UNKNOWN_GENRE]
    if rows.empty or "cost" not in rows.columns:
        return pd.DataFrame(columns=["title_kr", "cost"])

    label = rows["title_kr"] if "title_kr" in rows.columns else UNKNOWN_GENRE
    grouped = (
        rows.assign(title_kr=label)
        .groupby("title_kr", dropna=False)["cost"]
        .sum()
        .reset_index()
        .sort_values("cost", ascending=False)
    )
    return grouped.reset_index(drop=True)
