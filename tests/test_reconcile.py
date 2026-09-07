"""데이터 적합성 점검 규칙을 고정한다.

이 점검이 조용히 틀리면 **"숫자가 맞다"는 잘못된 확인**을 주게 된다 — 확인 도구가 틀리는
것은 확인을 안 하는 것보다 나쁘다. 판정 문턱과 단계 구성을 여기서 못 박는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import reconcile

HEADER = ["월", "매체명", "UA / non-UA 구분", "OS 구분", "최종 AD",
          "impression", "click", "cost (마크업 포함)", "total install"]


#: 테스트를 읽기 쉽게 하는 별칭. 실제 헤더 이름(`cost (마크업 포함)`)을 매번 적으면
#: 오타 하나로 값이 기본값으로 조용히 떨어진다 — 실제로 이 파일을 처음 쓸 때 그렇게 됐다.
ALIASES = {"cost": "cost (마크업 포함)", "install": "total install", "month": "월",
           "media": "매체명", "ua": "UA / non-UA 구분", "os": "OS 구분", "ad": "최종 AD"}


def sheet(rows: list[dict]) -> list[list[str]]:
    """Media_RAW 2차원 값. 안 준 값은 기본값으로 둔다."""
    base = {"월": "8", "매체명": "TikTok", "UA / non-UA 구분": "UA", "OS 구분": "AOS",
            "최종 AD": "1234_작품_VID_Madup_Highlight_9X16_1",
            "impression": "0", "click": "0", "cost (마크업 포함)": "0",
            "total install": "0"}
    out = [HEADER]
    for row in rows:
        translated = {ALIASES.get(k, k): v for k, v in row.items()}
        unknown = set(translated) - set(HEADER)
        assert not unknown, f"헤더에 없는 컬럼: {unknown}"   # 오타를 조용히 넘기지 않는다
        merged = {**base, **translated}
        out.append([str(merged[c]) for c in HEADER])
    return out


def parsed_frame(rows: list[dict]) -> pd.DataFrame:
    base = {"month": 8, "media": "TikTok", "ua_type": "UA", "os": "AOS",
            "ad": "1234_작품_VID_Madup_Highlight_9X16_1", "format": "VID",
            "cost": 0.0, "impression": 0.0, "click": 0.0, "total install": 0.0}
    return pd.DataFrame([{**base, **r} for r in rows])


def steps_by_label(steps: list[dict]) -> dict:
    return {s["label"][0]: s for s in steps}


# ------------------------------------------------------------------------- 지문

def test_지문은_월_매체_ua_os_소재명유무로_묶는다():
    fp = reconcile.build_fingerprint(sheet([
        {"cost": "100", "total install": "5"},
        {"cost": "200", "total install": "7"},
        {"매체명": "Meta", "cost": "50", "total install": "1"},
    ]))
    keys = {(r["media"], r["has_ad"]): r for r in fp["by_key"]}
    assert keys[("TikTok", True)]["rows"] == 2
    assert keys[("TikTok", True)]["cost"] == 300
    assert keys[("TikTok", True)]["install"] == 12
    assert keys[("Meta", True)]["cost"] == 50


def test_소재명이_비면_has_ad가_False():
    fp = reconcile.build_fingerprint(sheet([{"최종 AD": ""}, {"최종 AD": "  "}]))
    assert all(r["has_ad"] is False or r["has_ad"] == 0 for r in fp["by_key"])


def test_매체명을_정규화한다():
    """`Facebook`은 화면에서 `Meta`다 — 지문이 원본 표기 그대로면 매체 필터가 어긋난다."""
    fp = reconcile.build_fingerprint(sheet([{"매체명": "Facebook", "cost": "10"}]))
    assert fp["by_key"][0]["media"] == "Meta"


def test_월을_못_읽는_행은_버린다():
    fp = reconcile.build_fingerprint(sheet([{"월": ""}, {"월": "8", "cost": "10"}]))
    assert sum(r["rows"] for r in fp["by_key"]) == 1


def test_빈_시트도_지문을_만든다():
    fp = reconcile.build_fingerprint([])
    assert fp["by_key"] == [] and fp["sheet_rows"] == 0
    assert fp["version"] == reconcile.FINGERPRINT_VERSION


def test_지문은_파서를_쓰지_않는다():
    """같은 파서를 쓰면 파서가 틀렸을 때 지문도 같이 틀려 점검이 무의미해진다.

    `tools/audit_pivot.py`가 정답 프레임을 손으로 다시 만드는 것과 같은 이유다.
    """
    import ast

    tree = ast.parse(Path(reconcile.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "parse_raw_values" not in imported
    assert "attach_creative_attributes" not in imported
    # 부를 수도 없어야 한다(주석·문서 문자열에 이름이 나오는 것은 괜찮다)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "parse_raw_values" not in called


def test_지문_저장과_읽기(tmp_path, monkeypatch):
    monkeypatch.setattr(reconcile, "CACHE_DIR", tmp_path)
    fp = reconcile.build_fingerprint(sheet([{"cost": "10"}]), sheet_id="abc")
    reconcile.save_fingerprint(fp)
    assert reconcile.load_fingerprint("abc")["by_key"] == fp["by_key"]


def test_형식이_다른_지문은_안_읽는다(tmp_path, monkeypatch):
    """옛 지문을 새 코드로 읽으면 조용히 틀린 표가 나온다 — 없는 것으로 취급한다."""
    monkeypatch.setattr(reconcile, "CACHE_DIR", tmp_path)
    path = reconcile.fingerprint_path("abc")
    path.write_text(json.dumps({"version": 0, "by_key": []}), encoding="utf-8")
    assert reconcile.load_fingerprint("abc") is None


def test_깨진_지문은_없는_것으로_본다(tmp_path, monkeypatch):
    monkeypatch.setattr(reconcile, "CACHE_DIR", tmp_path)
    reconcile.fingerprint_path("abc").write_text("{ 깨진", encoding="utf-8")
    assert reconcile.load_fingerprint("abc") is None


# ----------------------------------------------------------------------- 워터폴

def full_case():
    """8월 실측을 축소한 모양 — 각 단계가 하나씩 무언가를 덜어낸다."""
    values = sheet([
        {"cost": "1000", "total install": "10"},                       # 살아남는다
        {"매체명": "Apple Search Ads", "cost": "500", "total install": "5"},
        {"최종 AD": "", "cost": "0", "total install": "40"},            # 설치만 든 빈 행
        {"UA / non-UA 구분": "non-UA", "cost": "300", "total install": "2"},
        {"최종 AD": "9_작_IMG_M_SingleImage_1X1_1", "cost": "70", "total install": "3"},
    ])
    fp = reconcile.build_fingerprint(values)
    parsed = parsed_frame([
        {"cost": 1000.0, "total install": 10.0},
        {"ad": "9_작_IMG_M_SingleImage_1X1_1", "format": "IMG", "cost": 70.0,
         "total install": 3.0},
    ])
    scope = parsed  # 이 예시는 포맷 필터에서 아무것도 안 빠진다
    return fp, parsed, scope


def test_단계는_일곱_개_정해진_순서다():
    fp, parsed, scope = full_case()
    steps = reconcile.waterfall(fp, parsed, scope, 8)
    assert [s["label"][0] for s in steps] == ["①", "②", "③", "④", "⑤", "⑥", "⑦"]


def test_대상_외_매체는_의도된_제외():
    fp, parsed, scope = full_case()
    step = steps_by_label(reconcile.waterfall(fp, parsed, scope, 8))["②"]
    assert step["verdict"] == reconcile.VERDICT_INTENDED
    assert step["d_cost"] == -500
    assert "Apple Search Ads" in step["reason"]


def test_소재명_빈_행이_값을_들고_있으면_확인_필요():
    """8월에 설치 11,047건이 이 경로로 사라졌다 — 조용히 넘기면 안 되는 항목이다."""
    fp, parsed, scope = full_case()
    step = steps_by_label(reconcile.waterfall(fp, parsed, scope, 8))["③"]
    assert step["verdict"] == reconcile.VERDICT_CHECK
    assert step["d_install"] == -40


def test_소재명_빈_행이_비어_있으면_의도된_제외():
    values = sheet([{"cost": "1000"}, {"최종 AD": "", "cost": "0",
                                       "total install": "0"}])
    fp = reconcile.build_fingerprint(values)
    parsed = parsed_frame([{"cost": 1000.0}])
    step = steps_by_label(reconcile.waterfall(fp, parsed, parsed, 8))["③"]
    assert step["verdict"] == reconcile.VERDICT_INTENDED


def test_구글은_소재명이_비어도_안_버린다():
    """구글은 소재 단위 태깅이 아예 없다 — 버리면 매체 하나가 통째로 사라진다."""
    fp = reconcile.build_fingerprint(sheet([
        {"매체명": "Google", "최종 AD": "", "cost": "900", "total install": "9"},
    ]))
    parsed = parsed_frame([{"media": "Google", "ad": "-", "format": None,
                            "cost": 900.0, "total install": 9.0}])
    step = steps_by_label(reconcile.waterfall(fp, parsed, parsed, 8))["③"]
    assert step["d_cost"] == 0
    assert step["cost"] == 900


def test_non_UA는_의도된_제외():
    fp, parsed, scope = full_case()
    step = steps_by_label(reconcile.waterfall(fp, parsed, scope, 8))["④"]
    assert step["verdict"] == reconcile.VERDICT_INTENDED
    assert step["d_cost"] == -300


def test_코호트_단계는_설치만_늘어야_한다():
    """`load_media_raw`가 파싱과 코호트 대체를 함께 한다 — 설치는 늘고 소진은 그대로다."""
    fp, parsed, scope = full_case()
    parsed = parsed.copy()
    parsed.loc[0, "total install"] = 99.0        # 코호트가 채워 넣은 값
    step = steps_by_label(reconcile.waterfall(fp, parsed, parsed, 8))["⑤"]
    assert step["verdict"] == reconcile.VERDICT_REPLACED
    assert step["d_cost"] == 0
    assert step["d_install"] > 0


def test_코호트_단계에서_소진이_움직이면_확인_필요():
    """코호트는 전환 지표만 채운다 — 소진이 움직였다면 파싱이 값을 바꾼 것이다."""
    fp, parsed, scope = full_case()
    parsed = parsed.copy()
    parsed.loc[0, "cost"] = 999.0
    step = steps_by_label(reconcile.waterfall(fp, parsed, parsed, 8))["⑤"]
    assert step["verdict"] == reconcile.VERDICT_CHECK


def test_포맷_제외는_의도된_제외():
    fp, parsed, _ = full_case()
    scope = parsed[parsed["format"] == "VID"]
    step = steps_by_label(reconcile.waterfall(fp, parsed, scope, 8,
                                              formats=("VID",)))["⑥"]
    assert step["verdict"] == reconcile.VERDICT_INTENDED
    assert step["d_cost"] == -70


def test_마지막_단계에서_움직이면_확인_필요():
    """⑦에서 뭔가 달라지면 앞 단계로 설명되지 않는 차이다 — 가장 위험한 신호."""
    fp, parsed, _ = full_case()
    scope = parsed.iloc[:1]          # 화면이 이유 없이 한 줄을 잃었다
    step = steps_by_label(reconcile.waterfall(fp, parsed, scope, 8))["⑦"]
    assert step["verdict"] == reconcile.VERDICT_CHECK


def test_설명되면_마지막_단계는_일치():
    fp, parsed, scope = full_case()
    step = steps_by_label(reconcile.waterfall(fp, parsed, scope, 8))["⑦"]
    assert step["verdict"] == reconcile.VERDICT_MATCH


def test_다른_달은_섞이지_않는다():
    fp = reconcile.build_fingerprint(sheet([
        {"월": "7", "cost": "5000"}, {"월": "8", "cost": "100"},
    ]))
    parsed = parsed_frame([{"cost": 100.0}])
    steps = reconcile.waterfall(fp, parsed, parsed, 8)
    assert steps[0]["cost"] == 100


def test_그_달_데이터가_없어도_죽지_않는다():
    fp = reconcile.build_fingerprint(sheet([{"월": "7", "cost": "5000"}]))
    steps = reconcile.waterfall(fp, parsed_frame([]), parsed_frame([]), 8)
    assert steps[0]["cost"] == 0 and len(steps) == 7


# ------------------------------------------------------------------- 설치 격차

def test_설치_격차는_빈_행과_OS별_대조를_준다():
    fp, parsed, scope = full_case()
    gap = reconcile.install_gap(fp, scope, 8)
    assert gap["unnamed_rows"] == 1
    assert gap["unnamed_install"] == 40
    aos = next(r for r in gap["by_os"] if r["os"] == "AOS")
    assert aos["sheet"] == 13 and aos["screen"] == 13 and aos["delta"] == 0


def test_코호트가_채운_만큼_OS_차이로_보인다():
    fp, parsed, _ = full_case()
    scope = parsed.copy()
    scope["os"] = "iOS"
    scope["total install"] = [100.0, 0.0]
    gap = reconcile.install_gap(fp, scope, 8)
    ios = next(r for r in gap["by_os"] if r["os"] == "iOS")
    assert ios["screen"] == 100


# --------------------------------------------------------------------- 코호트 고아

def test_코호트에만_있고_RAW에_없는_소재를_찾는다():
    fp = reconcile.build_fingerprint(sheet([{"cost": "10"}]))
    fp["cohort"] = {"rows": 2, "by_key": [
        {"month": 8, "media": "Meta", "ad": "없는소재", "install": 7},
        {"month": 8, "media": "Meta", "ad": "있는소재", "install": 3},
    ]}
    parsed = parsed_frame([{"media": "Meta", "os": "iOS", "ad": "있는소재"}])
    orphans = reconcile.cohort_orphans(fp, parsed, 8)
    assert [o["ad"] for o in orphans] == ["없는소재"]
    assert orphans[0]["install"] == 7


def test_다른_달의_코호트는_안_본다():
    fp = reconcile.build_fingerprint(sheet([{"cost": "10"}]))
    fp["cohort"] = {"rows": 1, "by_key": [
        {"month": 7, "media": "Meta", "ad": "없는소재", "install": 7},
    ]}
    assert reconcile.cohort_orphans(fp, parsed_frame([]), 8) == []


def test_설치가_0인_코호트_행은_지문에_안_담는다():
    cohort = pd.DataFrame([
        {"month": 8, "media": "Meta", "ad": "a", "total install": 0.0},
        {"month": 8, "media": "Meta", "ad": "b", "total install": 5.0},
    ])
    fp = reconcile.build_fingerprint(sheet([{"cost": "10"}]), cohort=cohort)
    assert [r["ad"] for r in fp["cohort"]["by_key"]] == ["b"]


# --------------------------------------------------------------------- 요약 / 판정

def test_설명되지_않는_차이가_없으면_0원이라고_말한다():
    fp, parsed, scope = full_case()
    line = reconcile.summary_line(reconcile.waterfall(fp, parsed, scope, 8))
    assert "설명되지 않는 차이 ₩0" in line


def test_설명되지_않는_차이가_있으면_경고한다():
    fp, parsed, _ = full_case()
    scope = parsed.iloc[:1]
    line = reconcile.summary_line(reconcile.waterfall(fp, parsed, scope, 8))
    assert line.startswith("⚠")


@pytest.mark.parametrize("orphans, unnamed, expected", [
    ([], 0, False),
    ([{"media": "Meta", "ad": "x", "install": 1}], 0, True),
    ([], 40, True),
])
def test_확인_필요_판정(orphans, unnamed, expected):
    steps = [{"verdict": reconcile.VERDICT_INTENDED}]
    assert reconcile.has_issues(steps, {"unnamed_install": unnamed},
                               orphans) is expected


def test_단계에_확인_필요가_있으면_전체가_확인_필요():
    steps = [{"verdict": reconcile.VERDICT_CHECK}]
    assert reconcile.has_issues(steps, {"unnamed_install": 0}, []) is True


def test_화면_고정_조건은_진입점과_같아야_한다():
    """진입점을 import할 수 없어 값을 복제했다 — 어긋나면 점검이 딴 걸 재게 된다.

    ⚠ 진입점 파일명을 못 박지 않는다. madup.app 배포판은 `app.py`이고, 이름을 하나로
      고정하면 그 폴더에서 테스트가 깨져 배포가 막힌다(2026-09-08에 두 번 겪었다).
    """
    root = Path(reconcile.__file__).parent
    entrypoints = [root / name for name in ("creative_dashboard.py", "app.py")]
    found = [p for p in entrypoints if p.exists()]
    assert found, "진입점을 찾지 못했습니다"

    for path in found:
        source = path.read_text(encoding="utf-8")
        assert 'media_selection = [m for m in ("TikTok", "Meta", "Google")' in source
        assert 'ua_selection = ["UA"]' in source
        assert 'format_selection = ["VID", "IMG", "GIF"]' in source


def _audit_source() -> str:
    """`tools/audit_reconcile.py` 원문.

    ⚠ **배포 복사본에는 `tools/` 가 없다** — 동기화 스크립트가 최상위 `*.py` 와
      `tests/` 만 복사한다. 그대로 읽으면 배포 전 pytest가 `FileNotFoundError`로
      막힌다(2026-09-08 실제로 막혔다). 저장소 위생 검사라 없으면 건너뛴다.
    """
    path = Path(reconcile.__file__).parent / "tools" / "audit_reconcile.py"
    if not path.exists():
        pytest.skip("배포 복사본에는 tools/ 가 없습니다 — 저장소에서만 검사합니다")
    return path.read_text(encoding="utf-8")


def test_점검_도구가_시트를_하드코딩하지_않는다():
    """화면은 `app_settings`의 링크를 읽고 그 값은 사이드바에서 바뀐다.

    도구가 시트를 박아 두면 **딴 시트를 재고 "숫자가 맞다"고 보고한다** — 실제로 그렇게
    됐다(옛 시트 ₩314,822,890 vs 화면의 새 시트 ₩321,209,673). 확인 도구가 틀리는 것은
    확인을 안 하는 것보다 나쁘다.
    """
    source = _audit_source()
    assert 'app_settings.get("sheet_url"' in source, "저장된 링크를 읽어야 한다"
    # 폴백 상수 하나는 있어도 되지만, 그걸 그대로 쓰는 경로가 있으면 안 된다.
    assert "load_media_raw(DEFAULT_SHEET)" not in source
    assert "fetch_fingerprint(DEFAULT_SHEET" not in source


def test_점검_도구가_OS_필터를_진입점과_같이_쓴다():
    """`notna()`만으로는 `os == "All"`이 통과한다 — 진입점은 `os_values`로 뺀다."""
    source = _audit_source()
    assert "os_values(" in source
    assert 'frame["os"].notna()' not in source
