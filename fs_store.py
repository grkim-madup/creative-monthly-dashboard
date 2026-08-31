"""Firestore 저장소 — 우선 **편집 잠금**부터.

왜 잠금이 먼저인가:
시트에서 가장 망가져 있던 곳이다. 시트에는 원자적 compare-and-swap이 없어서, rev를 읽는
것과 쓰는 것이 별개 호출이 되고 6명이 동시에 달려들면 다섯 명이 같은 rev를 보고 전부
통과했다(2026-08-30 실측: 임계구역에 5명 동시 진입). 그걸 `claim-then-verify`
(쓴 뒤 0.5초 기다렸다 다시 읽어 확인)로 막았는데 — 확률적 방어이고, 429 재시도가 끼면
정착창이 무의미해지며, 조작 한 번에 시트 읽기 5회를 썼다.

Firestore 트랜잭션은 읽기와 쓰기가 한 단위다. 그래서:
  - 획득이 **트랜잭션 한 번**이 된다 → 겹침이 원리적으로 불가능
  - `claim-then-verify`와 0.5초 지연이 필요 없어진다(편집 버튼이 그만큼 빨라진다)
  - 조작당 왕복이 5회에서 1회로 준다

데이터 모양 (컬렉션 `locks`, 문서 하나 = 잠금 하나):
    locks/{key}  ->  {owner, acquired_at, touched_at}
`key`는 시트 시절과 같은 `"block:<블록id>@<월>"`이다. 소유자가 없으면(빈 문자열/없음)
"잠금 없음"이다 — 문서를 지우지 않고 소유자만 비운다. 문서를 지워도 되지만, 읽기 쪽
의미를 시트 시절과 똑같이 유지해 두면 두 백엔드를 나란히 검증하기 쉽다.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from uuid import uuid4

LOCKS = "locks"

_local = threading.local()


def _creds():
    from google.oauth2 import service_account

    import google_sheets_writer

    info = google_sheets_writer._service_account_info()
    if not info:
        return None, None
    creds = service_account.Credentials.from_service_account_info(info)
    return creds, str(info.get("project_id") or "")


def configured() -> bool:
    """Firestore를 쓸 준비가 됐는가(자격증명 + 라이브러리)."""
    try:
        from google.cloud import firestore  # noqa: F401
    except ImportError:
        return False
    creds, project = _creds()
    return bool(creds and project)


def client():
    """스레드별 Firestore 클라이언트.

    Streamlit은 세션마다 스레드가 다르다. 클라이언트를 매번 새로 만들면 그때마다 자격증명
    처리가 다시 일어나 리런 한 번에 수백 ms가 날아간다(시트 클라이언트에서 같은 교훈).
    """
    if getattr(_local, "db", None) is None:
        from google.cloud import firestore

        creds, project = _creds()
        if not creds:
            raise RuntimeError("Firestore 자격증명이 없습니다(gcp_service_account).")
        _local.db = firestore.Client(project=project, credentials=creds)
    return _local.db


def reset_client() -> None:
    """테스트·백엔드 전환 때 캐시된 클라이언트를 버린다."""
    _local.db = None


# ---------------------------------------------------------------------------
# 잠금


def _elapsed_minutes(touched_at: str, now: datetime) -> float:
    """마지막 갱신 이후 흐른 시간(분). 값이 깨져 있으면 '아주 오래됐다'로 본다.

    깨진 값을 0분으로 보면 아무도 그 잠금을 회수할 수 없어 블록이 영구히 잠긴다.
    """
    try:
        return (now - datetime.fromisoformat(touched_at)).total_seconds() / 60.0
    except (TypeError, ValueError):
        return float("inf")


def read_locks() -> tuple[str, dict, str | None]:
    """(상태, {키: {owner, acquired_at, touched_at, rev}}, 실패 이유).

    시트 백엔드와 **똑같은 모양**을 돌려준다. `rev`는 Firestore에서 쓰이지 않지만(트랜잭션이
    대신한다) 호출부 계약을 바꾸지 않기 위해 0으로 채운다.
    읽기 실패를 "잠금 없음"으로 뭉개면 두 사람이 같은 블록을 동시에 잡는다 — 반드시 error로.
    """
    try:
        out: dict = {}
        for snap in client().collection(LOCKS).stream():
            data = snap.to_dict() or {}
            if not data.get("owner"):
                continue                      # 소유자 없는 문서 = 풀린 잠금
            out[snap.id] = {
                "owner": str(data.get("owner") or ""),
                "acquired_at": str(data.get("acquired_at") or ""),
                "touched_at": str(data.get("touched_at") or ""),
                "rev": 0,
            }
        return "ok", out, None
    except Exception as error:  # noqa: BLE001
        return "error", {}, f"{type(error).__name__}: {error}"


def acquire_lock(
    key: str, owner: str, now: datetime, ttl_minutes: float
) -> tuple[bool, str | None]:
    """잠금을 잡는다 — **트랜잭션 한 번.** 겹침이 원리적으로 불가능하다.

    잡을 수 있는 경우: 아무도 안 쥐고 있다 / 이미 내 것이다 / 마지막 갱신이 TTL을 넘겼다.
    """
    from google.cloud import firestore

    stamp = now.isoformat(timespec="seconds")

    @firestore.transactional
    def attempt(tx):
        snap = ref.get(transaction=tx)
        data = (snap.to_dict() or {}) if snap.exists else {}
        holder = str(data.get("owner") or "")
        if holder and holder != owner:
            if _elapsed_minutes(str(data.get("touched_at") or ""), now) < ttl_minutes:
                return False               # 남이 쥐고 있고 아직 안 만료됐다
        acquired = str(data.get("acquired_at") or stamp) if holder == owner else stamp
        tx.set(ref, {"owner": owner, "acquired_at": acquired, "touched_at": stamp})
        return True

    try:
        ref = client().collection(LOCKS).document(key)
        return bool(attempt(client().transaction())), None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def touch_lock(
    key: str, owner: str, now: datetime, ttl_minutes: float
) -> tuple[bool, str | None]:
    """내가 쥔 잠금의 만료를 미룬다. 그 사이 뺏겼으면 False.

    ⚠ `ref`는 아래 try 안에서 만든다 — 저장소가 아예 안 될 때 `client()`가 던지는 예외가
      화면까지 올라가지 않게 하려면 준비 코드도 try 안이어야 한다(계약 테스트가 잡았다).
    """
    from google.cloud import firestore

    stamp = now.isoformat(timespec="seconds")

    @firestore.transactional
    def attempt(tx):
        snap = ref.get(transaction=tx)
        data = (snap.to_dict() or {}) if snap.exists else {}
        if str(data.get("owner") or "") != owner:
            return False
        if _elapsed_minutes(str(data.get("touched_at") or ""), now) >= ttl_minutes:
            return False                   # 이미 만료 — 다시 잡아야 한다
        tx.update(ref, {"touched_at": stamp})
        return True

    try:
        ref = client().collection(LOCKS).document(key)
        return bool(attempt(client().transaction())), None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def release_lock(key: str, owner: str) -> tuple[bool, str | None]:
    """내 잠금을 푼다. **내 것이 아니면 건드리지 않는다**(트랜잭션이 보장한다).

    시트 시절에는 사전 확인과 쓰기가 떨어져 있어, 확인이 낡으면 남이 방금 가져간 잠금을
    지울 수 있었다. 여기서는 같은 트랜잭션 안에서 확인하고 쓴다.
    """
    from google.cloud import firestore

    @firestore.transactional
    def attempt(tx):
        snap = ref.get(transaction=tx)
        data = (snap.to_dict() or {}) if snap.exists else {}
        if str(data.get("owner") or "") != owner:
            return False                   # 내 것이 아니다(이미 풀렸거나 뺏겼다)
        tx.set(ref, {"owner": "", "acquired_at": "", "touched_at": ""})
        return True

    try:
        ref = client().collection(LOCKS).document(key)
        attempt(client().transaction())
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def force_release_lock(key: str) -> tuple[bool, str | None]:
    """소유자와 무관하게 푼다(강제 해제·테스트 정리용)."""
    try:
        client().collection(LOCKS).document(key).set(
            {"owner": "", "acquired_at": "", "touched_at": ""}
        )
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


# ---------------------------------------------------------------------------
# 블록 · 셀 강조 · 수동 분류
#
# 컬렉션 배치 (문서 하나 = 항목 하나. 시트의 "키 하나 = 행 하나"와 같은 뜻이다):
#     reports/{월}/blocks/{block_id}      {slot, seq, rev, payload}
#     reports/{월}/hlcells/{cell_key}     {table_key, row, col}
#     reports/{월}/overrides/{소재명}      {rev, fields}
#
# 시트와 결정적으로 다른 점: `rev` 대조가 **트랜잭션 안에서** 일어난다. 시트에서는 읽기와
# 쓰기가 별개 호출이라 여럿이 같은 rev를 보고 전부 통과할 수 있었고, 행 번호가 주소여서
# 남이 행을 지우면 내 쓰기가 엉뚱한 줄에 떨어졌다. 문서에는 행 번호라는 개념이 없다.

BLOCKS = "blocks"
HLCELLS = "hlcells"
OVERRIDES = "overrides"


def _month_doc(month: int):
    return client().collection("reports").document(str(int(month)))


def _sub(month: int, name: str):
    return _month_doc(month).collection(name)


def read_block_rows(month: int) -> tuple[str, list[dict], str | None]:
    """(상태, [{block_id, slot, seq, rev, block}], 실패 이유) — 시트와 같은 모양."""
    try:
        items = []
        for snap in _sub(month, BLOCKS).stream():
            data = snap.to_dict() or {}
            block = data.get("payload")
            if not isinstance(block, dict) or not block.get("id"):
                continue
            items.append({
                "block_id": snap.id,
                "slot": str(data.get("slot") or ""),
                "seq": int(data.get("seq") or 0),
                "rev": int(data.get("rev") or 0),
                "block": block,
            })
        # "행이 없다"와 "못 읽었다"는 끝까지 구분한다. empty는 이관 경로를 태우고,
        # error는 저장을 막는다 — 뭉개면 그 위에 빈 값을 저장해 한 달치가 날아간다.
        return ("ok" if items else "empty"), items, None
    except Exception as error:  # noqa: BLE001
        return "error", [], f"{type(error).__name__}: {error}"


def upsert_block_rows(
    month: int, rows: list[dict], expected_revs: dict | None = None
) -> tuple[bool, str | None]:
    """블록 여러 개를 **한 트랜잭션으로** 저장한다.

    expected_revs를 주면 그 안에서 rev를 대조하고, 하나라도 어긋나면 아무것도 쓰지 않는다.
    시트에서는 이 "전부 아니면 전무"가 보장되지 않아, 절반은 새 값 절반은 옛 값인 상태가
    만들어질 수 있었다.
    """
    if not rows:
        return True, None
    from google.cloud import firestore

    refs: dict = {}

    @firestore.transactional
    def attempt(tx):
        current = {}
        for block_id, ref in refs.items():
            snap = ref.get(transaction=tx)
            current[block_id] = (snap.to_dict() or {}) if snap.exists else None
        if expected_revs:
            for block_id, seen in expected_revs.items():
                data = current.get(block_id)
                if data is None:
                    if int(seen) != 0:
                        return "deleted"
                elif int(data.get("rev") or 0) != int(seen):
                    return "conflict"
        for row in rows:
            block_id = row["block_id"]
            data = current.get(block_id) or {}
            tx.set(refs[block_id], {
                "slot": row["slot"],
                "seq": int(row["seq"]),
                "rev": int(data.get("rev") or 0) + 1,
                "payload": row["payload"],
            })
        return None

    try:
        coll = _sub(month, BLOCKS)
        refs.update({row["block_id"]: coll.document(row["block_id"]) for row in rows})
        problem = attempt(client().transaction())
        return (problem is None), problem
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def delete_block_rows(month: int, block_ids: list[str]) -> tuple[bool, str | None]:
    """블록 문서를 지운다. 행 번호가 없으니 남의 것이 밀릴 일이 없다."""
    if not block_ids:
        return True, None
    try:
        batch = client().batch()
        coll = _sub(month, BLOCKS)
        for block_id in block_ids:
            batch.delete(coll.document(block_id))
        batch.commit()
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def read_hl_cells(month: int) -> tuple[str, dict, str | None]:
    """(상태, {표 키: [(행, 컬럼), ...]}, 실패 이유)."""
    try:
        out: dict[str, list] = {}
        for snap in _sub(month, HLCELLS).stream():
            data = snap.to_dict() or {}
            table_key = str(data.get("table_key") or "")
            if not table_key:
                continue
            cell = (int(data.get("row") or 0), str(data.get("col") or ""))
            cells = out.setdefault(table_key, [])
            if cell not in cells:
                cells.append(cell)
        return ("ok" if out else "empty"), out, None
    except Exception as error:  # noqa: BLE001
        return "error", {}, f"{type(error).__name__}: {error}"


def add_hl_cells(month: int, table_key: str, cells: list) -> tuple[bool, str | None]:
    """셀마다 문서 하나. 서로 다른 셀은 서로 다른 문서라 충돌이 없다."""
    if not cells:
        return True, None
    try:
        batch = client().batch()
        coll = _sub(month, HLCELLS)
        for row, col in cells:
            key = f"{table_key}|{int(row)}|{col}"
            batch.set(coll.document(key),
                      {"table_key": table_key, "row": int(row), "col": str(col)})
        batch.commit()
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def remove_hl_cells(month: int, table_key: str, cells: list) -> tuple[bool, str | None]:
    if not cells:
        return True, None
    try:
        batch = client().batch()
        coll = _sub(month, HLCELLS)
        for row, col in cells:
            batch.delete(coll.document(f"{table_key}|{int(row)}|{col}"))
        batch.commit()
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def read_overrides(month: int) -> tuple[str, dict, str | None]:
    """(상태, {소재명: {필드: 값}}, 실패 이유)."""
    try:
        out = {}
        for snap in _sub(month, OVERRIDES).stream():
            data = snap.to_dict() or {}
            fields = data.get("fields")
            if isinstance(fields, dict):
                out[snap.id] = fields
        return ("ok" if out else "empty"), out, None
    except Exception as error:  # noqa: BLE001
        return "error", {}, f"{type(error).__name__}: {error}"


def write_override(month: int, ad: str, fields: dict) -> tuple[bool, str | None]:
    try:
        _sub(month, OVERRIDES).document(ad).set({"fields": dict(fields)})
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


def delete_override(month: int, ad: str) -> tuple[bool, str | None]:
    try:
        _sub(month, OVERRIDES).document(ad).delete()
        return True, None
    except Exception as error:  # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"


# --------------------------------------------------------------------------- #
# 스냅샷 (2-C)
#
# 시트에서는 `snapshot_<월>` 탭 + `_snapshot_meta` 탭 두 개였고, 원자성을 얻기 위해
# "임시 탭에 쓰고 이름 맞바꾸기"(`_swap_tab`)를 써야 했다. 여기서는 같은 성질을
# **커밋 문서 하나**로 얻는다 — 청크를 다 쓴 뒤 마지막에 메타 문서를 쓰고, 읽는 쪽은
# 메타의 `gen`과 일치하는 청크만 읽는다. 그래서 중간 상태가 보이지 않는다.
#
# ⚠ 왜 문서 하나에 안 담는가: 7월 스냅샷이 2,091행 × 20열 = **JSON 692KB**로,
#   문서 상한 1 MiB의 66%다(설계 때 "≈150KB"로 잡았던 추정은 틀렸다). 행이 1.5배만
#   늘어도 한도를 넘는다. 그래서 청크로 나눈다.
# --------------------------------------------------------------------------- #

SNAPMETA = "snapmeta"
SNAPCHUNKS = "snapchunks"
_META_DOC = "current"

#: 청크 하나에 담을 JSON 바이트 목표. 상한(1 MiB)의 1/3 이하로 잡아 여유를 둔다.
CHUNK_TARGET_BYTES = 300_000


def _snap_meta_ref(month: int):
    return _sub(month, SNAPMETA).document(_META_DOC)


def _snap_chunks(month: int):
    return _sub(month, SNAPCHUNKS)


def snapshot_exists(month: int) -> bool:
    try:
        return _snap_meta_ref(month).get().exists
    except Exception:
        return False


def snapshot_frozen_at(month: int) -> str | None:
    try:
        snap = _snap_meta_ref(month).get()
        return (snap.to_dict() or {}).get("frozen_at") if snap.exists else None
    except Exception:
        return None


def _chunk_rows(rows: list, cols: list) -> list[str]:
    """행 목록을 JSON 문자열 청크로 쪼갠다. 청크 하나가 문서 하나가 된다."""
    chunks: list[str] = []
    current: list = []
    size = 0
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False, default=str)
        # 한 행만으로도 목표를 넘으면 그 행 하나를 자기 청크로 둔다(쪼갤 수 없다).
        if current and size + len(blob.encode("utf-8")) > CHUNK_TARGET_BYTES:
            chunks.append(json.dumps(current, ensure_ascii=False, default=str))
            current, size = [], 0
        current.append(row)
        size += len(blob.encode("utf-8"))
    if current or not chunks:
        chunks.append(json.dumps(current, ensure_ascii=False, default=str))
    return chunks


def write_snapshot(month: int, df, frozen_at: str | None = None) -> None:
    """이 달 스냅샷을 갈아끼운다. 실패하면 예전 스냅샷이 그대로 남는다.

    `frozen_at`은 **이관할 때만** 넘긴다 — 시트에 있던 원래 고정 시각을 보존하기
    위해서다. 이 값은 화면에 "N월 데이터 고정됨 · 날짜"로 광고주에게 그대로 보이므로,
    이관이 오늘 날짜로 덮어쓰면 리포트 이력이 조용히 틀려진다(실제로 그렇게 됐다).
    평소 고정 버튼은 인자를 비워 지금 시각을 찍는다.

    커밋 순서가 안전성의 핵심이다:
      1) 새 세대(`gen`)로 청크를 쓴다 — 이 시점에는 아무도 새 청크를 안 본다
      2) **메타 문서를 쓴다 = 커밋**. 이 한 번의 쓰기로 옛 스냅샷이 새 것으로 바뀐다
      3) 옛 세대 청크를 지운다 — 실패해도 데이터는 정확하다(쓰레기만 남는다)
    2)까지 못 가고 실패하면 메타가 옛 세대를 계속 가리키므로 **옛 스냅샷이 온전하다.**
    """
    cols = [str(c) for c in df.columns]
    body = df.astype(object).where(df.notna(), None)
    rows = body.values.tolist()

    gen = uuid4().hex[:8]
    chunks = _chunk_rows(rows, cols)
    fs = client()
    coll = _snap_chunks(month)

    # 1) 새 청크
    batch = fs.batch()
    for index, payload in enumerate(chunks):
        batch.set(coll.document(f"{gen}_{index:04d}"),
                  {"gen": gen, "seq": index, "payload": payload,
                   "created_at": datetime.now().isoformat(timespec="seconds")})
    batch.commit()

    # 2) 커밋 — 이 쓰기 하나로 스냅샷이 교체된다
    _snap_meta_ref(month).set({
        "gen": gen,
        "chunks": len(chunks),
        "cols": cols,
        "row_count": len(rows),
        "frozen_at": frozen_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    # 3) 옛 세대 청소 — 실패해도 정확성에 영향 없다.
    #
    # ⚠ **남의 세대를 지우면 안 된다.** 6명이 동시에 고정하면, 내가 커밋한 뒤 남이 또
    #   커밋할 수 있다. 그때 "내 gen이 아닌 것 전부"를 지우면 **메타가 가리키는 최신
    #   청크를 지워** 스냅샷이 깨진다(실측으로 재현: 청크 0/1). 그래서:
    #     - 지금 커밋된 메타를 다시 읽고
    #     - 내가 졌으면 **내 청크만** 지운다(아무도 안 본다)
    #     - 내가 이겼으면 남이 자기 것을 치우도록 두고, 10분 넘게 방치된 고아만 쓸어낸다
    #       (고정 도중에 죽은 프로세스의 잔해)
    try:
        live = ((_snap_meta_ref(month).get().to_dict() or {}).get("gen")) or gen
        cutoff = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
        stale = []
        for doc in coll.stream():
            data = doc.to_dict() or {}
            doc_gen = data.get("gen")
            if doc_gen == live:
                continue                       # 메타가 가리키는 것 — 절대 건드리지 않는다
            if doc_gen == gen or (data.get("created_at") or "") < cutoff:
                stale.append(doc.reference)
        for start in range(0, len(stale), 400):
            batch = fs.batch()
            for ref in stale[start:start + 400]:
                batch.delete(ref)
            batch.commit()
    except Exception:
        pass


def read_snapshot(month: int):
    """스냅샷을 원가 기준 DataFrame으로. 없으면 None. **깨졌으면 예외를 던진다.**

    청크가 메타의 개수와 안 맞으면 조용히 일부만 돌려주지 않는다 — 광고주에게 가는
    숫자라서, 잘린 표를 정상처럼 보여주는 것이 가장 나쁜 실패다.
    """
    import pandas as pd

    import google_sheets_writer

    snap = _snap_meta_ref(month).get()
    if not snap.exists:
        return None
    meta = snap.to_dict() or {}
    gen, expected = meta.get("gen"), int(meta.get("chunks") or 0)

    docs = [d for d in _snap_chunks(month).stream()
            if (d.to_dict() or {}).get("gen") == gen]
    if len(docs) != expected:
        raise RuntimeError(
            f"{month}월 스냅샷이 온전하지 않습니다(청크 {len(docs)}/{expected}). "
            "다시 고정해 주세요."
        )

    rows: list = []
    for doc in sorted(docs, key=lambda d: (d.to_dict() or {}).get("seq", 0)):
        rows.extend(json.loads((doc.to_dict() or {})["payload"]))

    df = pd.DataFrame(rows, columns=meta.get("cols") or None)
    for col in google_sheets_writer._NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
