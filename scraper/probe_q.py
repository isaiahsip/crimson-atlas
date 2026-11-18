#!/usr/bin/env python3
"""
One-off probe for Q Reports: fetch one course's Q search page (and one report, if possible)
with your signed-in cookies and save the raw pages to debug/ so a parser can be written.

    python3 scraper/probe_q.py

Cookies (both files are gitignored):
    .harvard-q-cookie      Cookie header from a request to qreports.fas.harvard.edu
    .harvard-blue-cookie   Cookie header from a request to harvard.bluera.com (optional)

Read-only GET requests. Cookies are only ever sent to the site they came from.
"""
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import ROOT, SSL_CTX  # noqa: E402

OUT = os.path.join(ROOT, "debug")
COOKIES = {
    "qreports.fas.harvard.edu": os.path.join(ROOT, ".harvard-q-cookie"),
    "harvard.bluera.com": os.path.join(ROOT, ".harvard-blue-cookie"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # never follow: a redirect would carry the cookie elsewhere
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=SSL_CTX))


def cookie_for(url):
    host = urllib.parse.urlparse(url).hostname
    path = COOKIES.get(host)
    if not path or not os.path.exists(path):
        return None
    raw = open(path).read().strip()
    return re.sub(r"^cookie:\s*", "", raw, flags=re.I) or None


def fetch(url):
    """GET with the cookie for that host only. Returns (status, body, redirect_location)."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh) crimson-atlas personal Q probe"}
    ck = cookie_for(url)
    if ck:
        headers["Cookie"] = ck
    try:
        with OPENER.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("Location")


def save(name, body):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as f:
        f.write(body)
    print(f"  saved debug/{name} ({len(body):,} bytes)")


def main():
    if not cookie_for("https://qreports.fas.harvard.edu/"):
        sys.exit("Missing .harvard-q-cookie (Cookie header from qreports.fas.harvard.edu).")
    url = "https://qreports.fas.harvard.edu/search/courses?school=FAS&search=113326"  # ECON 10A
    status, body, loc = fetch(url)
    print("search page:", status, f"-> {loc[:70]}…" if loc else "")
    if status != 200:
        sys.exit("Not signed in to qreports (cookie expired or wrong site). Copy a fresh cookie and retry.")
    save("q-search.html", body)
    links = sorted(set(re.findall(r'href="(https?://[^"]+)"', body)))
    reports = [l for l in links if "bluera" in l or "rpv" in l.lower()]
    print(f"links on page: {len(links)}, report links: {len(reports)}")
    for l in reports[:5]:
        print("   ", l[:140])
    if reports:
        target = reports[0].replace("&amp;", "&")
        status, body, loc = fetch(target)
        print("report page:", status, f"-> {loc[:70]}…" if loc else "")
        if status == 200:
            save("q-report.html", body)
        else:
            print("  Couldn't open the report with the cookies provided. Add .harvard-blue-cookie and rerun.")
    print("\nDone. Tell Claude the probe finished.")


if __name__ == "__main__":
    main()
