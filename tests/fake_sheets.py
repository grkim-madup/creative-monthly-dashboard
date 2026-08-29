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

    def execute(self):
        return self._result


class _Values:
    def __init__(self, book: "FakeSheets"):
        self.book = book

    def get(self, spreadsheetId=None, range=None, **_):  # noqa: A002, N803
        tab, _row = self.book.parse_range(range)
        return _Execute({"values": [list(r) for r in self.book.tabs.get(tab, [])]})

    def update(self, spreadsheetId=None, range=None, body=None, **_):  # noqa: A002, N803
        tab, row = self.book.parse_range(range)
        self.book.tabs.setdefault(tab, [])
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
        rows = self.book.tabs.setdefault(tab, [])
        for values in body["values"]:
            rows.append(list(values))
        self.book.appends.append(tab)
        return _Execute({})

    def clear(self, spreadsheetId=None, range=None, **_):  # noqa: A002, N803
        tab, _row = self.book.parse_range(range)
        self.book.cleared.append(tab)
        self.book.tabs[tab] = []
        return _Execute({})


class _Spreadsheets:
    def __init__(self, book: "FakeSheets"):
        self.book = book

    def get(self, spreadsheetId=None, **_):  # noqa: N803
        return _Execute({
            "sheets": [
                {"properties": {"title": title, "sheetId": index}}
                for index, title in enumerate(self.book.tabs)
            ]
        })

    def values(self):
        return _Values(self.book)

    def batchUpdate(self, spreadsheetId=None, body=None, **_):  # noqa: N802, N803
        for request in body["requests"]:
            if "addSheet" in request:
                self.book.tabs.setdefault(request["addSheet"]["properties"]["title"], [])
            elif "deleteDimension" in request:
                target = request["deleteDimension"]["range"]
                titles = list(self.book.tabs)
                title = titles[target["sheetId"]]
                rows = self.book.tabs[title]
                del rows[target["startIndex"]:target["endIndex"]]
                self.book.deleted.append((title, target["startIndex"]))
        return _Execute({})


class FakeSheets:
    """탭 이름 → 행 목록(2차원 리스트). 호출 이력도 함께 기록한다."""

    def __init__(self, tabs: dict | None = None):
        self.tabs: dict[str, list[list]] = {k: [list(r) for r in v]
                                           for k, v in (tabs or {}).items()}
        self.cleared: list[str] = []
        self.updates: list[tuple[str, int | None]] = []
        self.appends: list[str] = []
        self.deleted: list[tuple[str, int]] = []

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
