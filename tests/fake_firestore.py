"""인메모리 가짜 Firestore. 실제 DB 없이 Firestore 경로를 검증한다.

`tests/fake_sheets.py`와 같은 역할이다. `tests/conftest.py`가 실제 Firestore 접근을
막고 있으므로(fail-closed), Firestore 경로를 검증하려면 이걸 명시적으로 붙인다.

**왜 자체 제작인가.** `fs_store`는 `from google.cloud import firestore`를 함수 안에서
하고 `@firestore.transactional`을 쓴다. 진짜 데코레이터에 가짜 트랜잭션을 넘기면
내부 구현을 건드려 깨진다. 그래서 `sys.modules`에 **가짜 firestore 모듈**을 끼워
`transactional`까지 함께 흉내 낸다.

**트랜잭션은 직렬화한다.** 전역 락으로 "읽고 판단하고 쓰기"를 한 단위로 묶는다 —
그게 진짜 Firestore가 주는 성질이고, 우리가 시트에서 얻지 못했던 바로 그것이다.
이 성질이 없으면 "같은 블록 동시 저장 → 한쪽 거부" 계약을 검증할 수 없다.

지원 범위는 `fs_store`가 실제로 쓰는 만큼이다:
    client().collection(name).document(id).get()/set()/delete()
    collection.stream() / list_documents()
    client().transaction() + @firestore.transactional (tx.set / tx.delete / ref.get(tx))
    client().batch() + batch.set/delete/commit
"""
from __future__ import annotations

import copy
import threading
import types

_LOCK = threading.RLock()


class _Snap:
    def __init__(self, path, data, ref):
        self._path, self._data, self.reference = path, data, ref

    @property
    def id(self):
        return self._path[-1]

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class _DocRef:
    def __init__(self, book, path):
        self._book, self._path = book, path

    @property
    def id(self):
        return self._path[-1]

    def collection(self, name):
        return _CollRef(self._book, self._path + (name,))

    def get(self, transaction=None):
        # 트랜잭션 안의 읽기도 같은 저장소를 본다. 직렬화는 transactional이 담당한다.
        with _LOCK:
            return _Snap(self._path, self._book.data.get(self._path), self)

    def set(self, data, merge=False):
        with _LOCK:
            if merge and self._path in self._book.data:
                merged = dict(self._book.data[self._path])
                merged.update(copy.deepcopy(data))
                self._book.data[self._path] = merged
            else:
                self._book.data[self._path] = copy.deepcopy(data)
            self._book.writes += 1

    def delete(self):
        with _LOCK:
            self._book.data.pop(self._path, None)
            self._book.deletes += 1


class _CollRef:
    def __init__(self, book, path):
        self._book, self._path = book, path

    def document(self, doc_id=None):
        if doc_id is None:
            self._book.auto += 1
            doc_id = f"auto{self._book.auto}"
        return _DocRef(self._book, self._path + (str(doc_id),))

    def _children(self):
        depth = len(self._path) + 1
        with _LOCK:
            return [p for p in self._book.data
                    if len(p) == depth and p[:len(self._path)] == self._path]

    def stream(self):
        self._book.reads += 1
        return [_Snap(p, self._book.data[p], _DocRef(self._book, p))
                for p in sorted(self._children())]

    def list_documents(self):
        self._book.reads += 1
        return [_DocRef(self._book, p) for p in sorted(self._children())]


class _Tx:
    """쓰기를 모아 두고 commit에서 한꺼번에 적용한다(전부 아니면 전무)."""

    def __init__(self, book):
        self._book, self._ops = book, []

    def set(self, ref, data, merge=False):
        self._ops.append(("set", ref, copy.deepcopy(data), merge))

    def delete(self, ref):
        self._ops.append(("delete", ref, None, False))

    def _commit(self):
        for kind, ref, data, merge in self._ops:
            if kind == "set":
                ref.set(data, merge=merge)
            else:
                ref.delete()
        self._ops = []

    def _rollback(self):
        self._ops = []


class _Batch(_Tx):
    def commit(self):
        with _LOCK:
            self._commit()


class FakeFirestore:
    def __init__(self):
        self.data: dict = {}
        self.reads = self.writes = self.deletes = self.auto = 0

    def collection(self, name):
        return _CollRef(self, (name,))

    def document(self, path):
        return _DocRef(self, tuple(str(path).split("/")))

    def transaction(self):
        return _Tx(self)

    def batch(self):
        return _Batch(self)

    # ---- 테스트 편의 ----
    def dump(self, prefix=()):
        return {"/".join(p): v for p, v in sorted(self.data.items())
                if p[:len(prefix)] == prefix}


def _fake_module():
    """`from google.cloud import firestore` 가 받아 갈 가짜 모듈."""
    module = types.ModuleType("google.cloud.firestore")

    def transactional(func):
        def wrapped(transaction, *args, **kwargs):
            # **전체를 한 락 안에서** 돌린다 — 이게 Firestore가 주는 원자성이고,
            # 시트에서는 얻을 수 없었던 성질이다(읽기와 쓰기 사이가 원자적).
            with _LOCK:
                try:
                    result = func(transaction, *args, **kwargs)
                except Exception:
                    transaction._rollback()
                    raise
                transaction._commit()
                return result

        return wrapped

    module.transactional = transactional
    module.Client = lambda *a, **k: FakeFirestore()
    module.SERVER_TIMESTAMP = "__server_timestamp__"
    return module


def install(monkeypatch, fs_store, book: FakeFirestore | None = None) -> FakeFirestore:
    """가짜 Firestore를 붙인다. 돌려받은 객체로 저장 내용을 직접 볼 수 있다."""
    import sys

    book = book or FakeFirestore()
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", _fake_module())
    monkeypatch.setattr(fs_store, "client", lambda: book)
    monkeypatch.setattr(fs_store, "configured", lambda: True)
    monkeypatch.setattr(fs_store, "_creds", lambda: ("fake-creds", "fake-project"))
    return book
