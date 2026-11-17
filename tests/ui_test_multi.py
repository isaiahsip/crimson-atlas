"""CHEM 20: pick a posted discussion AND a hand-entered lab at the same time."""
import sys
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://localhost:8765/"); pg.evaluate("localStorage.clear()"); pg.reload()
    pg.wait_for_selector(".result")
    pg.fill("#q", "chem 20"); pg.wait_for_timeout(300)
    pg.locator(".result").first.locator(".add").click()
    pg.click("[data-addopt]")
    print("type choices:", pg.locator(".section-form select[name=component] option").all_inner_texts(),
          "| default:", pg.input_value(".section-form select[name=component]"), "| label:", pg.input_value(".section-form input[name=label]"))
    pg.select_option(".section-form select[name=component]", "Laboratory")
    pg.click(".section-form .days button[data-d=Tu]")
    pg.fill(".section-form input[name=start]", "13:30"); pg.fill(".section-form input[name=end]", "16:30")
    pg.click(".section-form button[type=submit]"); pg.wait_for_timeout(100)
    pg.click("[data-addopt]")  # close form
    print("lines:", [t.replace("\n", " ")[:80] for t in pg.locator(".sched-item .line").all_inner_texts()])
    pg.click("[data-pick]:has-text('DW6A')"); pg.wait_for_timeout(50)
    pg.click("[data-pick]:has-text('Lab 1')"); pg.wait_for_timeout(50)
    print("solid section blocks:", pg.locator(".ev.section").count(), "| dashed left:", pg.locator(".ev.option").count())
    print("picked lines:", [t.replace("\n", " ")[:80] for t in pg.locator(".sched-item .line").all_inner_texts()])
    pg.screenshot(path=sys.argv[1])
    b.close()
print("ERRORS:", errors or "none")
