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
