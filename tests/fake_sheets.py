"""구글시트 API를 대신하는 인메모리 가짜 서비스.

동시 저장 사고는 "어떤 API를 어떤 범위로 호출했는가"에서 갈린다(탭 전체 clear냐, 그 행만
갱신이냐). 그래서 google_sheets_writer의 함수를 monkeypatch로 갈아끼우는 대신, **실제
코드가 실제로 보내는 요청**을 이 가짜 서비스가 받아서 흉내낸다. 그렇게 해야
"탭을 clear하지 않았다"를 테스트로 고정할 수 있다(ASA에서 코멘트 5개가 사라진 그 사고의
회귀 테스트가 정확히 이 형태였다).

지원하는 호출만 구현한다: spreadsheets().get / batchUpdate(addSheet·deleteDimension) /
values().get / values().update / values().append / values().clear
"""

from __future__ import annotations


class _Execute:
    def __init__(self, result):
        self._result = result

    def execute(self, **kwargs):
        # 실제 코드는 execute(num_retries=...)로 부른다 — 429·5xx 자동 재시도 옵션이다.
        # 가짜 시트는 재시도할 일이 없으므로 인자만 받아 무시한다.
        return self._result


class _Values:
    def __init__(self, book: "FakeSheets"):
        self.book = book

    def get(self, spreadsheetId=None, range=None, **_):  # noqa: A002, N803
        self.book.calls.append(("get", range))
        tab, _row = self.book.parse_range(range)
        return _Execute({"values": [list(r) for r in self.book.tabs.get(tab, [])]})

    def batchGet(self, spreadsheetId=None, ranges=None, **_):  # noqa: N802, N803
        """여러 탭을 한 번에 읽는다 — 실제 API와 같이 요청 순서대로 돌려준다."""
        self.book.calls.append(("batchGet", tuple(ranges or ())))
        out = []
        for item in ranges or []:
            tab, _row = self.book.parse_range(item)
            out.append({"values": [list(r) for r in self.book.tabs.get(tab, [])]})
        return _Execute({"valueRanges": out})

    def update(self, spreadsheetId=None, range=None, body=None, **_):  # noqa: A002, N803
        tab, row = self.book.parse_range(range)
        self.book.ensure(tab)
        rows = self.book.tabs[tab]
        start = (row or 1) - 1
        while len(rows) < start:
            rows.append([])
        for offset, values in enumerate(body["values"]):
            index = start + offset
            if index < len(rows):
                rows[index] = list(values)
            else:
                rows.append(list(values))
        self.book.updates.append((tab, row))
        return _Execute({})

    def batchUpdate(self, spreadsheetId=None, body=None, **_):  # noqa: N802, N803
        """여러 범위를 한 번에 갱신한다(실제 values.batchUpdate와 같은 형태).

        블록 저장이 행마다 따로 쓰던 것을 한 번의 호출로 묶으면서 필요해졌다.
        내부적으로는 update를 여러 번 부른 것과 결과가 같아야 한다.
        """
        for entry in (body or {}).get("data", []):
            self.update(
                spreadsheetId=spreadsheetId,
                range=entry["range"],
                body={"values": entry["values"]},
            )
        return _Execute({})

    def append(self, spreadsheetId=None, range=None, body=None, **_):  # noqa: A002, N803
        tab, _row = self.book.parse_range(range)
        self.book.ensure(tab)
        rows = self.book.tabs[tab]
        for values in body["values"]:
            rows.append(list(values))
        self.book.appends.append(tab)
        return _Execute({})

    def clear(self, spreadsheetId=None, range=None, **_):  # noqa: A002, N803
        tab, _row = self.book.parse_range(range)
        self.book.cleared.append(tab)
        self.book.ensure(tab)
        self.book.ensure(tab) and None or None
        self.book.tabs[tab] = []
        return _Execute({})


class _Spreadsheets:
    def __init__(self, book: "FakeSheets"):
        self.book = book

    def get(self, spreadsheetId=None, **_):  # noqa: N803
        return _Execute({
            "sheets": [
                {"properties": {"title": title,
                                "sheetId": self.book.sheet_ids.setdefault(
                                    title, self.book._new_id())}}
                for title in self.book.tabs
            ]
        })

    def values(self):
        return _Values(self.book)

    def batchUpdate(self, spreadsheetId=None, body=None, **_):  # noqa: N802, N803
        for request in body["requests"]:
            if "addSheet" in request:
                title = request["addSheet"]["properties"]["title"]
                if title in self.book.tabs:
                    # 실제 API와 같이 거절한다 — 동시에 같은 탭을 만들려는 경우.
                    raise RuntimeError(
                        f'Invalid requests: A sheet with the name "{title}" already exists.'
                    )
                self.book.ensure(title)
            elif "deleteSheet" in request:
                title = self.book.title_of(request["deleteSheet"]["sheetId"])
                if title is None or title not in self.book.tabs:
                    raise RuntimeError("Invalid requests: No sheet with the given id.")
                self.book.tabs.pop(title)
                self.book.sheet_ids.pop(title, None)
            elif "updateSheetProperties" in request:
                props = request["updateSheetProperties"]["properties"]
                title = self.book.title_of(props["sheetId"])
                if title is None or title not in self.book.tabs:
                    raise RuntimeError("Invalid requests: No sheet with the given id.")
                rows = self.book.tabs.pop(title)
                sheet_id = self.book.sheet_ids.pop(title)
                self.book.tabs[props["title"]] = rows
                self.book.sheet_ids[props["title"]] = sheet_id
            elif "deleteDimension" in request:
                target = request["deleteDimension"]["range"]
                title = self.book.title_of(target["sheetId"])
                if title is None:
                    continue
                rows = self.book.tabs[title]
                del rows[target["startIndex"]:target["endIndex"]]
                self.book.deleted.append((title, target["startIndex"]))
        return _Execute({})


class FakeSheets:
    """탭 이름 → 행 목록(2차원 리스트). 호출 이력도 함께 기록한다."""

    def __init__(self, tabs: dict | None = None):
        self.tabs: dict[str, list[list]] = {k: [list(r) for r in v]
                                           for k, v in (tabs or {}).items()}
        # 실제 시트의 sheetId는 탭을 지워도 바뀌지 않는 고정값이다. 순번으로 흉내 내면
        # '삭제 + 개명'을 한 요청으로 보내는 코드가 엉뚱한 탭을 건드려도 통과해 버린다.
        self._next_id = 0
        self.sheet_ids: dict[str, int] = {}
        for title in self.tabs:
            self.sheet_ids[title] = self._new_id()
        # 읽기 호출 이력 — "조작 한 번에 시트를 몇 번 읽었나"를 테스트로 고정한다.
        # 구글 시트 API의 진짜 상한이 분당 60회 읽기라서, 이 숫자가 곧 동시 사용 가능 인원이다.
        self.calls: list[tuple] = []
        self.cleared: list[str] = []
        self.updates: list[tuple[str, int | None]] = []
        self.appends: list[str] = []
        self.deleted: list[tuple[str, int]] = []

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def ensure(self, title: str) -> int:
        """탭이 없으면 만들고 그 고정 id를 돌려준다."""
        if title not in self.tabs:
            self.tabs[title] = []
            self.sheet_ids[title] = self._new_id()
        return self.sheet_ids[title]

    def title_of(self, sheet_id: int):
        for title, value in self.sheet_ids.items():
            if value == sheet_id:
                return title
        return None

    @staticmethod
    def parse_range(value):
        text = str(value or "")
        if "!" not in text:
            return text, None
        tab, cell = text.split("!", 1)
        digits = "".join(c for c in cell if c.isdigit())
        return tab, int(digits) if digits else None

    def spreadsheets(self):
        return _Spreadsheets(self)


def install(monkeypatch, writer, tabs: dict | None = None) -> FakeSheets:
    """writer(google_sheets_writer)가 이 가짜 시트를 쓰도록 붙인다."""
    book = FakeSheets(tabs)
    # conftest가 기본값을 "시트 없음"으로 잠가 두므로, 여기서 명시적으로 다시 켠다.
    monkeypatch.setattr(writer, "configured", lambda: True)
    monkeypatch.setattr(writer, "_service", lambda: book)
    monkeypatch.setattr(writer, "_service_account_info", lambda: {"fake": True})
    monkeypatch.setattr(writer, "_sheet_id", lambda: "fake-sheet-id")
    monkeypatch.setattr(writer, "_secret", lambda name: "fake-sheet-id")
    # 탭 목록 캐시는 프로세스 전역이라 테스트 사이에 샌다 — 붙일 때 비우고,
    # 테스트가 끝난 뒤에도 비워지도록 monkeypatch 해제 시점에 한 번 더 건다.
    writer._clear_tabs_cache()
    writer._clear_ids_cache()
    monkeypatch.setattr(writer, "_tabs_cache", None, raising=False)
    monkeypatch.setattr(writer, "_ids_cache", None, raising=False)
    writer.clear_image_cache()
    return book
