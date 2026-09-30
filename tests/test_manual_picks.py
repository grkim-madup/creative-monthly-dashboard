# -*- coding: utf-8 -*-
"""우수·저조 수기 지정.

자동 규칙이 팀원 판단과 어긋나는 동안에도 리포트가 **사람 판단대로** 나가야 한다.
"""
import pandas as pd
import pytest

import manual_picks


@pytest.fixture(autouse=True)
def local_backend(tmp_path, monkeypatch):
    """실제 시트·Firestore에 절대 닿지 않게 로컬 파일로 묶는다."""
    monkeypatch.setattr(manual_picks, "PICKS_DIR", tmp_path)
    monkeypatch.setattr(manual_picks.store, "is_firestore", lambda: False)
    monkeypatch.setattr(manual_picks.google_sheets_writer, "configured",
                        lambda: False)


def table(*ads):
    return pd.DataFrame({"ad": list(ads), "cost": [1.0] * len(ads)})


class TestKeys:
    def test_key_carries_the_table_identity(self):
        """같은 소재가 표마다 다르게 지정된다 — 실제 팀원 픽이 그랬다."""
        a = manual_picks.row_key("AOS", "D0 coin", "소재A")
        b = manual_picks.row_key("iOS", "D0 coin", "소재A")
        c = manual_picks.row_key("AOS", "total install", "소재A")
        assert len({a, b, c}) == 3

    def test_round_trip(self):
        key = manual_picks.row_key("AOS", "total install", "9981_A_9X16_1-KR")
        assert manual_picks.split_key(key) == ("AOS", "total install",
                                               "9981_A_9X16_1-KR")

    def test_broken_key_is_ignored(self):
        assert manual_picks.split_key("이상한키") is None


class TestSaveLoad:
    def test_save_then_read_back(self):
        ok, reason = manual_picks.save(8, "AOS", "total install", "소재A", "best")
        assert ok and reason is None
        assert manual_picks.for_table(8, "AOS", "total install") == {"소재A": "best"}

    def test_other_tables_are_untouched(self):
        manual_picks.save(8, "AOS", "total install", "소재A", "best")
        assert manual_picks.for_table(8, "iOS", "total install") == {}
        assert manual_picks.for_table(8, "AOS", "D0 coin") == {}

    def test_months_are_separate(self):
        manual_picks.save(8, "AOS", "total install", "소재A", "best")
        assert manual_picks.for_table(7, "AOS", "total install") == {}

    def test_none_removes_the_pick(self):
        manual_picks.save(8, "AOS", "total install", "소재A", "best")
        manual_picks.save(8, "AOS", "total install", "소재A", None)
        assert manual_picks.for_table(8, "AOS", "total install") == {}

    def test_unknown_verdict_is_refused(self):
        ok, reason = manual_picks.save(8, "AOS", "total install", "소재A", "좋음")
        assert not ok and "좋음" in reason

    def test_save_reports_failure(self, monkeypatch):
        """결과를 버리면 실패해도 화면은 저장된 것처럼 보인다(overrides에서 겪었다)."""
        monkeypatch.setattr(manual_picks.store, "is_firestore", lambda: True)
        monkeypatch.setattr(manual_picks.fs_store, "write_pick",
                            lambda *a, **k: (False, "쿼터 초과"))
        ok, reason = manual_picks.save(8, "AOS", "total install", "소재A", "best")
        assert not ok and reason == "쿼터 초과"

    def test_read_error_does_not_wipe(self, monkeypatch):
        """읽기 실패를 '지정 없음'으로 뭉개면 그 위에 빈 값을 저장하게 된다."""
        monkeypatch.setattr(manual_picks.store, "is_firestore", lambda: True)
        monkeypatch.setattr(manual_picks.fs_store, "read_picks",
                            lambda month: ("error", {}, "끊김"))
        assert manual_picks.load(8) == {}


class TestApply:
    def test_manual_replaces_the_automatic_picks(self):
        """섞으면 5~6줄이 칠해져 무엇이 사람 판단인지 알 수 없다."""
        manual_picks.save(8, "AOS", "total install", "소재B", "best")
        auto_best, auto_worst = {0: "CPI"}, {2: "CPI"}
        best, worst = manual_picks.apply(
            table("소재A", "소재B", "소재C"), 8, "AOS", "total install",
            auto_best, auto_worst)
        assert list(best) == [1]          # 소재B
        assert worst == {}

    def test_reason_is_a_real_column(self):
        """사유 자리에 문구를 넣으면 소비하는 쪽이 KeyError로 죽는다 —
        `df.loc[index, 값]`으로 쓰기 때문이다(2026-09-08 배포판 사고)."""
        manual_picks.save(8, "AOS", "total install", "소재B", "worst")
        frame = table("소재A", "소재B")
        _best, worst = manual_picks.apply(
            frame, 8, "AOS", "total install", {}, {})
        assert list(worst) == [1]
        assert worst[1] in frame.columns

    def test_no_picks_keeps_the_automatic_result(self):
        auto_best, auto_worst = {0: "CPI"}, {1: "CPI"}
        best, worst = manual_picks.apply(
            table("소재A", "소재B"), 8, "AOS", "total install",
            auto_best, auto_worst)
        assert (best, worst) == (auto_best, auto_worst)

    def test_pick_outside_the_table_is_ignored(self):
        """정렬 기준을 바꿔 그 소재가 TOP N에서 빠지면 칠할 자리가 없다."""
        manual_picks.save(8, "AOS", "total install", "표에없는소재", "best")
        best, worst = manual_picks.apply(
            table("소재A"), 8, "AOS", "total install", {}, {})
        assert best == {} and worst == {}

    def test_empty_table_is_safe(self):
        assert manual_picks.apply(pd.DataFrame(), 8, "AOS", "x", {}, {}) == ({}, {})


def test_screen_passes_the_table_identity():
    """진입점은 import할 수 없으니 소스로 확인한다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    entry = next((root / n for n in ("creative_dashboard.py", "app.py")
                  if (root / n).exists()))
    source = entry.read_text(encoding="utf-8")
    assert "manual_picks.apply(" in source
    assert "os_name=os_name," in source and "month=month," in source


# ---------------------------------------------------------------- 회귀: 배포판 사망

def test_지정값은_표에_실제로_있는_컬럼이다(tmp_path, monkeypatch):
    """소비하는 쪽이 이 값을 `df.loc[index, 값]`으로 쓴다.

    예전에는 `"수기 지정"`이라는 **문구**를 넣어서, 썸네일 카드가 KeyError로 죽고
    **배포판 2번 섹션이 AOS 표에서 멈췄다**(2026-09-08 실제 사고).
    """
    import pandas as pd

    import manual_picks

    monkeypatch.setattr(manual_picks, "PICKS_DIR", tmp_path)
    table = pd.DataFrame([
        {"ad": "a", "media": "Meta", "cost": 1_000_000,
         "total install": 100, "CPI": 10_000},
        {"ad": "b", "media": "Meta", "cost": 2_000_000,
         "total install": 200, "CPI": 10_000},
    ])
    manual_picks.save(8, "AOS", "total install", "a", manual_picks.BEST)
    manual_picks.save(8, "AOS", "total install", "b", manual_picks.WORST)

    best, worst = manual_picks.apply(table, 8, "AOS", "total install", {}, {})
    assert best and worst
    for column in list(best.values()) + list(worst.values()):
        assert column in table.columns, column


def test_정렬기준이_표에_없으면_대체_컬럼을_쓴다():
    import pandas as pd

    import manual_picks

    table = pd.DataFrame([{"ad": "a", "cost": 1, "CPI": 2}])
    assert manual_picks.label_column(table, "D0 coin") == "CPI"
    assert manual_picks.label_column(table, "cost") == "cost"
    assert manual_picks.label_column(pd.DataFrame(), "cost") == ""


def test_카드_렌더가_없는_컬럼에도_죽지_않는다():
    """진입점은 import할 수 없으니 소스를 훑어 확인한다."""
    import pathlib

    for name in ("creative_dashboard.py", "app.py"):
        path = pathlib.Path(__file__).resolve().parent.parent / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert 'df.loc[idx, column] if column in df.columns' in source, name


# ------------------------------------------------- 구글 표 (식별자가 URL)

def test_구글_키는_메타틱톡과_공간이_나뉜다():
    assert manual_picks.google_os("iOS") == "google:iOS"
    parts = manual_picks.split_key(
        manual_picks.row_key(manual_picks.google_os("iOS"), "total install",
                             "https://www.youtube.com/watch?v=abc"))
    # URL에 `|`가 없으므로 키는 여전히 세 조각으로 정확히 갈린다.
    assert parts == ("google:iOS", "total install",
                     "https://www.youtube.com/watch?v=abc")


def test_구글_지정은_asset_컬럼으로_붙는다(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(manual_picks, "PICKS_DIR", tmp_path)
    table = pd.DataFrame([
        {"asset": "https://www.youtube.com/watch?v=A", "cost": 2.0, "CPI": 10},
        {"asset": "https://www.youtube.com/watch?v=B", "cost": 1.0, "CPI": 20},
    ])
    gos = manual_picks.google_os("iOS")
    manual_picks.save(8, gos, "total install",
                      "https://www.youtube.com/watch?v=A", "best")
    manual_picks.save(8, gos, "total install",
                      "https://www.youtube.com/watch?v=B", "worst")
    best, worst = manual_picks.apply(table, 8, gos, "total install", {}, {},
                                     id_column="asset")
    assert list(best) == [0] and list(worst) == [1]
    for column in list(best.values()) + list(worst.values()):
        assert column in table.columns


def test_ad_컬럼이_없는_표는_그냥_넘어간다(tmp_path, monkeypatch):
    """`id_column`을 안 넘기면 구글 표에는 아무 일도 일어나지 않아야 한다."""
    import pandas as pd

    monkeypatch.setattr(manual_picks, "PICKS_DIR", tmp_path)
    table = pd.DataFrame([{"asset": "u", "cost": 1.0}])
    manual_picks.save(8, manual_picks.google_os("iOS"), "total install", "u", "best")
    best, worst = manual_picks.apply(
        table, 8, manual_picks.google_os("iOS"), "total install", {}, {})
    assert (best, worst) == ({}, {})


def test_화면이_구글_표에_수기_지정을_적용한다():
    """진입점은 import할 수 없어 소스를 훑는다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    checked = 0
    for name in ("creative_dashboard.py", "app.py"):
        path = root / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert 'id_column="asset"' in source, name
        assert "manual_picks.google_os(os_name)" in source, name
        checked += 1
    assert checked


# ------------------------------------------- 매체까지 담는 식별자 (2026-09-30)

class TestIdentity:
    """표는 **소재 × 매체** 단위다 — 소재명만으로는 한 줄을 가리킬 수 없다.

    9월 실측: `iOS · 인스톨` 표에 `8230_第44節生存課_..._KRLabB-return2` 가
    Meta(₩5.4M)·TikTok(₩2.0M) **두 줄**로 있었다.
    """

    def frame(self):
        return pd.DataFrame({
            "ad": ["같은소재", "같은소재", "다른소재"],
            "media": ["Meta", "TikTok", "Meta"],
            "cost": [5_400_000, 2_000_000, 1_000_000],
            "CPI": [6_356, 6_513, 7_000],
        })

    def test_매체가_식별자에_들어간다(self):
        assert manual_picks.identities(self.frame()) == [
            "Meta|같은소재", "TikTok|같은소재", "Meta|다른소재"]

    def test_키를_왕복해도_안_깨진다(self):
        """식별자 칸은 `split(_SEP, 2)` 라 `|` 를 품어도 된다."""
        key = manual_picks.row_key("iOS", "total install", "Meta|같은소재")
        assert manual_picks.split_key(key) == ("iOS", "total install", "Meta|같은소재")

    def test_한_매체만_칠해진다(self):
        """③ 회귀 방지 — 예전에는 같은 소재의 **두 줄이 다** 칠해졌다."""
        manual_picks.invalidate(7)
        df = self.frame()
        ok, _ = manual_picks.save(7, "iOS", "total install", "Meta|같은소재", manual_picks.BEST)
        assert ok
        best, worst = manual_picks.apply(df, 7, "iOS", "total install", {}, {})
        assert list(best) == [0]          # Meta 줄만
        assert 1 not in best and 1 not in worst

    def test_옛_형식_지정이_계속_맞는다(self):
        """8·9월에 저장된 지정은 소재명만 들고 있다. **읽기 전용 승격**이라
        저장된 원본을 안 고쳐도 계속 맞아야 한다."""
        manual_picks.invalidate(7)
        df = self.frame()
        ok, _ = manual_picks.save(7, "iOS", "total install", "다른소재", manual_picks.WORST)
        assert ok
        _best, worst = manual_picks.apply(df, 7, "iOS", "total install", {}, {})
        assert list(worst) == [2]

    def test_매체_컬럼이_없으면_소재명_그대로다(self):
        df = self.frame().drop(columns=["media"])
        assert manual_picks.identities(df) == ["같은소재", "같은소재", "다른소재"]

    def test_include_media_False면_붙이지_않는다(self):
        """피벗 식별자는 이미 매체를 담고 있다 — 또 붙이면 `Meta|Meta|…` 가 된다."""
        assert manual_picks.identities(self.frame(), include_media=False) == [
            "같은소재", "같은소재", "다른소재"]


class TestPivotIdentity:
    """장르·피벗 표 — 행 축 값을 이어 붙인 것이 식별자다."""

    def frame(self):
        return pd.DataFrame({
            "media": ["Meta", "Meta", "TikTok"],
            "os": ["AOS", "iOS", "AOS"],
            "genre_group": ["[A-3] ROMANCE FANTASY", "[C] THRILLER", "[A-3] ROMANCE FANTASY"],
            "cost": [3_000_000, 2_000_000, 1_000_000],
            "CPI": [3_656, 8_302, 1_742],
        })

    def test_행_축을_이어_붙인다(self):
        ids = manual_picks.pivot_ids(self.frame(), ["media", "os", "genre_group"])
        assert ids[0] == "Meta|AOS|[A-3] ROMANCE FANTASY"
        assert len(set(ids)) == 3

    def test_표마다_키_공간이_나뉜다(self):
        assert manual_picks.pivot_os("abc123") != manual_picks.pivot_os("def456")
        assert manual_picks.pivot_os("abc123").startswith(manual_picks.PIVOT_PREFIX)
        # 2번 섹션·구글과도 안 겹친다.
        assert not manual_picks.pivot_os("abc123").startswith(manual_picks.GOOGLE_PREFIX)

    def test_표에_없는_축은_건너뛴다(self):
        ids = manual_picks.pivot_ids(self.frame(), ["media", "없는축"])
        assert ids[0] == "Meta"

    def test_빈_표는_빈_목록(self):
        assert manual_picks.pivot_ids(pd.DataFrame(), ["media"]) == []

    def test_지정이_피벗_표에_붙는다(self):
        manual_picks.invalidate(9)
        df = self.frame()
        df[manual_picks.PIVOT_ID_COLUMN] = manual_picks.pivot_ids(df, ["media", "os", "genre_group"])
        ok, _ = manual_picks.save(9, manual_picks.pivot_os("v1"), "CPI",
                       "TikTok|AOS|[A-3] ROMANCE FANTASY", manual_picks.BEST)
        assert ok
        best, _worst = manual_picks.apply(df, 9, manual_picks.pivot_os("v1"), "CPI", {}, {},
                               id_column=manual_picks.PIVOT_ID_COLUMN)
        assert list(best) == [2]
