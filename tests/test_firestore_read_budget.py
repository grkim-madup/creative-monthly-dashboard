# -*- coding: utf-8 -*-
"""Firestore 읽기 예산 — 없는 문서를 달마다 묻지 않는다.

2026-09-08 실제 사고: `_media_meta()`가 월 1~12를 돌며 `snapshot_meta(m)`을 불렀다.
Firestore는 **없는 문서를 읽어도 읽기 1회**를 쓰므로 리런마다 12회, TTL 60초면
프로세스 하나당 하루 17,280회다. 배포판 둘 + 로컬이면 무료 한도(5만/일)를 태운다.

결과: 팀원이 대시보드를 열자 `429 Quota exceeded`가 뜨고 4·6번 블록이 통째로 안 보였다.
**데이터는 멀쩡했다** — 읽기만 막혔고 편집은 fail-closed로 잠겨 덮어쓰지 않았다.

지금은 컬렉션 그룹 질의 한 번으로 **고정된 달만** 가져온다(돌려주는 문서 수만큼만 과금).
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_컬렉션_그룹_질의로_한_번에_읽는다():
    import fs_store

    assert hasattr(fs_store, "all_snapshot_meta")
    source = (ROOT / "fs_store.py").read_text(encoding="utf-8")
    assert "collection_group(" in source


@pytest.mark.parametrize("name", ["media_snapshot.py", "google_snapshot.py"])
def test_스냅샷_모듈이_Firestore를_달마다_묻지_않는다(name):
    """`for month in range(1, 13)` 안에서 Firestore를 부르면 12배가 된다.

    시트·로컬 백엔드에서 도는 루프는 괜찮다(하루 한도 개념이 없다) — Firestore
    분기 안에 있는지만 본다.
    """
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        src = ast.unparse(node)
        if "range(1, 13)" not in src:
            continue
        if "fs_store." in src:
            bad.append(f"{name}: range(1,13) 루프 안에서 fs_store 호출")
    assert not bad, "\n  ".join(bad)


def test_화면이_월별로_따로_묻지_않는다():
    """진입점은 테스트가 import할 수 없어 소스를 훑는다."""
    checked = 0
    for name in ("creative_dashboard.py", "app.py"):
        path = ROOT / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        # 한 번에 읽는 창구를 쓰는지
        assert "media_snapshot.all_meta()" in source, name
        assert "google_snapshot.all_meta()" in source, name
        # 예전 12개월 스캔이 되살아나지 않았는지
        assert "for month in range(1, 13):" not in source, name
        checked += 1
    assert checked


def test_고정된_달만_돌려준다(monkeypatch):
    """없는 달을 채워 넣으면 다시 12배가 된다."""
    import fs_store
    import media_snapshot
    import pandas as pd
    from tests import fake_firestore

    fake_firestore.install(monkeypatch, fs_store)
    monkeypatch.setattr(media_snapshot.store, "is_firestore", lambda: True)
    rows = pd.DataFrame([{"ad": "a", "month": 8, "cost": 1.0}])
    media_snapshot.save(8, rows)
    found = media_snapshot.all_meta()
    assert sorted(found) == [8]
    assert media_snapshot.frozen_months() == [8]
