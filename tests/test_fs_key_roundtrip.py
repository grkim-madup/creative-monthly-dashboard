# -*- coding: utf-8 -*-
"""Firestore 문서 id는 키로 되읽을 수 없다 — 원본 키를 필드에서 읽어야 한다.

2026-09-08 실제 사고: 구글 애셋 URL을 수기 지정 키로 쓰자마자 드러났다.
`_doc_id`가 `/`를 전각 `／`로 바꿔 저장하는데 `read_picks`가 문서 id를 키로 읽어서,
**저장은 성공하는데 표에는 하나도 안 붙었다.** 에러도 나지 않았다.
메타·틱톡 소재명에는 `/`가 없어서 여태 보이지 않던 결함이다.
"""
import pytest

import fs_store
from tests import fake_firestore

URL = "https://www.youtube.com/watch?v=G0_9MDiaCe8"


@pytest.fixture
def book(monkeypatch):
    return fake_firestore.install(monkeypatch, fs_store)


def test_문서_id는_슬래시를_전각으로_바꾼다():
    """되돌릴 수 없는 변환임을 명시적으로 고정한다."""
    doc = fs_store._doc_id(URL)
    assert "/" not in doc
    assert doc != URL


def test_슬래시가_있는_키가_그대로_되읽힌다(book):
    ok, reason = fs_store.write_pick(8, f"google:iOS|total install|{URL}", "best")
    assert (ok, reason) == (True, None)
    status, data, _ = fs_store.read_picks(8)
    assert status == "ok"
    assert list(data) == [f"google:iOS|total install|{URL}"], (
        "문서 id를 키로 읽으면 `https:／／…`가 되어 표에 안 붙는다")


def test_예전_문서에는_key_필드가_없다_id로_폴백(book):
    """`key` 필드를 넣기 전에 저장된 문서도 계속 읽혀야 한다."""
    fs_store._sub(8, fs_store.PICKS).document("AOS|total install|어떤소재").set(
        {"pick": "worst"})
    status, data, _ = fs_store.read_picks(8)
    assert status == "ok"
    assert data["AOS|total install|어떤소재"] == {"pick": "worst"}


def test_수동_분류도_같은_방식으로_읽는다(book):
    ok, _ = fs_store.write_override(8, "소재/이름", {"format": "VID"})
    assert ok
    status, data, _ = fs_store.read_overrides(8)
    assert status == "ok"
    assert data == {"소재/이름": {"format": "VID"}}
