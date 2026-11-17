"""KOREAN BB ("Multiple Sections"): findable, previewable, pick one section."""
import sys
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://localhost:8765/"); pg.evaluate("localStorage.clear()"); pg.reload()
    pg.wait_for_selector(".result")
    pg.fill("#q", "korean bb"); pg.wait_for_timeout(300)
    r = pg.locator(".result").first
    print("top:", r.locator(".code").inner_text(), "|", r.locator(".when").inner_text())
    r.hover(); pg.wait_for_timeout(150)
    print("hover section previews:", pg.locator(".ev.preview-sec").count())
    r.locator(".add").click(); pg.wait_for_timeout(100)
    print("dashed options:", pg.locator(".ev.option").count())
    pg.click("[data-pick]:has-text('002')"); pg.wait_for_timeout(100)
    print("picked:", pg.locator(".ev.section").count(), "solid,", pg.locator(".ev.option").count(), "dashed |",
          [t.replace("\n", " ") for t in pg.locator(".sched-item .line").all_inner_texts()])
    # time filters treat any section as a match
    pg.fill("#q", "korean"); pg.fill("#after", "10:00"); pg.dispatch_event("#after", "change"); pg.wait_for_timeout(300)
    print("korean, starts after 10am:", pg.locator(".result .code").all_inner_texts())
    pg.screenshot(path=sys.argv[1])
    b.close()
print("ERRORS:", errors or "none")
