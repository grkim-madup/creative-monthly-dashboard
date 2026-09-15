"""표(뷰) 하나의 저장 형식과 **위젯 → 저장** 변환.

**왜 진입점에서 빼냈나.** 이 로직은 편집기의 심장인데 `creative_dashboard.py` 안에 있어서
**어떤 테스트도 검증하지 못했다** — 진입점은 import하면 화면을 그리기 시작해서 테스트가
부를 수 없다. `spend_pool`·`pick_best_worst`를 `creative_data.py`로 옮긴 것과 같은 이유다
(그때는 테스트가 같은 구현을 복사해 두고 있었고, 복사본이 통과해도 진짜 코드는 검증되지
않았다).

`view_from_widgets`는 `st.session_state`를 **인자로 받는다.** Streamlit을 몰라야 테스트가
평범한 dict를 넘길 수 있다.
"""

from __future__ import annotations

import copy
from uuid import uuid4

from creative_data import (
    DEFAULT_PIVOT_ROWS,
    METRIC_COLUMNS,
    normalize_rows,
    title_level_allowed,
)

#: 빈 뷰를 만들 때의 기본값. 저장된 뷰에 없는 키는 여기서 채운다 — 나중에 필드를
#: 늘려도 예전에 저장된 뷰가 KeyError로 화면을 죽이지 않는다.
VIEW_DEFAULTS = {
    "label": "",
    #: 표 종류는 셋이다 — `pivot`(행/값/필터) · `compare`(기간 비교) ·
    #: `google`(구글 애셋, 2026-09-16 추가). 예전의 `aggregate`/`list` 구분은
    #: 사라졌다 — 행에 소재명을 넣으면 목록, 빼면 집계표다.
    "kind": "pivot",
    #: 행 = 묶는 기준. 기간 비교에서는 이 자리를 `periods`가 쓴다.
    "rows": [],
    #: 값 = 보여줄 지표. 비우면 기본 세트 — 빈 목록을 '0개'로 읽으면 표가 사라진다.
    "values": [],
    #: 필터 = 표에 담을 범위. **값을 좁히는 자리는 여기 하나뿐이다.**
    "filters": {},
    #: 대조군 비교 — 켜면 "동일 조건에서 이 소재군을 제외한 나머지"와 매체별로 견준다.
    "contrast": False,
    #: 대조 기준으로 삼을 필터 하나. 비우면 `default_contrast_field`가 고른다.
    "contrast_field": "",
    #: 표 위에 소재 썸네일 줄을 보여줄지.
    "thumbs": False,
    #: **소재명 규칙이 안 맞아 필터로는 안 잡히는 소재**를 이 그룹에 손으로 넣는 자리.
    #: 규리님(2026-09-09): *"비교대상이 되는 그 그룹에 소재명 룰이 안 맞아서 수기로
    #: 추가해야 될 때 사용하는 용도"*. 필터의 보조라서 화면에서도 필터에 붙어 있다.
    "include_ads": [],
    #: 기간 비교 뷰용. `metrics`는 편집 위젯이 없어 늘 기본값이었다 — 지금은 `values`를
    #: 쓴다. 필드는 지우지 않는다(되돌릴 수 있게).
    "periods": [], "metrics": [],
    #: 그래프는 걷어냈다(7·8월 실사용 0%, 규리님 확정 2026-09-09). 읽는 곳이 없지만
    #: **저장된 값은 지우지 않는다** — 되돌리려면 위젯만 다시 그리면 된다.
    "chart_kind": "", "metric": "CPI", "top_n": 0,
    #: ── 구글 애셋 표(`kind == "google"`) 전용 ──────────────────────────────
    #: ⚠ **`rows`/`values`/`filters`를 재사용하지 않는다.** 그 키들은
    #:   `render_block_kpis`·`insight_button`·`filtered_scope`가 **`named_overview`
    #:   (메타·틱톡 프레임) 기준으로** 읽는다. 같은 키에 구글 축을 담으면 구글
    #:   필터가 메타 프레임에 걸린다. 키를 `g_*`로 분리하면 "구글 축이 메타 프레임에
    #:   닿지 않는다"가 **구조적으로 참**이 된다.
    "g_rows": [], "g_values": [], "g_filters": {},
    #: 영상·이미지만 볼지. 텍스트 애셋(광고 제목·설명·앱 딥 링크)은 `asset_name`이
    #: 전부 `--`라 소재로 볼 수 없다.
    "g_creative_only": True,
    #: ── 작품 단위 집계(`kind == "pivot"` 전용) ────────────────────────────
    #: 켜면 `named_overview`(메타·틱톡) 대신 `overview`를 쓴다 = **구글이 들어온다.**
    #: 구글은 `Media_RAW`에 `ad == "-"`로 들어와서 소재 단위 프레임에서 빠져 있는데,
    #: 장르는 소재가 아니라 작품 속성이라 소재명이 없어도 집계된다(광고주 요청
    #: 2026-09-16 — 구글이 소진의 1/3이라 빼면 답이 반쪽이다).
    #: ⚠ 기본값 False. 기존에 저장된 표는 한 줄도 안 바뀐다.
    #: ⚠ 행·필터에 소재 단위 축이 섞이면 `view_with_defaults`가 **강제로 끈다** —
    #:   `title_level_allowed` 참고.
    "title_level": False,
    #: 마지막 행 축을 **그룹 안에서** 이 지표 순으로 줄세운다(`rank_within_groups`).
    #: 비우면 예전 그대로 소진액 내림차순이다 — 기존 표는 한 줄도 안 바뀐다.
    #: 장르 표가 이걸 쓴다: `[매체, OS, 장르]`를 매체·OS로 묶고 그 안에서 CPI 순.
    "rank_by": "",
}

#: 예전 형식의 필드 — 지우지 않는다. 되돌리려면 코드만 되돌리면 되게 남겨 둔다.
LEGACY_VIEW_FIELDS = ("axis", "axis_values", "conditions", "columns", "chart",
                      "show_table")


def empty_periods() -> list[dict]:
    return [{"label": "", "months": []}, {"label": "", "months": []}]


def migrate_view(view: dict) -> dict:
    """예전 뷰(`axis`/`conditions`/`columns`)를 행/값/필터로 옮긴다.

    **읽을 때만 변환하고 저장된 원본은 건드리지 않는다** — `promote_views`와 같은 방식.
    다음 저장 때 새 형식으로 굳는다.
    """
    if view.get("rows") or view.get("kind") == "compare":
        return view

    legacy_kind = view.get("kind")
    if legacy_kind not in ("aggregate", "list"):
        return view

    columns = list(view.get("columns") or [])
    conditions = dict(view.get("conditions") or {})
    axis = view.get("axis") or "creative_type"

    # 행: 목록이면 소재명, 집계면 축. 매체는 예전에 컬럼 선택이 결정했다.
    head = "ad" if legacy_kind == "list" else axis
    rows = [{"field": head}]
    if "media" in (columns or DEFAULT_PIVOT_ROWS):
        rows.append({"field": "media"})

    values = [c for c in columns if c in METRIC_COLUMNS]
    # 예전 축 값은 이제 **필터**로 간다 — 좁히는 자리가 하나뿐이므로.
    filters = dict(conditions)
    narrowed = list(view.get("axis_values") or conditions.get(axis) or [])
    if legacy_kind == "aggregate" and narrowed:
        filters[axis] = narrowed

    moved = dict(view)
    moved.update({"kind": "pivot", "rows": rows, "values": values,
                  "filters": filters, "include_ads": []})
    return moved


def view_with_defaults(view: dict) -> dict:
    """저장된 뷰를 화면이 쓸 완전한 dict로. 없는 키는 기본값으로 채운다.

    ⚠ `id`를 여기서 발급하면 **리런마다 새 uuid가 나온다** — 부르는 쪽이 저장된 id를
      넘겨야 `view_key`가 안 흔들린다(위젯 상태·셀 강조가 그 키에 매달려 있다).
    """
    merged = copy.deepcopy(VIEW_DEFAULTS)
    source = migrate_view(dict(view or {}))
    merged.update({k: v for k, v in source.items()
                   if v is not None and k not in LEGACY_VIEW_FIELDS})
    merged["rows"] = normalize_rows(merged["rows"])
    if merged["kind"] == "google":
        # 구글 표에는 대조군·썸네일·소재 추가·그래프가 없다. 저장된 값이 남아 있어도
        # 화면이 그걸 보고 메타 경로로 새지 않게 여기서 못 박는다.
        merged.update({"contrast": False, "contrast_field": "", "thumbs": False,
                       "include_ads": [], "chart_kind": "", "title_level": False})
    # ⚠ **작품 단위 집계는 조건을 코드로 건다.** 소재 단위 축이 하나라도 섞이면 구글
    #   행이 전부 `미분류` 한 줄이 되어 표에 가짜 버킷이 생긴다(`883600f`와 같은 사고).
    #   화면에서 토글을 감추는 것만으로는 부족하다 — 축을 나중에 바꾸면 저장된 True가
    #   그대로 남기 때문에, 읽는 쪽에서 매번 다시 판정한다.
    if merged["title_level"] and not title_level_allowed(merged["rows"], merged["filters"]):
        merged["title_level"] = False
    # 대조군은 "같은 범위에서 이 소재군을 뺀 나머지"라 소재 단위 프레임을 전제한다.
    if merged["title_level"]:
        merged.update({"contrast": False, "contrast_field": "", "thumbs": False,
                       "include_ads": []})
    if not merged.get("id"):
        merged["id"] = uuid4().hex[:6]
    return merged


def view_from_widgets(view: dict, view_key: str, session) -> dict:
    """저장할 뷰를 **화면 위젯의 현재 값**으로 조립한다.

    편집기는 표 바로 위에서 그리는데 저장 버튼은 그보다 위에 있다. 위젯 값은 세션에
    남아 있으므로, 저장 시점에 그 세션 값을 읽으면 순서에 상관없이 항상 화면과 같은
    것이 저장된다.

    **세션 키가 없으면 저장된 값을 그대로 유지한다.** 그래서 위젯을 화면에서 걷어내도
    그 필드를 잃지 않는다 — 그래프를 없애면서 `chart_kind`·`metric`·`top_n`이 안전한
    이유가 이것이다.

    `session`은 `st.session_state`지만 **여기서는 그냥 dict처럼 읽는다** — Streamlit을
    모르는 함수여야 테스트가 평범한 dict를 넘길 수 있다.
    """
    merged = view_with_defaults(view)

    def take(key, fallback):
        value = session.get(key)
        return fallback if value is None else value

    merged["label"] = take(f"vlabel_{view_key}", merged["label"])
    merged["kind"] = take(f"vkind_{view_key}", merged["kind"])

    row_fields = take(f"pvrows_{view_key}", [r["field"] for r in merged["rows"]])
    merged["rows"] = normalize_rows([{"field": f} for f in row_fields])
    merged["values"] = list(take(f"pvvals_{view_key}", merged["values"]))
    merged["include_ads"] = list(take(f"pvads_{view_key}", merged["include_ads"]))
    merged["contrast"] = bool(take(f"pvct_{view_key}", merged["contrast"]))
    merged["contrast_field"] = str(
        take(f"pvctf_{view_key}", merged["contrast_field"]) or "")
    merged["thumbs"] = bool(take(f"pvth_{view_key}", merged["thumbs"]))
    merged["title_level"] = bool(take(f"pvtl_{view_key}", merged["title_level"]))
    merged["rank_by"] = str(take(f"pvrank_{view_key}", merged["rank_by"]) or "")

    # 기간 비교의 기간 두 개. 위젯은 라벨·월을 따로 쓴다.
    periods = []
    for index in range(2):
        label = session.get(f"vperiod_label_{view_key}_{index}")
        months = session.get(f"vperiod_months_{view_key}_{index}")
        if label is None and months is None:
            saved = merged["periods"]
            periods.append(saved[index] if index < len(saved)
                           else {"label": "", "months": []})
            continue
        periods.append({"label": str(label or ""),
                        "months": [int(m) for m in (months or [])]})
    if any(p.get("label") or p.get("months") for p in periods):
        merged["periods"] = periods

    # 필터는 **구분 목록**이 무엇이 걸렸는지를 정한다. 값이 빈 구분은 아무것도 걸지
    # 않으므로 저장에서 빼고, 그래야 화면(빈 멀티셀렉트)과 저장이 어긋나지 않는다.
    filter_fields = take(f"pvfilters_{view_key}", list(merged["filters"] or {}))
    merged["filters"] = {
        f: list(take(f"pvfval_{view_key}_{f}", (merged["filters"] or {}).get(f) or []))
        for f in filter_fields
        if take(f"pvfval_{view_key}_{f}", (merged["filters"] or {}).get(f) or [])
    }

    # ── 구글 애셋 표(2026-09-16) ─────────────────────────────────────────────
    # 위젯 키를 `gv*`로 따로 쓴다 — 피벗 키를 재사용하면 한 블록에서 표 종류를 바꿀 때
    # 메타 축이 구글 표에 그대로 남는다. 저장 키도 `g_*`로 분리해 구글 축이
    # `named_overview`(메타·틱톡 프레임)를 읽는 코드에 닿지 않게 한다.
    g_rows = take(f"gvrows_{view_key}",
                  [r["field"] if isinstance(r, dict) else r
                   for r in (merged.get("g_rows") or [])])
    merged["g_rows"] = [{"field": f} for f in g_rows]
    merged["g_values"] = list(take(f"gvvals_{view_key}", merged.get("g_values") or []))
    merged["g_creative_only"] = bool(
        take(f"gvonly_{view_key}", merged.get("g_creative_only", True)))

    g_filter_fields = take(f"gvfilters_{view_key}", list(merged.get("g_filters") or {}))
    merged["g_filters"] = {
        f: list(take(f"gvfval_{view_key}_{f}", (merged.get("g_filters") or {}).get(f) or []))
        for f in g_filter_fields
        if take(f"gvfval_{view_key}_{f}", (merged.get("g_filters") or {}).get(f) or [])
    }

    # 저장되는 값도 정직해야 한다 — 토글을 켠 뒤 소재 단위 축을 추가하면 화면은
    # `view_with_defaults`가 다시 판정해 끄지만, 저장본에 True가 남아 있으면 나중에
    # 축을 되돌렸을 때 켠 적 없는 토글이 켜져 있다.
    if merged["title_level"] and not title_level_allowed(merged["rows"], merged["filters"]):
        merged["title_level"] = False
    return merged
