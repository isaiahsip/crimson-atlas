"""Custom course colors: pick a color, calendar + schedule update, text stays readable, persists."""
import sys
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://localhost:8765/"); pg.evaluate("localStorage.clear()"); pg.reload()
    pg.wait_for_selector(".result")
    for q in ["ec 10a", "chem 20"]:
        pg.fill("#q", q); pg.wait_for_timeout(300)
        pg.locator(".result").first.locator(".add").click()
    pg.fill("#q", "")
    k0 = pg.locator(".sched-item").first.get_attribute("data-k")
    style = lambda: pg.eval_on_selector(f'.ev.lecture[data-k="{k0}"]', "e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color]")
    print("default:", style())
    pg.locator(".sched-item").first.locator("[data-color]").fill("#ffd84d")  # light yellow
    pg.wait_for_timeout(100)
    print("after yellow (bg, text):", style())
    pg.locator(".sched-item").nth(1).locator("[data-color]").fill("#1f6f5c")
    pg.reload(); pg.wait_for_selector(".sched-item")
    print("after reload:", pg.eval_on_selector_all(".ev.lecture", "es => [...new Set(es.map(e => getComputedStyle(e).backgroundColor))]"))
    pg.screenshot(path=sys.argv[1] if len(sys.argv) > 1 else "colors.png")
    b.close()
print("ERRORS:", errors or "none")
