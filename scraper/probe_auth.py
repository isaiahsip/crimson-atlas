#!/usr/bin/env python3
"""
One-off probe: fetch a few signed-in my.harvard pages with your session cookie and
save the raw responses to debug/ so the section parser can be written against them.

    python3 scraper/probe_auth.py            # reads cookie from .harvard-cookie

Read-only GET requests only. Nothing is added to your cart.
"""
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import BASE, ROOT, get  # noqa: E402

COOKIE_FILE = os.path.join(ROOT, ".harvard-cookie")
OUT = os.path.join(ROOT, "debug")


def load_cookie():
    if not os.path.exists(COOKIE_FILE):
        sys.exit(f"Missing {COOKIE_FILE}. Copy your my.harvard Cookie header into it.")
    raw = open(COOKIE_FILE).read().strip()
    raw = re.sub(r"^cookie:\s*", "", raw, flags=re.I)  # tolerate a pasted 'Cookie: ...' line
    return raw


def save(name, body):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        f.write(body)
    print(f"  saved {path} ({len(body):,} bytes)")
    return body


def main():
    cookie = load_cookie()
    print("Cookie names:", sorted({c.split("=", 1)[0].strip() for c in cookie.split(";") if "=" in c}))

    # 1. signed-in search results (add-to-cart buttons carry term/school/class number)
    q = urllib.parse.urlencode({"q": "ECON 10A", "school": "FAS", "term": "2027 Spring", "sort": "relevance", "page": 1})
    body = get(f"{BASE}/search/?{q}", cookie=cookie, accept="application/json")
    save("search.json", body)
    try:
        hits = json.loads(body)["hits"]
    except Exception:  # noqa: BLE001
        hits = body
    signed_in = "Sign in to Add to Cart" not in hits
    print("Signed in:", signed_in)
    if not signed_in:
        sys.exit("The cookie didn't sign in. It may have expired. Copy a fresh one and try again.")

    btn = re.search(r'<[^>]*class="[^"]*add-to-cart-button[^"]*"[^>]*>', hits)
    attrs = dict(re.findall(r'(data-[\w-]+)="([^"]*)"', btn.group(0))) if btn else {}
    print("Add-to-cart button attrs:", {k: v[:80] for k, v in attrs.items()})
    term, school, class_nbr = attrs.get("data-term"), attrs.get("data-school"), attrs.get("data-class-number")

    # 2. signed-in course page
    m = re.search(r'href="(/course/[^"]+)"', hits)
    if m:
        save("course.html", get(BASE + m.group(1), cookie=cookie))

    # 3. which carts / programs this student has
    if term:
        carts = save("carts.json", get(f"{BASE}/add-to-cart/available-carts/{term}", cookie=cookie))
        try:
            carts = json.loads(carts)
        except Exception:  # noqa: BLE001
            carts = []
        # 4. cart options = the section picker HTML
        for c in carts[:2]:
            url = f"{BASE}/add-to-cart/cart-options/{c['school']}/{term}/{class_nbr}/{school}/{c['program']}"
            print("GET", url)
            try:
                save(f"cart-options-{c['school']}.html", get(url, cookie=cookie))
            except Exception as e:  # noqa: BLE001
                print("  failed:", e)
    print("\nDone. Tell Claude the probe finished.")


if __name__ == "__main__":
    main()
