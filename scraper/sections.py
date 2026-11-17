#!/usr/bin/env python3
"""
Fetch discussion/lab section times using your signed-in my.harvard session.

    python3 scraper/sections.py                 # courses flagged "requires sections"
    python3 scraper/sections.py --all           # every course with a class number (slow)
    python3 scraper/sections.py --refresh       # re-fetch courses that already have sections

Reads the cookie from .harvard-cookie and updates data/courses.json in place.
Requires that scrape.py was run with --details (for class numbers).
Read-only GET requests, the same ones the Add to Cart popup makes. Nothing is added to your cart.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import BASE, DATA_DIR, ROOT, get, parse_meetings, text  # noqa: E402

COOKIE_FILE = os.path.join(ROOT, ".harvard-cookie")
COURSES = os.path.join(DATA_DIR, "courses.json")


class AuthError(Exception):
    pass


def load_cookie():
    if not os.path.exists(COOKIE_FILE) or not open(COOKIE_FILE).read().strip():
        sys.exit("Missing .harvard-cookie. See README → Discussion sections.")
    return re.sub(r"^cookie:\s*", "", open(COOKIE_FILE).read().strip(), flags=re.I)


def term_code(term, cookie):
    """'2027 Spring' -> '2272', read from the add-to-cart button of a signed-in search."""
    q = urllib.parse.urlencode({"q": "", "school": "FAS", "term": term, "page": 1})
    body = get(f"{BASE}/search/?{q}", cookie=cookie, accept="application/json")
    hits = json.loads(body).get("hits", "")
    if "Sign in to Add to Cart" in hits:
        raise AuthError("Your my.harvard session has expired. Copy a fresh cookie into .harvard-cookie.")
    m = re.search(r'data-term="(\d+)"', hits)
    if not m:
        raise RuntimeError(f"Couldn't find the term code for {term}")
    return m.group(1)


def parse_sections(page):
    """Parse the Add to Cart form's related/auto-enroll section blocks into section options."""
    sections = []
    blocks = re.split(r"<!-- (?:Related|Autoenroll) Section \d -->", page)[1:]
    for blk in blocks:
        blk = re.split(r"<!-- End (?:Related|Autoenroll) Section", blk)[0]
        lab = re.search(r'section\d-label"[^>]*data-component-code="(\w*)"[^>]*>([^<]*)<', blk)
        if not lab:
            continue
        code, component = lab.group(1), text(lab.group(2)) or lab.group(1)
        items = re.split(r'<label class="js-select-simulation-item', blk)[1:]
        if not items:  # single option shown statically (often an unscheduled placeholder)
            m = re.search(r'<span data-title[^>]*>(.*?)</span>.*?value="?(\d+)', blk, re.S)
            if m:
                items = [f'data-simulation-title="{m.group(1)}" value="{m.group(2)}"' + blk]
        for item in items:
            title = re.search(r'data-simulation-title="([^"]*)"', item)
            value = re.search(r'value="?(\d+)', item)
            label = re.sub(r"^Section\s+", "", text(title.group(1)) if title else "Section")
            spans = [text(x) for x in re.findall(r"<span>(.*?)</span>", item, re.S)]
            notes = [x for x in spans if x and not re.search(r"to be announced|\d:\d\d\s*[ap]m", x, re.I)]
            sections.append({
                "id": value.group(1) if value else f"{code}-{label}",
                "label": label,
                "component": component,
                "componentCode": code,
                "meetings": parse_meetings(item),
                **({"notes": notes} if notes else {}),
            })
    return sections


def main():
    sys.stdout.reconfigure(line_buffering=True)  # show progress live even when output goes to a file
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--term", help='only this term, e.g. "2027 Spring"')
    ap.add_argument("--all", action="store_true", help="check every course, not just ones flagged as needing sections")
    ap.add_argument("--refresh", action="store_true", help="re-fetch courses already done")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    cookie = load_cookie()
    courses = json.load(open(COURSES))
    todo = [c for c in courses
            if c.get("classNumber")
            and (args.all or c.get("needsSections"))
            and (not args.term or c["term"] == args.term)
            and (args.refresh or "sectionsFetched" not in c)]
    if not todo:
        print("Nothing to fetch. Run scrape.py --details first, or pass --refresh.")
        return

    try:
        carts = {}
        codes = {}
        for term in sorted({c["term"] for c in todo}):
            codes[term] = term_code(term, cookie)
            carts[term] = json.loads(get(f"{BASE}/add-to-cart/available-carts/{codes[term]}", cookie=cookie))
            if not carts[term]:
                sys.exit(f"No cart available for {term} on your account.")
            print(f"{term}: term code {codes[term]}, cart {carts[term][0]['school']}/{carts[term][0]['program']}")
    except AuthError as e:
        sys.exit(str(e))

    lock = threading.Lock()
    stop = threading.Event()
    done = [0]
    failures = [0]

    def save():
        tmp = COURSES + ".tmp"
        with open(tmp, "w") as f:
            json.dump(courses, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, COURSES)

    def fetch(c):
        if stop.is_set():
            return
        time.sleep(args.delay)
        cart = carts[c["term"]][0]
        url = f"{BASE}/add-to-cart/cart-options/{cart['school']}/{codes[c['term']]}/{c['classNumber']}/{c['school'] or 'FAS'}/{cart['program']}"
        try:
            page = get(url, cookie=cookie, retries=2)
        except Exception as e:  # noqa: BLE001
            print(f"  {c['code']}: {e}", file=sys.stderr)
            with lock:
                failures[0] += 1
            return
        if "cart-credits" not in page and "related-section" not in page:
            # login page or error page instead of the cart form
            with lock:
                failures[0] += 1
                if failures[0] >= 5 and done[0] == 0 or failures[0] >= 15:
                    stop.set()
            return
        secs = parse_sections(page)
        with lock:
            c["sections"] = secs
            c["sectionsFetched"] = time.strftime("%Y-%m-%d")
            done[0] += 1
            if secs:
                print(f"  {c['code']}: {len(secs)} section(s)")
            if done[0] % 25 == 0:
                save()

    print(f"Fetching sections for {len(todo)} courses…")
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(fetch, todo))
    save()
    with_secs = sum(1 for c in courses if c.get("sections"))
    print(f"Done: {done[0]} fetched, {failures[0]} failed. {with_secs} courses now have section times.")
    if stop.is_set():
        sys.exit("Stopped early after repeated failures. Your session may have expired; refresh .harvard-cookie and rerun (finished courses are kept).")


if __name__ == "__main__":
    main()
