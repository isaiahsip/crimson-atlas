"""Q Report chips, sorting, and schedule workload. Needs a local data/q.json (not published)."""
import os, sys
from playwright.sync_api import sync_playwright

if not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "data", "q.json")):
    sys.exit("skipped: no data/q.json (run scraper/q.py)")
errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://localhost:8765/"); pg.evaluate("localStorage.clear()"); pg.reload()
    pg.wait_for_selector(".result")
    print("sort options:", [o for o in pg.locator("#sort option:not([hidden])").all_inner_texts() if "Workload" in o or "Recommended" in o])
    pg.select_option("#sort", "q-rec"); pg.wait_for_timeout(300)
    print("top recommended:", [(r.locator(".code").inner_text().split("\n")[0][:14], r.locator(".tag.q").all_inner_texts()) for r in pg.locator(".result").all()[:3]])
    pg.select_option("#sort", "q-hours"); pg.wait_for_timeout(300)
    print("lightest:", [(r.locator(".code").inner_text().split("\n")[0][:14], r.locator(".tag.q").all_inner_texts()) for r in pg.locator(".result").all()[:3]])
    first = pg.locator(".result").first
    first.locator(".add").click(); pg.wait_for_timeout(100)
    print("schedule summary:", pg.inner_text("#schedSummary"))
    first.locator(".title").click(); pg.wait_for_timeout(300)
    print("drawer Q rows:", pg.locator(".q-terms div").all_inner_texts()[:3])
    pg.screenshot(path=sys.argv[1] if len(sys.argv) > 1 else "q.png")
    b.close()
print("ERRORS:", errors or "none")
