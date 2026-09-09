# -*- coding: utf-8 -*-
"""백업 — 화면 버튼과 터미널이 **같은 로직**을 쓰는지, 실패를 삼키지 않는지.

이 프로젝트의 최대 실패 비용은 "코멘트 유실 = 복구 불가"다. 백업이 조용히
반쪽만 담기면 정작 복구할 때 없다 — 그 경로를 고정한다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import backup

ENTRYPOINTS = ("creative_dashboard.py", "app.py")


def entrypoints():
    found = [(n, pathlib.Path(n).read_text(encoding="utf-8"))
             for n in ENTRYPOINTS if pathlib.Path(n).exists()]
    if not found:
        pytest.skip("진입점을 찾지 못했습니다")
    return found


# --------------------------------------------------------------------- 순수 로직

def test_HTML을_평문으로_바꾼다():
    got = backup.plain("<p>첫 줄</p><p>둘째 줄</p><ul><li>가</li></ul>")
    assert "첫 줄" in got and "둘째 줄" in got and "- 가" in got
    assert "<" not in got


def test_이스케이프된_문자를_되돌린다():
    """백업의 요점은 읽을 수 있는 것이다 — `&amp;`가 그대로 남으면 안 된다."""
    assert backup.plain("<p>COMIC &amp; HASHTAG</p>") == "COMIC & HASHTAG"


def test_빈_값도_안전하다():
    assert backup.plain(None) == ""
    assert backup.plain("") == ""


def test_요약에_어느_달인지와_분량이_찍힌다():
    """분량이 안 보이면 백업이 됐는지 알 수 없다(고정 패널과 같은 이유).

    ⚠ 달 **수**가 아니라 **어느 달인지**를 쓴다 — `2개월`이라고만 찍었더니
      규리님이 *"2개월은 무슨 표시야?"* 라고 물었다(2026-09-09).
    """
    data = {"months": {"7": {"blocks": [1]}, "8": {"blocks": [1, 2, 3], "picks": [1]}}}
    got = backup.summary(data)
    assert "7·8월" in got, got
    assert "개월" not in got, f"달 수만 찍으면 무슨 뜻인지 모른다: {got}"
    assert "코멘트 4건" in got and "수기지정 1건" in got


def test_한_파일로_묶는다():
    """버튼이 둘이면 "뭘 눌러야 하나"를 매번 판단해야 한다 — 백업은 그럴 일이
    아니다(규리님 2026-09-09). 복원용 JSON과 읽을 수 있는 md가 함께 들어간다."""
    import io
    import zipfile

    data = {"backed_up_at": "2026-09-09 15:00", "months": {"8": {"blocks": [
        {"slot": "next_step", "seq": 0, "block": {"title": "제안", "comment": "<p>글</p>"}},
    ]}}}
    archive = zipfile.ZipFile(io.BytesIO(backup.to_zip(data, "20260909_1500")))
    assert set(archive.namelist()) == {"comments_20260909_1500.json",
                                       "comments_20260909_1500.md"}
    assert "글" in archive.read("comments_20260909_1500.md").decode("utf-8")


def test_빈_백업은_그렇다고_말한다():
    assert "없습니다" in backup.summary({"months": {}})


def test_마크다운에_블록_제목과_본문이_들어간다():
    data = {"backed_up_at": "2026-09-09 10:00", "months": {"8": {"blocks": [
        {"slot": "next_step", "seq": 0,
         "block": {"title": "신규 USP 제안", "comment": "<p>본문</p>",
                   "insight": "<p>액션</p>"}},
    ]}}}
    got = backup.to_markdown(data)
    assert "## 8월" in got
    assert "NEXT STEP" in got and "신규 USP 제안" in got
    assert "본문" in got and "액션" in got


def test_제목이_없어도_깨지지_않는다():
    data = {"months": {"8": {"blocks": [{"slot": "analysis", "block": {}}]}}}
    assert "(제목 없음)" in backup.to_markdown(data)


def test_읽기_실패를_삼키지_않는다():
    """`error`가 나면 그 사실이 호출자에게 올라와야 한다."""
    calls = {"n": 0}

    def always_error():
        calls["n"] += 1
        return "error", None, "quota"

    status, data, reason = backup._retry(always_error, attempts=2, sleep=0)
    assert status == "error" and reason == "quota" and calls["n"] == 2


def test_한_번_성공하면_더_시도하지_않는다():
    calls = {"n": 0}

    def ok_once():
        calls["n"] += 1
        return "ok", [1], None

    assert backup._retry(ok_once, attempts=3, sleep=0)[0] == "ok"
    assert calls["n"] == 1


# --------------------------------------------------------------------- 화면 배선

def test_백업_버튼이_편집_권한자에게만_보인다():
    """광고주와 화면을 공유하는 리포트다."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        guarded = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "editor_allowed" in ast.unparse(node.test):
                # 2026-09-09: full-width 버튼 → `source_row(... icon="⬇")` 줄 문법.
                block = ast.unparse(node)
                if "source_row" in block and "'backup'" in block:
                    guarded = True
        assert guarded, f"{name}: 백업 줄이 editor_allowed 안에 없다"


def test_화면이_backup_모듈을_쓴다():
    """진입점에 로직을 다시 적으면 터미널 경로와 갈라진다."""
    for name, source in entrypoints():
        assert "backup.collect()" in source, name
        # 2026-09-09: 버튼을 하나로 합쳐 zip으로 내려준다.
        assert "backup.to_zip" in source, name
        assert "backup.summary" in source, name


def test_모으기는_버튼을_누른_리런에만_일어난다():
    """매 리런마다 모으면 무료 한도를 태운다(2026-09-08 사고)."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        # 버튼 결과를 담은 이름들(`source_row`가 돌려준 것 포함).
        click_names = {
            target.elts[0].id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and "source_row" in ast.unparse(node.value.func)
            for target in node.targets
            if isinstance(target, ast.Tuple) and isinstance(target.elts[0], ast.Name)
        }
        inside_click = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = ast.unparse(node.test)
            gated = "st.button" in test or test.strip() in click_names
            if gated and "backup.collect()" in ast.unparse(node):
                inside_click = True
        assert inside_click, f"{name}: backup.collect()가 클릭 조건 안에 없다"


def test_서버에_파일로_저장하지_않는다():
    """madup.app은 영속 볼륨이 없어 서버에 쓴 파일은 재배포 때 사라진다."""
    for name, source in entrypoints():
        tree = ast.parse(source)
        # `editor_allowed`를 언급하는 블록은 여러 겹이다 — **가장 작은 것**을 본다.
        # 큰 조상 블록을 잡으면 사이드바 전체가 들어와 무관한 코드까지 검사한다.
        blocks = [ast.unparse(node) for node in ast.walk(tree)
                  if isinstance(node, ast.If)
                  and "editor_allowed" in ast.unparse(node.test)
                  and "backup.collect()" in ast.unparse(node)]
        assert blocks, f"{name}: 백업 블록을 찾지 못했습니다"
        body = min(blocks, key=len)
        assert "write_text" not in body, f"{name}: 백업을 서버 파일로 쓴다"
        assert "st.download_button" in body or "download_button" in body,             f"{name}: 다운로드 버튼이 없다"


def test_터미널_도구가_같은_로직을_쓴다():
    tool = pathlib.Path("tools/backup_comments.py")
    if not tool.exists():   # 배포 복사본에는 tools/가 없다
        pytest.skip("tools/backup_comments.py 없음 (배포 복사본)")
    source = tool.read_text(encoding="utf-8")
    assert "import backup" in source
    assert "backup.collect(" in source
    # 로직을 다시 적었는지 — 평문 변환·마크다운 조립이 여기 있으면 두 벌이다.
    assert "re.sub" not in source, "평문 변환을 다시 적었다 (backup.plain을 쓸 것)"
    assert "SLOT_LABEL" not in source, "라벨을 다시 적었다 (backup 모듈을 쓸 것)"
