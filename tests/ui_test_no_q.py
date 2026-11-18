"""Without data/q.json (as on the public site), no Q feature should appear anywhere."""
import sys
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route("**/data/q.json", lambda r: r.fulfill(status=404, body="not found"))  # simulate the published site
    pg.goto("http://localhost:8765/"); pg.evaluate("localStorage.setItem('crimson-atlas-v1', JSON.stringify({sort: 'q-rec'}))"); pg.reload()
    pg.wait_for_selector(".result")
    print("sort falls back to:", pg.input_value("#sort"))
    print("visible Q sort options:", pg.locator("#sort option.q-only:not([hidden])").count())
    pg.fill("#q", "ec 10a"); pg.wait_for_timeout(300)
    r = pg.locator(".result").first
    r.locator(".add").click(); pg.wait_for_timeout(100)
    r.locator(".title").click(); pg.wait_for_timeout(300)
    print("Q chips:", pg.locator(".tag.q").count(), "| Q panel:", pg.locator(".qpanel").count(),
          "| 'no Q data' text:", pg.locator("text=/no Q/i").count(), "| summary:", pg.inner_text("#schedSummary"))
    b.close()
print("ERRORS:", errors or "none")
