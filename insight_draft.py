"""인사이트 초안을 **계산으로** 만든다 (순수 함수 — pytest 대상).

규리님이 표를 완성한 뒤 버튼 한 번으로 초안을 받고, 고칠 것만 고치는 흐름이다.

## 왜 LLM을 쓰지 않는가

두 가지 이유다.

1. **앱에서 LLM 호출이 막혀 있다** — Anthropic API 크레딧이 없다(`client-recap-bot`이
   같은 이유로 대기 중). 버튼을 만들어도 눌리면 실패한다.
2. **더 중요한 이유 — 지어낼 수 없어야 한다.** 이 문구는 광고주에게 그대로 간다.
   실제로 손으로 쓴 초안에서도 "그 작품이 왜 효율이 좋았는지"는 숫자에 없어서 추정을
   섞게 됐다. 계산으로만 만들면 **표에 있는 것만 말한다.** 해석이 필요한 자리는
   `(확인 필요)` 로 비워 두고 사람에게 넘긴다.

실제 리포트의 문법을 그대로 쓴다(8·6월 시트 대조):
    `- 대분석` → `ㄴ 근거`(들여쓰기) → `▶ 결론` → 별도 `추후 제작 인사이트`

## 비교 기준

**그 달 같은 매체 전체**다. 실제 시트도 `TikTok 신규유형 총계` 바로 아래
`6월 틱톡 AOS 베너 소재 총 성과`를 붙여 놓고 눈으로 대조한다. 표 안의 평균과
비교하면 "이 조건이 좋은가"를 자기 자신에게 묻는 셈이라 아무것도 알 수 없다.
"""

from __future__ import annotations

import pandas as pd

from creative_data import LOWER_IS_BETTER, RATIO_METRICS, aggregate_by, delta_unit

#: 초안에서 언급할 지표와 그 이름. 순서 = 언급 순서(볼륨 → 앞단 → 뒷단).
NARRATIVE_METRICS = [
    ("CTR", "CTR"),
    ("CPI", "CPI"),
    ("D0 read CVR", "D0 Read CVR"),
    ("D0 coin CVR", "D0 Coin CVR"),
]

#: 이 정도 차이는 "비슷하다"로 본다. 아래면 근거로 쓰지 않는다 —
#: 0.3%p 차이를 "우수"로 쓰면 광고주가 다음 달 제작 방향을 잘못 잡는다.
MEANINGFUL_RATIO_POINTS = 1.0      # %p
MEANINGFUL_CHANGE = 0.05           # 5%


def _ratio(frame: pd.DataFrame, metric: str) -> float | None:
    """그 프레임 전체의 가중 지표. 행별 평균이 아니라 합계에서 다시 계산한다."""
    if frame.empty:
        return None
    rolled = aggregate_by(frame.assign(_all="합계"), ["_all"])
    if rolled.empty or metric not in rolled.columns:
        return None
    value = rolled.iloc[0][metric]
    return None if pd.isna(value) else float(value)


def topic_particle(word: str) -> str:
    """`은`/`는` 을 고른다. `EPN형 소재은` 처럼 나오면 초안을 손으로 고치게 된다."""
    if not word:
        return "는"
    last = word.strip()[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:            # 한글 음절
        return "은" if (code - 0xAC00) % 28 else "는"
    # 숫자·영문으로 끝나면 읽는 소리로 가른다(N·L·M·R 등은 받침처럼 읽힌다).
    return "은" if last.upper() in "LMNR13678" else "는"


def fmt(metric: str, value: float | None) -> str:
    if value is None:
        return "-"
    if metric in RATIO_METRICS:
        return f"{value:.2%}"
    if metric in ("CPI", "CPC", "cost"):
        return f"₩{value:,.0f}"
    return f"{value:,.0f}"


def compare(metric: str, mine: float | None,
            benchmark: float | None) -> dict | None:
    """한 지표를 기준과 견준다. 단위·방향·의미 있는 차이인지까지 담아 돌려준다.

    ⚠ **비율은 `%p`(차이), 나머지는 `%`(변화율)** 이다. 49%→53%를 "+8.2%"로 쓰면
    광고주가 8.2%p 오른 것으로 읽는다. `creative_data.delta_unit`이 그 판단을 한다.
    """
    if mine is None or benchmark is None or benchmark == 0:
        return None
    unit = delta_unit(metric)
    if unit == "%p":
        delta = (mine - benchmark) * 100
        meaningful = abs(delta) >= MEANINGFUL_RATIO_POINTS
        shown = f"{delta:+.2f}%p"
    else:
        delta = (mine - benchmark) / benchmark
        meaningful = abs(delta) >= MEANINGFUL_CHANGE
        shown = f"{delta:+.1%}"
    better = delta < 0 if metric in LOWER_IS_BETTER else delta > 0
    return {"metric": metric, "mine": mine, "benchmark": benchmark,
            "delta": delta, "unit": unit, "shown": shown,
            "better": better, "meaningful": meaningful}


def media_verdicts(scope: pd.DataFrame, whole: pd.DataFrame) -> list[dict]:
    """매체별로 "무엇이 좋고 무엇이 나쁜지"를 가른다.

    실제 리포트가 반복해 쓰는 구조가 이것이다 — 6월 신규 배너 코멘트도
    "매체별로 워킹하는 지표가 상반되는 경향 / 틱톡 : ... / 페이스북 : ..." 였다.
    """
    if "media" not in scope.columns:
        return []
    result = []
    for media in sorted(scope["media"].dropna().unique()):
        mine = scope[scope["media"] == media]
        base = whole[whole["media"] == media] if "media" in whole.columns else whole
        rows = []
        for metric, label in NARRATIVE_METRICS:
            verdict = compare(metric, _ratio(mine, metric), _ratio(base, metric))
            if verdict and verdict["meaningful"]:
                rows.append({**verdict, "label": label})
        result.append({
            "media": str(media),
            "cost": float(mine["cost"].fillna(0).sum()),
            "good": [r for r in rows if r["better"]],
            "bad": [r for r in rows if not r["better"]],
        })
    return result


def axis_spread(scope: pd.DataFrame, field: str, metric: str = "CPI") -> dict | None:
    """그 축에서 지표가 가장 좋은 값과 가장 나쁜 값의 격차.

    "작품별 CPI 편차 큼" 같은 근거를 만든다. 소진이 아주 작은 값은 제외한다 —
    설치 1건짜리 극단값을 "3.2배 차이"의 근거로 쓰면 결론이 뒤집힌다.
    """
    if field not in scope.columns or scope.empty:
        return None
    table = aggregate_by(scope, [field])
    if table.empty or metric not in table.columns:
        return None
    total = float(table["cost"].fillna(0).sum())
    if total > 0:
        table = table[table["cost"].fillna(0) / total >= 0.05]
    table = table.dropna(subset=[metric])
    if len(table) < 2:
        return None
    ordered = table.sort_values(metric, ascending=metric in LOWER_IS_BETTER)
    best, worst = ordered.iloc[0], ordered.iloc[-1]
    if float(best[metric]) == 0:
        return None
    times = float(worst[metric]) / float(best[metric])
    if metric not in LOWER_IS_BETTER:
        times = float(best[metric]) / float(worst[metric]) if float(worst[metric]) else 0
    return {
        "field": field, "metric": metric, "times": times,
        "best_name": str(best[field]), "best": float(best[metric]),
        "worst_name": str(worst[field]), "worst": float(worst[metric]),
        "count": len(table),
    }


def notable_creatives(scope: pd.DataFrame, metric: str = "CPI",
                      limit: int = 2) -> list[dict]:
    """언급할 만한 개별 소재 — 소진 상위 중 그 지표가 가장 좋은 것.

    소진이 작은 소재는 뺀다. 설치 1건짜리를 "가장 효율 좋은 소재"로 올리면
    광고주가 그걸 더 만들자고 한다.
    """
    if scope.empty or "ad" not in scope.columns:
        return []
    table = aggregate_by(scope, ["ad"])
    if table.empty or metric not in table.columns:
        return []
    total = float(table["cost"].fillna(0).sum())
    if total > 0:
        table = table[table["cost"].fillna(0) / total >= 0.10]
    table = table.dropna(subset=[metric])
    if table.empty:
        return []
    ordered = table.sort_values(metric, ascending=metric in LOWER_IS_BETTER)
    return [{"ad": str(row["ad"]), "cost": float(row["cost"]),
             "metric": metric, "value": float(row[metric])}
            for _, row in ordered.head(limit).iterrows()]


def draft_lines(scope: pd.DataFrame, whole: pd.DataFrame, month: int,
                label: str = "", links: dict[str, str] | None = None) -> list[str]:
    """초안 본문을 줄 목록으로. 화면은 이걸 HTML로 감싸기만 한다.

    `links`는 소재명 → Drive 링크. 언급하는 소재에만 붙인다 —
    표에 있는 모든 소재에 링크를 달면 문구가 링크 목록이 된다.
    """
    links = links or {}
    if scope.empty:
        return ["- 조건에 맞는 소재가 없어 초안을 만들 수 없습니다."]

    name = label or "이 소재군"
    lines: list[str] = []
    verdicts = media_verdicts(scope, whole)
    split = [v for v in verdicts if v["good"] and v["bad"]]

    if len(verdicts) >= 2 and split:
        lines.append(f"- {name}{topic_particle(name)} 매체별로 워킹하는 지표가 상반되는 경향 "
                     f"({month}월 같은 매체 전체 대비)")
    else:
        lines.append(f"- {name} 성과 ({month}월 같은 매체 전체 대비)")

    for verdict in sorted(verdicts, key=lambda v: -v["cost"]):
        good = ", ".join(f"{r['label']} {fmt(r['metric'], r['mine'])} ({r['shown']})"
                         for r in verdict["good"])
        bad = ", ".join(f"{r['label']} {fmt(r['metric'], r['mine'])} ({r['shown']})"
                        for r in verdict["bad"])
        if good and bad:
            lines.append(f"   ㄴ {verdict['media']} : {good} 우수")
            lines.append(f"       ㄴ 다만 {bad} 저조")
        elif good:
            lines.append(f"   ㄴ {verdict['media']} : {good} 우수")
        elif bad:
            lines.append(f"   ㄴ {verdict['media']} : {bad} 저조")
        else:
            lines.append(f"   ㄴ {verdict['media']} : 전체 대비 유의미한 차이 없음")

    spread = axis_spread(scope, "title_kr")
    if spread and spread["times"] >= 1.5:
        lines.append(
            f"   ㄴ 작품별 {spread['metric']} 편차 큼 — "
            f"{spread['best_name']} {fmt(spread['metric'], spread['best'])} ~ "
            f"{spread['worst_name']} {fmt(spread['metric'], spread['worst'])} "
            f"({spread['times']:.1f}배, 소진 비중 5% 이상 {spread['count']}작품 기준)")

    for item in notable_creatives(scope):
        link = links.get(item["ad"])
        tail = f' <a href="{link}" target="_blank">소재 보기</a>' if link else ""
        lines.append(f"   ㄴ 참고 소재 : {item['ad']} — "
                     f"{item['metric']} {fmt(item['metric'], item['value'])}{tail}")

    if split:
        medias = " / ".join(v["media"] for v in split)
        lines.append(f"▶ 매체 단위로 목적을 갈라 운영하는 것이 효율적인 상황 ({medias})")

    lines.append("")
    lines.append("추후 제작 인사이트")
    for verdict in sorted(verdicts, key=lambda v: -v["cost"]):
        if verdict["bad"]:
            weakest = ", ".join(r["label"] for r in verdict["bad"])
            lines.append(f"ㄴ {verdict['media']} : {weakest} 보완이 필요 "
                         "(원인·개선 방향 확인 필요)")
    lines.append("ㄴ 차기 제작 방향 (확인 필요 — 어떤 요소가 성과를 만들었는지는 "
                 "수치로 알 수 없습니다)")
    return lines


def draft_html(scope: pd.DataFrame, whole: pd.DataFrame, month: int,
               label: str = "", links: dict[str, str] | None = None) -> str:
    """Quill 에디터에 그대로 넣을 HTML. 빈 줄은 `<p><br></p>`로 둔다."""
    out = []
    for line in draft_lines(scope, whole, month, label, links):
        out.append("<p><br></p>" if not line.strip() else f"<p>{line}</p>")
    return "".join(out)
