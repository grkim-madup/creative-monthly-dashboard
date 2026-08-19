"""대시보드 전체 화면을 PDF 한 장으로 내보낸다(내부 공유용).

실행: python export_dashboard_pdf.py  → creative-monthly-report/dashboard_report.pdf

PNG 대신 PDF를 쓰는 이유: 텍스트가 벡터로 남아 확대해도 표 숫자가 깨지지 않는다.
주의할 점 두 가지:
- Streamlit은 `body`가 아니라 내부 `[data-testid="stMain"]` div가 스크롤된다. 뷰포트를
  콘텐츠 높이만큼 늘려두지 않으면 첫 화면만 나온다.
- 기본 print 미디어로 찍으면 화면과 색이 달라진다 → `emulate_media("screen")` 필수.
"""

import io
import time

from playwright.sync_api import sync_playwright

URL = "http://localhost:8502/?month=7"
OUT = "creative-monthly-report/dashboard_report.pdf"
WIDTH_PX = 1680

FIND_SCROLLER = """() => {
  const cands = [...document.querySelectorAll('div,section,main')]
    .filter(e => e.scrollHeight > e.clientHeight + 50 && e.clientHeight > 300);
  cands.sort((a, b) => b.scrollHeight - a.scrollHeight);
  const el = cands[0];
  return el ? el.scrollHeight : 0;
}"""

log = io.open("_pdf.txt", "w", encoding="utf-8")

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": WIDTH_PX, "height": 1200})
    page.emulate_media(media="screen")
    page.goto(URL, wait_until="networkidle", timeout=120_000)
    page.wait_for_selector(".foot", timeout=120_000)

    for _ in range(15):
        page.mouse.wheel(0, 2500)
        time.sleep(0.35)
    time.sleep(2)

    content_h = int(page.evaluate(FIND_SCROLLER)) + 140
    page.set_viewport_size({"width": WIDTH_PX, "height": min(content_h, 15000)})
    page.evaluate("() => window.scrollTo(0, 0)")
    time.sleep(3)

    # CSS 픽셀 → 인치 (96dpi). 잘리지 않게 한 장으로 길게 뽑는다.
    page.pdf(
        path=OUT,
        width=f"{WIDTH_PX / 96:.2f}in",
        height=f"{content_h / 96:.2f}in",
        print_background=True,
        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        scale=1,
    )
    log.write("content height(px)=%s → %.2fin\n" % (content_h, content_h / 96))
    browser.close()

log.write("saved: %s\n" % OUT)
log.close()
