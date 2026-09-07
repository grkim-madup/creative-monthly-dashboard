# -*- coding: utf-8 -*-
"""전역 설정 — 세션이 아니라 저장소에 남아야 한다.

규리님: *"왜 자꾸 구글 시트 링크도 내가 고정해둔 걸로 안 쓰고 [기본값] 으로 불러와?"*
원인은 `st.session_state`에만 있었던 것 — 새로고침·재배포마다 코드 상수로 돌아갔다.
"""
import pytest

import app_settings


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", tmp_path / "app_settings.json")
    monkeypatch.setattr(app_settings.store, "is_firestore", lambda: False)


def test_처음에는_비어_있다():
    assert app_settings.load() == {}
    assert app_settings.get("sheet_url", "기본") == "기본"


def test_저장하면_다시_읽힌다():
    ok, reason = app_settings.save("sheet_url", "https://docs.google.com/x/A/edit")
    assert (ok, reason) == (True, None)
    assert app_settings.get("sheet_url") == "https://docs.google.com/x/A/edit"


def test_모르는_키는_거부한다():
    ok, reason = app_settings.save("password", "x")
    assert ok is False
    assert "알 수 없는" in reason
    assert app_settings.load() == {}


def test_빈_값은_저장하지_않는다():
    """실수로 지웠을 때 기본값이 저장돼 원래 값을 덮으면 안 된다."""
    app_settings.save("sheet_url", "A")
    ok, reason = app_settings.save("sheet_url", "   ")
    assert ok is False and reason
    assert app_settings.get("sheet_url") == "A"


def test_저장은_원자적이다(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", tmp_path / "s.json")
    app_settings.save("sheet_url", "A")
    assert not list(tmp_path.glob("*.tmp"))


def test_깨진_파일은_빈_설정으로_읽는다(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    path.write_text("{깨짐", encoding="utf-8")
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", path)
    assert app_settings.load() == {}


def test_읽기_실패를_설정_없음으로_뭉개지_않는다(monkeypatch):
    """실패면 빈 dict를 돌려주되, 그 위에 저장하는 일이 없도록 호출부가 기본값을 쓴다."""
    import fs_store

    monkeypatch.setattr(app_settings.store, "is_firestore", lambda: True)
    monkeypatch.setattr(fs_store, "read_app_settings",
                        lambda: ("error", {}, "쿼터 초과"))
    assert app_settings.load() == {}


def test_firestore_왕복(monkeypatch):
    import fs_store
    from tests import fake_firestore

    fake_firestore.install(monkeypatch, fs_store)
    monkeypatch.setattr(app_settings.store, "is_firestore", lambda: True)
    assert app_settings.load() == {}
    assert app_settings.save("sheet_url", "https://x/A/edit") == (True, None)
    assert app_settings.save("google_folder", r"C:\드롭박스\구글") == (True, None)
    loaded = app_settings.load()
    assert loaded["sheet_url"] == "https://x/A/edit"
    assert "구글" in loaded["google_folder"]
