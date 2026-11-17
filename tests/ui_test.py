"""Smoke test: python3 tests/ui_test.py [screenshot.png]  (expects the site served on :8765)."""
import sys
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
    pg.goto("http://localhost:8765/")
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.wait_for_selector(".result")
    print("initial:", pg.inner_text("#resultMeta"))

    pg.fill("#q", "ec 10a"); pg.wait_for_timeout(300)
    r = pg.locator(".result").first
    print("top result:", r.locator(".code").inner_text())
    r.hover(); pg.wait_for_timeout(150)
    print("hover -> lecture previews:", pg.locator(".ev.preview").count(), "section previews:", pg.locator(".ev.preview-sec").count())
    r.locator(".add").click(); pg.wait_for_timeout(100)
    print("added -> lecture:", pg.locator(".ev.lecture").count(), "dashed options:", pg.locator(".ev.option").count())

    # manual option joins the Discussion group
    pg.click("[data-addopt]")
    pg.click(".section-form .days button[data-d=Mo]")
    pg.fill(".section-form input[name=start]", "15:00"); pg.fill(".section-form input[name=end]", "16:00")
    pg.click(".section-form button[type=submit]"); pg.wait_for_timeout(100)
    print("after manual add -> options:", pg.locator(".ev.option").count(), "| form still open:", pg.locator(".section-form").count())
    pg.locator(".ev.option").first.click(); pg.wait_for_timeout(100)
    print("picked -> sections:", pg.locator(".ev.section").count(), "options:", pg.locator(".ev.option").count())
    print("schedule line:", pg.locator(".sched-item .line").nth(1).inner_text())

    # multi-component course
    pg.fill("#q", "chem 27"); pg.wait_for_timeout(300)
    pg.locator(".result").first.locator(".add").click(); pg.wait_for_timeout(100)
    item = pg.locator(".sched-item").nth(1)
    print("CHEM 27 lines:", [t[:70] for t in item.locator(".line").all_inner_texts()])
    pg.fill("#q", "")
    pg.check("#fits"); pg.wait_for_timeout(300)
    print("fits my schedule ->", pg.inner_text("#resultMeta"))
    pg.uncheck("#fits")
    pg.reload(); pg.wait_for_selector(".sched-item")
    print("after reload -> picked sections:", pg.locator(".ev.section").count())
    pg.screenshot(path=sys.argv[1] if len(sys.argv) > 1 else "ui.png")
    b.close()
print("ERRORS:", errors or "none")
