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

from creative_data import (
    BACK_PRIMARY,
    BACK_SECONDARY,
    FRONT_PRIMARY,
    FRONT_SECONDARY,
    LOWER_IS_BETTER,
    MEANINGFUL_CHANGE,
    MEANINGFUL_RATIO_POINTS,
    RATIO_METRICS,
    aggregate_by,
    METRIC_DISPLAY,
    VERDICT_WORDS,
    contrast_by_media,
    delta_unit,
    front_back_state,
    meaningful,
)

#: 초안에서 언급할 지표와 그 이름. 순서 = 언급 순서(볼륨 → 앞단 → 뒷단).
NARRATIVE_METRICS = [
    ("CTR", "CTR"),
    ("CPI", "CPI"),
    ("D0 read CVR", "D0 Read CVR"),
    ("D0 coin CVR", "D0 Coin CVR"),
]

# ⚠ 문턱(`MEANINGFUL_RATIO_POINTS` / `MEANINGFUL_CHANGE`)은 이제 `creative_data`에
#   있다. 여기서 다시 정의하지 말 것 — 예전에는 이 모듈만 문턱을 갖고 대조군 배지는
#   부호만 봤다. 그래서 배지는 `앞단 우수`인데 초안 근거는 한 줄도 없는 카드가
#   실측 10건 나왔고, CTR **+0.36%p**짜리가 `우수`로 찍혔다.
#   `tests/test_contrast.py::test_threshold_is_shared_with_the_draft`가 감시한다.


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


def subject_particle(word: str) -> str:
    """`이` / `가`. `topic_particle`은 은/는이라 따로 필요하다(`CPI이` 가 나왔다)."""
    word = (word or "").strip()
    if not word:
        return "이"
    last = word[-1]
    if "가" <= last <= "힣":
        return "이" if (ord(last) - 0xAC00) % 28 else "가"
    # 영문·숫자로 끝나면 발음으로 가른다. `CPI`는 "씨피아이"라 `가`다.
    return "가" if last.lower() in "aeiouy0123456789" else "이"


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


def draft_sections(scope: pd.DataFrame, whole: pd.DataFrame, month: int,
                   label: str = "", links: dict[str, str] | None = None,
                   ) -> tuple[list[str], list[str]]:
    """초안 본문을 줄 목록으로. 화면은 이걸 HTML로 감싸기만 한다.

    `links`는 소재명 → Drive 링크. 언급하는 소재에만 붙인다 —
    표에 있는 모든 소재에 링크를 달면 문구가 링크 목록이 된다.
    """
    links = links or {}
    if scope.empty:
        return ["- 조건에 맞는 소재가 없어 초안을 만들 수 없습니다."], []

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

    tail = []
    tail.append("")
    tail.append("추후 제작 인사이트")
    for verdict in sorted(verdicts, key=lambda v: -v["cost"]):
        if verdict["bad"]:
            weakest = ", ".join(r["label"] for r in verdict["bad"])
            tail.append(f"ㄴ {verdict['media']} : {weakest} 보완이 필요 "
                        "(원인·개선 방향 확인 필요)")
    tail.append("ㄴ 차기 제작 방향 (확인 필요 — 어떤 요소가 성과를 만들었는지는 "
                "수치로 알 수 없습니다)")
    return lines, tail


def draft_lines(scope: pd.DataFrame, whole: pd.DataFrame, month: int,
                label: str = "", links: dict[str, str] | None = None) -> list[str]:
    """본문 + `추후 제작 인사이트`를 이어 붙인 목록.

    ⚠ 이 함수를 **한 블록에서 두 번 부르면 `추후 제작 인사이트` 헤더가 두 번** 나온다.
      뷰가 여러 개일 때는 `draft_sections`로 본문과 꼬리를 따로 받아,
      꼬리는 블록 끝에 한 번만 붙여야 한다. 이 래퍼는 기존 호출·테스트 계약을
      지키기 위해 남겨 둔다.
    """
    body, tail = draft_sections(scope, whole, month, label, links)
    return body + tail


def draft_html(scope: pd.DataFrame, whole: pd.DataFrame, month: int,
               label: str = "", links: dict[str, str] | None = None) -> str:
    """Quill 에디터에 그대로 넣을 HTML. 빈 줄은 `<p><br></p>`로 둔다."""
    out = []
    for line in draft_lines(scope, whole, month, label, links):
        out.append("<p><br></p>" if not line.strip() else f"<p>{line}</p>")
    return "".join(out)


# ---------------------------------------------------------------------------
# 대조군 서사 — "기존 소재 대비 신규 소재가 어땠나 → 계속 쓸 의미가 있나 → next step"
#
# 규리님 요구(2026-09-03): *"코멘트도 기존 소재 대비 신규 소재의 성과가 어땠는가.
# 이 소재 유형을 계속 운영하는 것이 의미가 있는가. 그렇다면 우리의 next step
# 제안사항은 무엇인가. 이 흐름이 보여야 해."*
#
# ⚠ **`compare()`를 쓰지 않는다.** 그 함수는 값을 다시 계산해서 표와 문장이
#   어긋나게 만든 원인이다(실측 Meta CPI 표 +36.7% / 초안 +36.5%).
#   여기서는 `card["table"]`의 `delta`를 **읽어서** 표와 같은 문자열로 찍는다.

#: 되돌리기 어려운 제안(확대·축소)을 허용하는 최소 표본.
#: 근거(8월 329카드): 설치 중위값 73건 · 소진 비중 중위값 0.66%.
#: 설치가 많으면 비중이 작아도 판단할 수 있어 `설치 300` 예외를 둔다 —
#: 8월 EPN/TikTok(설치 155 · 비중 0.24%)이 정확히 그 경계다.
MIN_INSTALLS_FOR_ACTION = 100
MIN_SHARE_FOR_ACTION = 0.01
INSTALLS_OVERRIDE_SHARE = 300

#: (앞단, 뒷단) → (판정, 액션). 액션은 실제 리포트 문체(`~제안` / `~검토`)를 따른다.
VERDICT_MATRIX = {
    (1, 1): ("확대 권장", "동일 유형 확대 집행 제안"),
    (1, -1): ("유지 + 뒷단 보완",
              "유입 효율은 확인됨. 열람·코인 전환이 낮은 원인 규명 후 재제작 검토"),
    (-1, 1): ("앞단 보완 후 재시도",
              "전환은 확인됨. 유입 단가·후킹 요소 점검 후 재집행 검토"),
    (-1, -1): ("축소 검토", "원인 규명 전까지 축소 검토"),
}


def delta_text(row) -> str:
    """표에 찍히는 것과 **같은 문자열**. 여기서 다시 계산하지 않는다."""
    if pd.notna(row.get("share")):
        return f"비중 {row['share']:.1%}"
    delta = row.get("delta")
    if delta is None or pd.isna(delta):
        return "-"
    return f"{delta:+.2f}%p" if row["unit"] == "%p" else f"{delta:+.1%}"


def metric_line(row) -> str:
    """`CPI ₩7,668 (그 외 ₩5,609 · +36.7%)`."""
    metric = row["metric"]
    return (f"{METRIC_LABEL.get(metric, metric)} {fmt(metric, row['subject'])} "
            f"(그 외 {fmt(metric, row['rest'])} · {delta_text(row)})")


def operating_verdict(card: dict) -> dict:
    """이 소재군을 계속 운영할 의미가 있나. **판정은 숫자에서만 나온다.**

    두 게이트를 **따로** 본다:
      · 하드   — 판정 자체가 불가능한 표본(`front`/`back`이 판단 불가)
      · 액션   — 판정은 되지만 확대·축소 같은 되돌리기 어려운 제안은 위험한 표본

    하나로 묶으면 "소진 ₩0·설치 4건"(판정이 틀림)과 "설치 98건·비중 0.66%"
    (판정은 맞고 확대만 위험)가 같은 문구로 처리되어 전자가 후자의 신뢰도를 얻는다.
    """
    # 판정은 `judge`(고정 지표 표)에서 읽는다 — 사용자가 표에서 지표를 빼도
    # 판정과 제안이 바뀌지 않아야 한다.
    table = card.get("judge")
    if table is None:
        table = card["table"]
    front, back = front_back_state(table)
    installs = _raw(table, "total install")
    share = card.get("share")

    verdict, action = VERDICT_MATRIX.get((front["state"], back["state"]), ("", ""))
    action_ok = (
        installs >= MIN_INSTALLS_FOR_ACTION
        and ((share is not None and share >= MIN_SHARE_FOR_ACTION)
             or installs >= INSTALLS_OVERRIDE_SHARE)
    )
    return {
        "front": front, "back": back, "installs": installs,
        "verdict": verdict, "action": action,
        # 판정이 없으면 액션도 없다.
        "action_ok": bool(verdict) and action_ok,
    }


def _raw(table: pd.DataFrame, metric: str) -> float:
    rows = table[table["metric"] == metric]
    if rows.empty or pd.isna(rows.iloc[0]["subject"]):
        return 0.0
    return float(rows.iloc[0]["subject"])


def side_phrase(side: dict, label: str) -> str:
    """`앞단 우수` + 필요하면 단서. 주 지표를 못 썼거나 보조가 반대면 밝힌다."""
    word = VERDICT_WORDS[side["state"]]
    text = f"{label} {word}"
    notes = []
    if side["fallback"] and side["used"]:
        notes.append(f"{METRIC_LABEL.get(side['used'], side['used'])} 기준")
    if side["opposed"]:
        notes.append(f"{METRIC_LABEL.get(side['opposed'], side['opposed'])}는 반대")
    return f"{text} ({' · '.join(notes)})" if notes else text


def contrast_lines(cards: list[dict], month: int, title: str,
                   scale: str = "", media_limit: int = 2) -> list[str]:
    """대조군 표 하나를 문단으로. 매체는 소진 상위 `media_limit`개만 서술한다.

    카드를 다 쓰면 뷰 5개인 블록에서 초안이 70줄을 넘는다 — 그러면 규리님이
    "고칠 것만 고치는" 흐름이 아니라 지우는 작업을 하게 된다.
    """
    if not cards:
        return []
    lines = [f"- {title} — 기존 소재 대비 ({month}월 · 그 외 소재 대비)"]
    if scale:
        lines.append(f"   ㄴ 규모 : {scale}")

    shown, hidden = cards[:media_limit], cards[media_limit:]
    for card in shown:
        judged = operating_verdict(card)
        head = (f"{side_phrase(judged['front'], '앞단')} · "
                f"{side_phrase(judged['back'], '뒷단')}")
        if judged["verdict"]:
            head += f" → {judged['verdict']}"
            if not judged["action_ok"]:
                head += " (표본 작아 액션 보류)"
        lines.append(f"   ㄴ {card['media']} : {head}")

        table = card.get("judge", card["table"])
        for metrics in (FRONT_METRICS_ORDER, BACK_METRICS_ORDER):
            parts = [metric_line(row) for _, row in table.iterrows()
                     if row["metric"] in metrics and pd.notna(row.get("delta"))]
            if parts:
                lines.append("       ㄴ " + " / ".join(parts))
        sample = [f"설치 {judged['installs']:,.0f}건"]
        if card.get("share") is not None:
            sample.insert(0, f"소진 비중 {card['share']:.1%}")
        lines.append("       ㄴ " + " · ".join(sample))

    if hidden:
        total = sum(c.get("share") or 0 for c in hidden)
        names = ", ".join(c["media"] for c in hidden)
        lines.append(f"   ㄴ 그 외 매체 {len(hidden)}곳({names}) · "
                     f"소진 비중 합 {total:.1%} — 규모가 작아 생략")
    return lines


#: 근거 줄에 묶어 쓰는 순서(앞단 → 뒷단). 판정 지표와 같은 상수를 쓴다.
FRONT_METRICS_ORDER = (FRONT_PRIMARY, FRONT_SECONDARY)
BACK_METRICS_ORDER = (BACK_PRIMARY, BACK_SECONDARY)

#: 지표 이름 → 화면 표기. 표(`METRIC_DISPLAY`)와 같은 값을 쓴다.
METRIC_LABEL = dict(METRIC_DISPLAY)


def swing_creatives(scope: pd.DataFrame, metrics=("CPI", "D0 read CVR"),
                    min_ads: int = 3, min_swing: float = 0.10,
                    limit: int = 2) -> list[dict]:
    """소재군 평균을 혼자 끌고 가는 소재. **leave-one-out**으로 잰다.

    규리님 지시: *"소재단 테이블에서 유독 튀는 성과의 소재가 확인될 경우에 한해
    소재단 분석을 함께 넣어 — 그 특정 소재로 인해 전체 성과에 어떤 영향을 미치게
    되었다 와 같은 경우."* / *"소재가 3개 이상 있는 경우엔 적어."*

    소재를 나열하지 않는다. 실측(8월): Highlight 216개에서는 최대 swing이 4.5%로
    아무것도 안 걸리고(큰 소재군은 한 소재가 평균을 못 흔든다), MIX 15개에서는
    비중 37.4%짜리 하나가 제외 시 CPI를 **+30.6%** 바꾼다 — 그게 짚을 값이다.

    ⚠ **왜 그 소재가 잘/못 됐는지는 쓰지 않는다.** 숫자에 없다.
    """
    if scope.empty or "ad" not in scope.columns:
        return []
    ads = scope["ad"].dropna().unique()
    if len(ads) < min_ads:
        return []
    base = aggregate_by(scope.assign(_all="합계"), ["_all"]).iloc[0]
    total = float(scope["cost"].fillna(0).sum())

    found = []
    for ad in ads:
        others = scope[scope["ad"] != ad]
        if others.empty:
            continue
        without = aggregate_by(others.assign(_all="합계"), ["_all"]).iloc[0]
        swings = {}
        for metric in metrics:
            mine, rest = base.get(metric), without.get(metric)
            if pd.notna(mine) and pd.notna(rest) and mine:
                swings[metric] = (rest - mine) / mine
        if not swings:
            continue
        metric = max(swings, key=lambda m: abs(swings[m]))
        if abs(swings[metric]) < min_swing:
            continue
        found.append({
            "ad": str(ad), "metric": metric, "swing": swings[metric],
            "base": float(base[metric]), "without": float(without[metric]),
            "share": (float(scope[scope["ad"] == ad]["cost"].fillna(0).sum()) / total
                      if total else None),
        })
    found.sort(key=lambda item: -abs(item["swing"]))
    return found[:limit]


def swing_lines(scope: pd.DataFrame, links: dict[str, str] | None = None,
                **kwargs) -> list[str]:
    """튀는 소재를 문장으로. 없으면 **한 줄도 만들지 않는다.**"""
    links = links or {}
    lines = []
    for item in swing_creatives(scope, **kwargs):
        metric, name = item["metric"], METRIC_LABEL.get(item["metric"], item["metric"])
        share = f"소진의 {item['share']:.0%} — " if item["share"] is not None else ""
        # 방향을 말로 풀어 준다. 제외 시 지표가 나빠지면 그 소재가 평균을 떠받쳤다는 뜻.
        worse = (item["swing"] > 0) if metric in LOWER_IS_BETTER else (item["swing"] < 0)
        pull = "낮게 유지되고 있음" if worse and metric in LOWER_IS_BETTER else (
            "높게 유지되고 있음" if worse else "눌려 있음")
        link = links.get(item["ad"])
        tail = f' <a href="{link}" target="_blank">소재 보기</a>' if link else ""
        lines.append(
            f"   ㄴ {item['ad']}이 {share}제외 시 소재군 {name} "
            f"{fmt(metric, item['base'])} → {fmt(metric, item['without'])} "
            f"({item['swing']:+.1%})으로, 소재군 {name}{subject_particle(name)} "
            f"이 소재 하나에 의해 {pull}{tail}")
    return lines


def next_step_lines(entries: list[tuple[str, dict]]) -> list[str]:
    """`추후 제작 인사이트`. 실제 리포트 문체를 따른다.

    `notes/next_step_7.json`의 사람이 쓴 원문에서 확인한 규칙:
      · 근거는 명사형·음슴체(`~있음`, `~활용`)
      · 제안은 `>>` 로 시작하고 `~제안` / `~검토`로 끝난다(화면에서 초록 굵게)
      · 제안 아래에 `ex)` 로 구체 예시를 붙인다

    ⚠ `ex)` 자리는 **비운다.** 거기에 문구를 지어 넣으면 광고주에게 없는 사실이 간다.
    ⚠ 줄마다 `{표} · {매체}`를 붙인다. 안 붙이면 한 블록에 EPN 표와 MIX 표가 있을 때
      `TikTok : 유지`와 `TikTok : 축소 검토`가 나란히 찍혀 자기모순이 된다.
    """
    if not entries:
        return []
    lines = ["", "추후 제작 인사이트"]
    proposals = []
    for title, card in entries:
        judged = operating_verdict(card)
        who = f"{title} · {card['media']}" if title else card["media"]
        if not judged["verdict"]:
            continue
        # 근거는 **판정에 실제로 쓴 지표**만. 전부 나열하면 위 본문과 통째로
        # 중복되고(실측 4지표 × 매체), 실제 리포트는 근거를 짧게 쓴다.
        table = card.get("judge", card["table"])
        used = [judged["front"]["used"], judged["back"]["used"]]
        facts = [metric_line(row) for _, row in table.iterrows()
                 if row["metric"] in used and pd.notna(row.get("delta"))]
        if facts:
            lines.append(f"- {who} : " + " / ".join(facts) + "으로 확인되고 있음")
        if judged["action_ok"]:
            proposals.append(f">> {who} — {judged['action']}")
        else:
            proposals.append(f">> {who} — 표본 확보 후 재판단 제안 "
                             f"(설치 {judged['installs']:,.0f}건)")
    if not proposals:
        return []
    lines.append("")
    for line in proposals:
        lines.append(line)
        lines.append("- ex)")
    return lines


def lines_to_html(lines: list[str]) -> str:
    """Quill에 그대로 넣을 HTML. **빈 줄 규칙을 여기 한 곳에만 둔다.**"""
    return "".join("<p><br></p>" if not line.strip() else f"<p>{line}</p>"
                   for line in lines)


def block_lines(sections: list[dict], month: int, pool: float = 0.0) -> list[str]:
    """주제(블록) 하나의 초안 전체. **문서 모양을 정하는 곳은 여기 한 곳이다.**

    `sections`는 진입점이 만든 데이터 묶음이다(화면 상태를 여기까지 끌고 오지 않는다):

        {"kind": "contrast", "title": str, "subject": df, "rest": df,
         "values": list | None}
        {"kind": "swing",    "scope": df, "links": dict}
        {"kind": "plain",    "scope": df, "whole": df, "label": str, "links": dict}

    규칙:
      · 대조군 섹션이 하나라도 있으면 그것이 서사를 만들고, `추후 제작 인사이트`는
        **블록 끝에 한 번만** 붙는다.
      · 대조군이 없으면 예전 경로(`draft_sections`, 전체 기준)를 쓴다.
      · 섹션 하나가 실패하면 그 섹션만 건너뛰고 **사실을 문장으로 남긴다** —
        조용히 빠지면 초안에 표 하나가 없어진 걸 아무도 모른다.
    """
    lines: list[str] = []
    entries: list[tuple[str, dict]] = []
    failed: list[str] = []
    has_contrast = any(s["kind"] == "contrast" for s in sections)

    for section in sections:
        title = section.get("title") or section.get("label") or ""
        try:
            if section["kind"] == "contrast":
                subject, rest = section["subject"], section["rest"]
                cards = contrast_by_media(subject, rest, section.get("values"))
                spend = float(subject["cost"].fillna(0).sum())
                count = int(subject["ad"].nunique()) if "ad" in subject else 0
                scale = f"소재 {count:,}개 · 소진 ₩{spend:,.0f}"
                if pool:
                    # ⚠ 분모를 문장에 못 박는다. `named_overview`는 구글(소재 단위가
                    #   없다)을 뺀 프레임이라 1번 섹션 총액보다 작다 — 8월 실측
                    #   ₩213,613,512 vs 전체 ₩325,793,438(65.6%). "집행 전체의 X%"라고
                    #   쓰면 광고주가 1번 표와 대조하며 1.5배 어긋난 숫자를 본다.
                    scale += (f" (소재 태깅된 집행 ₩{pool:,.0f} 중 "
                              f"{spend / pool:.2%})")
                lines += contrast_lines(cards, month, title, scale)
                entries += [(title, card) for card in cards]
            elif section["kind"] == "swing":
                lines += swing_lines(section["scope"], section.get("links"))
            elif section["kind"] == "plain" and not has_contrast:
                body, tail = draft_sections(
                    section["scope"], section["whole"], month,
                    label=section.get("label", ""), links=section.get("links"))
                lines += body + tail
        except Exception as error:  # noqa: BLE001
            failed.append(f"{title or '표'} ({error})")

    if has_contrast:
        lines += next_step_lines(entries)
    for item in failed:
        lines.append(f"※ 초안을 만들지 못한 표 : {item}")
    return lines
