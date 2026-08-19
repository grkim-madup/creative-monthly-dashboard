import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import overrides  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(overrides, "OVERRIDES_DIR", tmp_path / "notes")


def test_load_returns_empty_when_missing():
    assert overrides.load(7) == {}


def test_save_then_load_roundtrip():
    overrides.save(7, "이상한소재명", {"creative_type": "Highlight", "usp": "1"})
    assert overrides.load(7) == {"이상한소재명": {"creative_type": "Highlight", "usp": "1"}}


def test_save_drops_blank_fields():
    overrides.save(7, "ad1", {"creative_type": "Highlight", "usp": "  ", "format": ""})
    assert overrides.load(7) == {"ad1": {"creative_type": "Highlight"}}


def test_saving_all_blank_removes_entry():
    overrides.save(7, "ad1", {"creative_type": "Highlight"})
    overrides.save(7, "ad1", {"creative_type": "  ", "usp": ""})
    assert overrides.load(7) == {}


def test_remove():
    overrides.save(7, "ad1", {"creative_type": "Highlight"})
    overrides.remove(7, "ad1")
    assert overrides.load(7) == {}


def test_remove_unknown_ad_is_safe():
    overrides.remove(7, "없는소재")


def test_months_are_kept_separate():
    overrides.save(7, "ad1", {"creative_type": "Highlight"})
    overrides.save(8, "ad1", {"creative_type": "Trailer"})
    assert overrides.load(7)["ad1"]["creative_type"] == "Highlight"
    assert overrides.load(8)["ad1"]["creative_type"] == "Trailer"


def test_corrupted_file_falls_back_to_empty():
    overrides.OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    (overrides.OVERRIDES_DIR / "overrides_7.json").write_text("{깨진 json", encoding="utf-8")
    assert overrides.load(7) == {}


def test_apply_patches_matching_rows_only():
    df = pd.DataFrame({
        "ad": ["ad1", "ad1", "ad2"],
        "creative_type": [None, None, "Highlight"],
        "extra_info": [None, None, "text"],
    })
    overrides.save(7, "ad1", {"creative_type": "Trailer", "extra_info": "sns"})
    out = overrides.apply(df, 7)
    assert list(out["creative_type"]) == ["Trailer", "Trailer", "Highlight"]
    assert list(out["extra_info_label"]) == ["sns", "sns", "text"]


def test_apply_is_noop_when_no_overrides():
    df = pd.DataFrame({"ad": ["ad1"], "creative_type": ["Highlight"]})
    out = overrides.apply(df, 7)
    pd.testing.assert_frame_equal(out, df)


def test_apply_ignores_override_for_ad_not_present():
    df = pd.DataFrame({"ad": ["ad2"], "creative_type": [None]})
    overrides.save(7, "ad1", {"creative_type": "Trailer"})
    out = overrides.apply(df, 7)
    assert pd.isna(out.loc[0, "creative_type"])
