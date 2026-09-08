"""데이터 적합성 점검 — 시트 원본에서 화면까지 무엇이 얼마나 빠졌는지.

**왜.** 규리님 요구는 *"대시보드에서 보이는 데이터와 Media_RAW의 데이터가 동일한가,
누락된 것이 없는가"* 다. 지금은 이걸 확인하려면 시트 피벗을 손으로 만들어 대조해야 하고,
8월 리포트 작업에서 두 번째로 시간을 많이 잡아먹은 일이었다.

문제는 대시보드와 Media_RAW 사이에 **의도된 차이가 여러 겹** 쌓여 있는데 그게 코드에만
있고 화면 어디에도 안 적혀 있다는 것이다. 그래서 "숫자가 다르다"를 만나면 매번 원인을
처음부터 추적하게 된다. 2026-09-02에 광고주가 Media_RAW 총합과 안 맞는다고 물어온 적이
있고, 원인은 UA 필터였다.

8월 실측(2026-09-08, 시트 `1SCMxbAD…`):

    ① 시트 8월 전체                13,156행  ₩359,204,066  설치 118,146
    ② − 대상 외 매체(ASA·MOLOCO)    7,712행  ₩332,078,833  설치 111,322
    ③ − 소재명 빈 행                7,567행  ₩332,078,833  설치  99,982  ← 설치 11,340 사라짐
    ④ − non-UA                     6,639행  ₩321,209,673  설치  99,496
    ⑤ 파싱 + iOS 코호트 적용         6,639행  ₩321,209,673  설치 110,422  ← 코호트 +10,926
    ⑥ − 포맷 VID/IMG/GIF 외         6,639행  ₩321,209,673  설치 110,422
    ⑦ 화면 scope                    6,639행  ₩321,209,673  설치 110,422

소진은 원본과 정확히 일치했다(차이 0원). 설치만 두 군데서 움직이고, ③은 **확인이 필요한
항목**이다 — `최종 AD`가 빈 행 145개가 소진 ₩0인데 설치를 11,340건 들고 있고,
`parse_raw_values`가 그 행을 통째로 버린다.

⚠ **이 숫자는 어느 시트를 보느냐에 달렸다.** 화면은 `app_settings`의 `sheet_url`을 읽고
그 값은 사이드바에서 바뀐다 — 점검 도구가 시트를 하드코딩하면 딴 걸 재고 "맞다"고
보고하게 된다(실제로 그렇게 됐다: 옛 시트 ₩314,822,890 vs 화면 ₩321,209,673).

**지문(fingerprint)이 이 설계의 핵심.** `.cache/*.parquet`은 파싱·코호트가 적용된 **뒤**의
데이터다. 진짜 "시트 ↔ 화면"을 보려면 원본 값이 필요한데, 점검할 때마다 시트를 다시 받으면
36초 + API 쿼터를 쓴다. 그래서 원본 집계만 뽑아 sidecar JSON으로 남기고, 점검은 그것만 읽는다.

⚠ **지문은 `parse_raw_values`를 쓰지 않고 독립적으로 계산한다.** 같은 함수를 쓰면 파서가
틀렸을 때 지문도 같이 틀려서 점검이 무의미해진다 — `tools/audit_pivot.py`가 정답 프레임을
손으로 다시 만드는 것과 같은 이유다. 컬럼 이름 상수와 `to_number`·`normalize_media` 같은
표기 정규화만 재사용한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from creative_data import (
    COL_AD,
    COL_MEDIA,
    COL_MONTH,
    COL_OS,
    COL_UA,
    RAW_SHEET_NAME,
    _find_column,
    normalize_media,
    to_number,
)

CACHE_DIR = Path(__file__).resolve().parent / ".cache"

#: 지문 형식이 바뀌면 올린다. 옛 지문을 새 코드로 읽으면 조용히 틀린 표가 나온다.
FINGERPRINT_VERSION = 1

#: 화면이 실제로 쓰는 고정 조건. 진입점의 `media_selection`·`ua_selection`·
#: `format_selection`과 **같은 값이어야 한다.** 진입점을 import할 수 없어(화면을 그린다)
#: 여기 복제하고, 어긋나면 알아채도록 `tools/audit_reconcile.py`가 값을 함께 찍는다.
SCREEN_MEDIA = ("TikTok", "Meta", "Google")
SCREEN_UA = ("UA",)
SCREEN_FORMATS = ("VID", "IMG", "GIF")

#: 소재 단위가 없는 매체. 소재명이 비어 있어도 버리지 않고 자리표시자를 채워 살려 둔다
#: (`parse_raw_values`가 그렇게 한다) — 구글은 소재 태깅 자체가 없어서지 데이터가 없는 게 아니다.
ADLESS_MEDIA = ("Google",)

VERDICT_INTENDED = "의도된 제외"
VERDICT_REPLACED = "의도된 대체"
VERDICT_MATCH = "일치"
VERDICT_CHECK = "확인 필요"

KST = timezone(timedelta(hours=9))

METRICS = ("cost", "impression", "click", "install")


# --------------------------------------------------------------------------- 지문

def fingerprint_path(sheet_id: str) -> Path:
    return CACHE_DIR / f"{sheet_id}.fp{FINGERPRINT_VERSION}.json"


def build_fingerprint(values: list[list[str]], sheet_id: str = "",
                      cohort: pd.DataFrame | None = None) -> dict:
    """Media_RAW 2차원 값 → 원본 집계 지문.

    `parse_raw_values`를 부르지 않는다(위 모듈 주석 참고). 여기서 하는 일은 헤더에서
    필요한 컬럼을 찾아 숫자로 바꾸고, `월 × 매체 × UA × OS × 소재명 유무`로 묶는 것뿐이다.
    """
    if not values:
        return _empty_fingerprint(sheet_id)

    header = values[0]
    width = len(header)
    raw = pd.DataFrame([row + [""] * (width - len(row)) for row in values[1:]],
                       columns=header)
    if raw.empty:
        return _empty_fingerprint(sheet_id)

    def column(name: str) -> pd.Series:
        found = _find_column(raw.columns, name)
        if found is None:
            return pd.Series([""] * len(raw), index=raw.index)
        return raw[found]

    frame = pd.DataFrame(index=raw.index)
    frame["month"] = column(COL_MONTH).map(to_number)
    frame["media"] = column(COL_MEDIA).astype(str).str.strip().map(normalize_media)
    frame["ua_type"] = column(COL_UA).astype(str).str.strip()
    frame["os"] = column(COL_OS).astype(str).str.strip()
    ad = column(COL_AD).astype(str).str.strip()
    frame["has_ad"] = ad.ne("") & ad.ne("nan")

    for label, source in (("cost", "cost (마크업 포함)"), ("impression", "impression"),
                          ("click", "click"), ("install", "total install")):
        frame[label] = column(source).map(to_number).fillna(0.0)

    frame = frame[frame["month"].notna()]
    keys = ["month", "media", "ua_type", "os", "has_ad"]
    grouped = (frame.groupby(keys, dropna=False)
               .agg(rows=("cost", "size"), **{m: (m, "sum") for m in METRICS})
               .reset_index())
    grouped["month"] = grouped["month"].astype(int)

    return {
        "version": FINGERPRINT_VERSION,
        "sheet_id": sheet_id,
        "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "sheet_rows": int(len(values) - 1),
        "by_key": grouped.to_dict("records"),
        "cohort": _cohort_summary(cohort),
    }


def _empty_fingerprint(sheet_id: str) -> dict:
    return {"version": FINGERPRINT_VERSION, "sheet_id": sheet_id,
            "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "sheet_rows": 0, "by_key": [], "cohort": {"rows": 0, "by_key": []}}


def _cohort_summary(cohort: pd.DataFrame | None) -> dict:
    """`iOS 코호트 RD`에서 설치가 잡힌 (월, 매체, 소재)만 남긴다.

    RAW에 그 소재 행이 없으면 코호트의 설치가 화면에 영영 못 들어온다 — 그걸 찾기 위한
    목록이라 설치 0인 항목은 뺀다(파일만 커지고 쓸모가 없다).
    """
    if cohort is None or cohort.empty or "total install" not in cohort.columns:
        return {"rows": 0, "by_key": []}
    live = cohort[cohort["total install"].fillna(0) > 0]
    records = [
        {"month": int(r["month"]), "media": str(r["media"]), "ad": str(r["ad"]),
         "install": float(r["total install"])}
        for _, r in live.iterrows() if pd.notna(r.get("month"))
    ]
    return {"rows": int(len(cohort)), "by_key": records}


def save_fingerprint(fingerprint: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = fingerprint_path(fingerprint.get("sheet_id", ""))
    # 임시 파일에 다 쓰고 갈아끼운다 — 쓰는 중에 끊기면 반쯤 쓰인 JSON이 남고,
    # 그걸 읽은 점검이 "원본이 이만큼밖에 없다"고 보고하게 된다.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(fingerprint, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def load_fingerprint(sheet_id: str) -> dict | None:
    path = fingerprint_path(sheet_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if data.get("version") == FINGERPRINT_VERSION else None


def fetch_fingerprint(sheet_id: str, *, refresh: bool = False) -> dict:
    """지문을 얻는다. 캐시가 있으면 그대로, 없으면 시트를 읽어 만들고 저장한다.

    시트를 읽는 것은 **여기 한 곳**이다. 순수 함수들(`build_fingerprint`·`waterfall`)은
    네트워크를 모른다 — 테스트가 실제 시트에 닿지 않게 하는 경계다.
    """
    if not refresh:
        cached = load_fingerprint(sheet_id)
        if cached is not None:
            return cached

    from google_sheets_readonly import (
        fetch_sheet_values,
        fetch_sheet_values_parallel,
        get_credentials,
    )
    from ios_cohort import IOS_COHORT_SHEET_NAME, parse_ios_cohort

    credentials = get_credentials()
    values = fetch_sheet_values_parallel(sheet_id, RAW_SHEET_NAME, credentials)
    try:
        cohort = parse_ios_cohort(
            fetch_sheet_values(sheet_id, IOS_COHORT_SHEET_NAME, credentials)
        )
    except Exception:  # 코호트 탭이 없어도 나머지 점검은 할 수 있어야 한다
        cohort = None

    fingerprint = build_fingerprint(values, sheet_id, cohort)
    save_fingerprint(fingerprint)
    return fingerprint


# ----------------------------------------------------------------------- 워터폴

def _fp_frame(fingerprint: dict) -> pd.DataFrame:
    records = (fingerprint or {}).get("by_key") or []
    if not records:
        return pd.DataFrame(columns=["month", "media", "ua_type", "os", "has_ad",
                                     "rows", *METRICS])
    return pd.DataFrame(records)


def _totals(frame: pd.DataFrame, *, rows_column: str | None = None) -> dict:
    """행수와 지표 합계. 지문은 이미 묶여 있어 `rows` 컬럼을 더하고, 원본 프레임은 길이를 센다."""
    if frame is None or len(frame) == 0:
        return {"rows": 0, **{m: 0.0 for m in METRICS}}
    rows = int(frame[rows_column].sum()) if rows_column else int(len(frame))
    out = {"rows": rows}
    for metric in METRICS:
        column = "total install" if (metric == "install" and rows_column is None) else metric
        out[metric] = float(frame[column].sum()) if column in frame.columns else 0.0
    return out


def _step(label: str, totals: dict, previous: dict | None, reason: str,
          verdict: str) -> dict:
    step = {"label": label, "reason": reason, "verdict": verdict, **totals}
    for key in ("rows", *METRICS):
        step[f"d_{key}"] = (totals[key] - previous[key]) if previous else 0
    return step


def waterfall(fingerprint: dict, parsed: pd.DataFrame, scope: pd.DataFrame,
              month: int, *, media=SCREEN_MEDIA, ua=SCREEN_UA,
              formats=SCREEN_FORMATS) -> list[dict]:
    """시트 원본 → 화면까지의 단계별 감소.

    ①~④는 **지문만으로** 계산한다(네트워크 없음). ⑤(포맷)는 소재명 파싱이 있어야 알 수
    있어 지문에 없으므로 파싱된 프레임에서 잰다 — 그 경계에서 파싱이 값을 바꾸지 않았는지
    `파싱 후 대조` 단계로 먼저 확인한다. 그 줄이 없으면 파싱 손실이 '포맷 제외'로
    잘못 귀속된다.

    · `parsed` — `load_media_raw`가 돌려주는 프레임 전체(모든 달)
    · `scope`  — 화면이 실제로 그리는 그 달 프레임
    """
    month = int(month)
    fp = _fp_frame(fingerprint)
    fp = fp[fp["month"] == month] if len(fp) else fp
    steps: list[dict] = []

    total = _totals(fp, rows_column="rows")
    steps.append(_step(f"① 시트 {month}월 전체", total, None,
                       "Media_RAW 원본", VERDICT_MATCH))

    kept = fp[fp["media"].isin(media)] if len(fp) else fp
    total = _totals(kept, rows_column="rows")
    dropped = sorted(set(fp["media"].dropna()) - set(media)) if len(fp) else []
    steps.append(_step("② − 대상 외 매체", total, steps[-1],
                       f"이 리포트가 다루지 않는 매체 — {', '.join(dropped) or '없음'}",
                       VERDICT_INTENDED))

    named = kept[kept["has_ad"] | kept["media"].isin(ADLESS_MEDIA)] if len(kept) else kept
    total = _totals(named, rows_column="rows")
    step = _step("③ − 소재명 빈 행", total, steps[-1],
                 "`최종 AD`가 비어 소재 단위로 집계할 수 없는 행", VERDICT_INTENDED)
    # ✅ 2026-09-08 규리님 확정: **소진액과 소재명이 함께 찍힌 소재만** 집계한다.
    #    즉 소재명이 빈 행은 설치를 들고 있어도 제외하는 것이 의도된 기준이다
    #    (8월 145행 · 설치 11,340건 · 소진 ₩0). 이건 판단이 끝난 항목이라
    #    `확인 필요`로 띄우지 않는다 — 매달 같은 경고가 뜨면 정작 새로 생긴
    #    문제를 못 알아본다.
    #
    #    ⚠ 다만 **소진이 실려 있는데 소재명이 빈 행**은 다르다. 그건 집행비가
    #      화면에서 사라지는 것이라 사람이 봐야 한다.
    if step["d_cost"] != 0:
        step["verdict"] = VERDICT_CHECK
        step["reason"] += " — 소진액이 실린 행이 버려집니다"
    elif step["d_install"] != 0:
        step["reason"] += (f" — 설치 {abs(step['d_install']):,.0f}건이 함께 빠집니다"
                           " (소진 ₩0 · 규리님 확정 기준)")
    steps.append(step)

    ua_kept = named[named["ua_type"].isin(ua)] if len(named) else named
    total = _totals(ua_kept, rows_column="rows")
    steps.append(_step("④ − non-UA", total, steps[-1],
                       "이 리포트는 UA(신규 유입) 집행분만 집계합니다", VERDICT_INTENDED))

    # 여기서부터 파싱된 프레임이다. `load_media_raw`는 파싱과 **iOS 코호트 대체를 함께**
    # 한다 — 그래서 이 단계에서 설치가 늘어나는 것이 정상이다(8월 +10,638). 처음엔 이
    # 대체를 마지막 ⑥에 적어 뒀는데, 실제로는 여기서 일어나 라벨과 숫자가 어긋났다.
    base = parsed[parsed["month"] == month] if parsed is not None and len(parsed) else parsed
    if base is not None and len(base):
        base = base[base["media"].isin(media) & base["os"].notna()
                    & base["ua_type"].isin(ua)]
    total = _totals(base)
    step = _step("⑤ 파싱 + iOS 코호트 적용", total, steps[-1],
                 "iOS 전환 지표를 앱스플라이어 코호트 값으로 대체 "
                 "(소진·행수는 그대로여야 합니다)", VERDICT_REPLACED)
    if round(step["d_cost"], 2) != 0 or step["d_rows"] != 0:
        # 코호트는 **전환 지표만** 채운다. 소진이나 행수가 움직였다면 대체가 아니라
        # 파싱이 값을 바꿨다는 뜻이고, 그건 사고다.
        step["verdict"] = VERDICT_CHECK
        step["reason"] += " — 소진·행수가 함께 움직였습니다"
    steps.append(step)

    if base is not None and len(base):
        formatted = base[base["format"].isin(formats)
                         | base["media"].isin(ADLESS_MEDIA)]
    else:
        formatted = base
    total = _totals(formatted)
    steps.append(_step(f"⑥ − 포맷 {'/'.join(formats)} 외", total, steps[-1],
                       "영상·이미지·GIF만 집계합니다(구글은 포맷 태깅이 없어 예외)",
                       VERDICT_INTENDED))

    total = _totals(scope)
    step = _step("⑦ 화면 scope", total, steps[-1],
                 "화면이 실제로 그리는 값", VERDICT_MATCH)
    if any(round(step[f"d_{k}"], 2) != 0 for k in ("rows", *METRICS)):
        # 여기서 뭔가 움직였다면 위 단계로 설명되지 않는 차이다 — 가장 위험한 신호다.
        step["verdict"] = VERDICT_CHECK
        step["reason"] = "앞 단계로 설명되지 않는 차이가 있습니다"
    steps.append(step)
    return steps


# ------------------------------------------------------------------- 설치 격차

def install_gap(fingerprint: dict, scope: pd.DataFrame, month: int, *,
                media=SCREEN_MEDIA, ua=SCREEN_UA) -> dict:
    """설치가 어디서 얼마나 움직였는지.

    소진은 대개 원본과 딱 맞고 **설치만 움직인다**(8월이 그랬다). 두 가지가 있다:
      · 소재명 빈 행이 버려지며 사라지는 설치 — 화면에 못 들어온다
      · iOS 코호트 대체 — 의도된 것이고 늘어난다
    """
    month = int(month)
    fp = _fp_frame(fingerprint)
    fp = fp[fp["month"] == month] if len(fp) else fp
    scoped = fp[fp["media"].isin(media)] if len(fp) else fp

    unnamed = (scoped[~scoped["has_ad"] & ~scoped["media"].isin(ADLESS_MEDIA)]
               if len(scoped) else scoped)
    kept = (scoped[scoped["has_ad"] | scoped["media"].isin(ADLESS_MEDIA)]
            if len(scoped) else scoped)
    kept = kept[kept["ua_type"].isin(ua)] if len(kept) else kept

    sheet_by_os = (kept.groupby("os")["install"].sum().to_dict() if len(kept) else {})
    screen_by_os = (scope.groupby("os")["total install"].sum().to_dict()
                    if scope is not None and len(scope) else {})

    return {
        "unnamed_rows": int(unnamed["rows"].sum()) if len(unnamed) else 0,
        "unnamed_install": float(unnamed["install"].sum()) if len(unnamed) else 0.0,
        "unnamed_cost": float(unnamed["cost"].sum()) if len(unnamed) else 0.0,
        "by_os": [
            {"os": os_name,
             "sheet": float(sheet_by_os.get(os_name, 0.0)),
             "screen": float(screen_by_os.get(os_name, 0.0)),
             "delta": float(screen_by_os.get(os_name, 0.0)
                            - sheet_by_os.get(os_name, 0.0))}
            for os_name in sorted(set(sheet_by_os) | set(screen_by_os))
        ],
    }


def cohort_orphans(fingerprint: dict, parsed: pd.DataFrame, month: int) -> list[dict]:
    """코호트엔 설치가 잡혔는데 RAW에 그 소재의 iOS 행이 없는 건.

    `apply_ios_cohort`는 RAW의 iOS 행에 값을 **채워 넣는** 방식이라, 붙일 행이 없으면
    그 설치는 어디에도 안 들어간다. CLAUDE.md가 8월 31건(전체의 0.3%)으로 적어 둔 그것이다.
    """
    records = ((fingerprint or {}).get("cohort") or {}).get("by_key") or []
    month = int(month)
    wanted = [r for r in records if int(r.get("month", 0)) == month]
    if not wanted or parsed is None or len(parsed) == 0:
        return []

    ios = parsed[(parsed["month"] == month) & (parsed["os"] == "iOS")]
    have = set(zip(ios["media"].astype(str), ios["ad"].astype(str)))
    return [
        {"media": r["media"], "ad": r["ad"], "install": float(r["install"])}
        for r in wanted if (str(r["media"]), str(r["ad"])) not in have
    ]


def has_issues(steps: list[dict], gap: dict, orphans: list[dict]) -> bool:
    """`확인 필요`가 하나라도 있는가.

    ⚠ `gap["unnamed_install"]`(소재명 빈 행의 설치)은 **더 이상 이슈가 아니다.**
      2026-09-08 규리님 확정: *"소진액과 소재명이 찍힌 소재 대상으로 인스톨을
      집계하자."* 즉 그 설치를 빼는 것이 의도된 기준이다. 판단이 끝난 항목을
      매달 경고로 띄우면, 정작 **새로 생긴** 문제를 못 알아본다.
      단계 ③이 소진이 실린 채 버려질 때만 `확인 필요`를 올린다.
    """
    return (any(s["verdict"] == VERDICT_CHECK for s in steps)
            or bool(orphans))


def summary_line(steps: list[dict]) -> str:
    """맨 아래 한 줄. 소진이 원본과 맞는지가 이 점검의 결론이다."""
    if not steps:
        return "점검할 데이터가 없습니다."
    sheet = steps[0]["cost"]
    screen = steps[-1]["cost"]
    intended = sum(s["d_cost"] for s in steps[1:] if s["verdict"] == VERDICT_INTENDED)
    leftover = round(screen - sheet - intended, 2)
    if leftover == 0:
        return (f"소진 ₩{screen:,.0f} — 시트 원본에서 의도된 제외분만큼만 줄었습니다"
                f" (설명되지 않는 차이 ₩0)")
    return f"⚠ 설명되지 않는 소진 차이 ₩{leftover:,.0f} — 확인이 필요합니다"
