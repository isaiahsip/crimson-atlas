"""Drafts + export/import + share links."""
import json, os, sys, tempfile
from playwright.sync_api import sync_playwright

URL = "http://localhost:8765/"
errors = []
drafts = lambda pg: pg.locator("#draftSel option").all_inner_texts()

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(URL)

    # 1. a schedule saved before drafts existed is migrated into "Schedule 1"
    pg.evaluate("""localStorage.setItem('crimson-atlas-v1', JSON.stringify({term: '2027 Spring',
        schedule: {'2027 Spring|113326|1|Full Term': {color: '#2563eb', picks: {}, options: []}}}))""")
    pg.reload(); pg.wait_for_selector(".sched-item")
    print("1 migrated:", drafts(pg), "| heading:", pg.inner_text("#schedTitle"))

    # 2. build it out a bit, then export
    pg.click("[data-pick]:has-text('D002')")
    pg.fill("#q", "chem 20"); pg.wait_for_timeout(300); pg.locator(".result").first.locator(".add").click(); pg.fill("#q", "")
    with pg.expect_download() as dl:
        pg.click("#exportBtn")
    path = os.path.join(tempfile.mkdtemp(), dl.value.suggested_filename); dl.value.save_as(path)
    data = json.load(open(path))
    print("2 exported:", dl.value.suggested_filename, "|", [(c["code"], c["color"], c["picks"]) for c in data["courses"]])

    # 3. new empty draft, import -> dialog -> Replace fills the current draft
    pg.click("#draftNew"); pg.wait_for_timeout(100)
    print("3 after New:", drafts(pg), "| blocks:", pg.locator(".ev.lecture").count())
    pg.set_input_files("#importFile", path); pg.wait_for_selector("#importDialog[open]")
    print("  dialog:", pg.inner_text("#importMsg"))
    pg.click("#importDialog [data-choice=replace]"); pg.wait_for_timeout(300)
    print("  replace:", drafts(pg), "| sections:", pg.locator(".ev.section").count())

    # 4. import again -> New draft; then once more -> Cancel changes nothing
    pg.set_input_files("#importFile", path); pg.wait_for_selector("#importDialog[open]")
    pg.click("#importDialog [data-choice=new]"); pg.wait_for_timeout(300)
    print("4 new draft:", drafts(pg), "| active:", pg.inner_text("#schedTitle"))
    pg.set_input_files("#importFile", path); pg.wait_for_selector("#importDialog[open]")
    pg.click("#importDialog [data-choice=cancel]"); pg.wait_for_timeout(200)
    print("  cancel:", drafts(pg))

    # 5. switching drafts swaps the calendar; duplicate / rename / delete
    pg.select_option("#draftSel", index=0); pg.wait_for_timeout(100)
    print("5 switched to", pg.inner_text("#schedTitle"), "| courses:", pg.locator(".sched-item").count())
    pg.click("#draftDup"); pg.wait_for_timeout(100)
    pg.once("dialog", lambda d: d.accept("Plan B"))
    pg.click("#draftRename"); pg.wait_for_timeout(100)
    print("  dup+rename:", drafts(pg))
    pg.once("dialog", lambda d: d.accept())
    pg.click("#draftDelete"); pg.wait_for_timeout(100)
    print("  after delete:", drafts(pg))

    # 6. share link -> fresh browser imports it into its empty default draft
    pg.select_option("#draftSel", index=0); pg.wait_for_timeout(100)
    pg.click("#shareBtn"); pg.wait_for_timeout(200)
    link = pg.evaluate("navigator.clipboard.readText()")
    print("6 link length:", len(link))
    ctx2 = b.new_context(viewport={"width": 1440, "height": 1000}); pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errors.append(str(e)))
    pg2.goto(link); pg2.wait_for_selector("#importDialog[open]")
    pg2.click("#importDialog [data-choice=replace]"); pg2.wait_for_selector(".sched-item")
    print("  fresh browser:", drafts(pg2), "| sections:", pg2.locator(".ev.section").count(), "| hash cleared:", pg2.url == URL)

    # 7. everything persists
    pg.reload(); pg.wait_for_selector("#draftSel option", state="attached")
    print("7 after reload:", drafts(pg))
    pg.screenshot(path=sys.argv[1] if len(sys.argv) > 1 else "drafts.png")
    b.close()
print("ERRORS:", errors or "none")
