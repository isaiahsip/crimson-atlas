#!/usr/bin/env python3
"""
Scrape Harvard course listings from my.harvard's public course search.

    python3 scraper/scrape.py --term "2027 Spring" --school FAS
    python3 scraper/scrape.py --term "2027 Spring" --school FAS --details

Writes data/courses.json (merged across runs, keyed by term + course id) and
data/index.json (list of available terms) for the web app.

Only uses the standard library. Be polite: requests are rate-limited.
"""
import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://my.harvard.edu"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
UA = "atlas-for-harvard course scraper (personal, non-commercial)"

DAY_MAP = {
    "Sunday": "Su", "Monday": "Mo", "Tuesday": "Tu", "Wednesday": "We",
    "Thursday": "Th", "Friday": "Fr", "Saturday": "Sa",
}

def day_code(name):
    """'Monday' / 'Mondey' / 'Thursday' -> 'Mo' / 'Mo' / 'Th' (my.harvard has typos in day labels)."""
    return {"su": "Su", "mo": "Mo", "tu": "Tu", "we": "We", "th": "Th", "fr": "Fr", "sa": "Sa"}.get(name[:2].lower())


# ---------------------------------------------------------------- http

def _ssl_context():
    # python.org builds on macOS ship without CA certs; fall back to the system bundle / certifi.
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats()["x509_ca"]:
        return ctx
    for cafile in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ctx


SSL_CTX = _ssl_context()


def get(url, cookie=None, retries=4, accept=None):
    headers = {"User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    if accept:
        headers["Accept"] = accept
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  retry {attempt + 1} for {url} ({e}); sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)


# ---------------------------------------------------------------- parsing helpers

def text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def to_minutes(t):
    """'10:30am' -> 630"""
    m = re.match(r"(\d{1,2}):(\d\d)\s*([ap])m", t.strip().lower())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if h == 12:
        h = 0
    if ap == "p":
        h += 12
    return h * 60 + mi


TIME_RE = re.compile(r"(\d{1,2}:\d\d\s*[ap]m)\s*-\s*(\d{1,2}:\d\d\s*[ap]m)", re.I)
WEEKDAYS_RE = re.compile(r'role="group"\s+aria-label="Week Days"(.*?)</div>\s*(?=<)', re.S)


def parse_meetings(block):
    """Pair every 'Week Days' group with the time range that follows it."""
    meetings = []
    starts = [m.start() for m in re.finditer(r'aria-label="Week Days"', block)]
    if not starts:
        return meetings
    starts.append(len(block))
    for i in range(len(starts) - 1):
        seg = block[starts[i]:starts[i + 1]]
        days = [day_code(d) for d in re.findall(r'aria-label="(\w+), selected"', seg) if day_code(d)]
        tm = TIME_RE.search(seg)
        # Split schedules put a date range *before* the day group; grab the one before.
        prev = block[starts[i - 1] if i else 0:starts[i]]
        dates = re.findall(r"<span>([A-Z][a-z]{2,4}\.? \d{1,2}, \d{4} – [A-Z][a-z]{2,4}\.? \d{1,2}, \d{4})</span>", prev)
        m = {"days": days}
        if tm:
            m["start"] = to_minutes(tm.group(1))
            m["end"] = to_minutes(tm.group(2))
        else:
            m["tba"] = True
        if dates:
            m["dates"] = html.unescape(dates[-1])
        if days or tm:
            meetings.append(m)
    return meetings


def parse_card(card):
    c = {}
    m = re.search(r'data-course-id="(\d+)"\s+data-crse-offer-nbr="(\d+)"', card)
    if not m:
        return None
    c["courseId"], c["offerNbr"] = m.group(1), m.group(2)

    m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', card, re.S)
    if m:
        c["title"] = text(m.group(2))
    m = re.search(r'href="(/course/[^"]+)"', card)
    if m:
        c["url"] = BASE + html.unescape(m.group(1))
    m = re.search(r'badge badge-light[^>]*>([^<]+)<', card)
    code = text(m.group(1)) if m else ""
    c["code"] = re.sub(r"\s+", " ", code)
    parts = c["code"].split(" ", 1)
    c["subject"] = parts[0]
    c["catalog"] = parts[1] if len(parts) > 1 else ""

    c["instructors"] = [text(x) for x in re.findall(r'href="/instructor/[^"]*"[^>]*>.*?<span class="link-body">(.*?)</span>', card, re.S)]
    m = re.search(r'href="/school/([^"]+)"', card)
    c["school"] = m.group(1) if m else ""
    m = re.search(r'Department%2FField=([^"&]+)"', card)
    c["department"] = urllib.parse.unquote_plus(html.unescape(m.group(1))) if m else ""

    # description: the longest text-ish div in the left column
    m = re.search(r'<div class="course-description[^"]*">(.*?)</div>', card, re.S)
    c["description"] = text(m.group(1)) if m else ""

    right = card.split("<!-- End Col -->", 1)[1] if "<!-- End Col -->" in card else card
    spans = [text(s) for s in re.findall(r"<span>(.*?)</span>", right, re.S)]
    c["term"] = next((s for s in spans if re.match(r"^\d{4} (Spring|Fall|Summer|Winter|January)", s)), "")
    sess_idx = spans.index(c["term"]) + 1 if c["term"] in spans else None
    c["session"] = spans[sess_idx] if sess_idx is not None and sess_idx < len(spans) else ""
    c["meetings"] = parse_meetings(right)
    m = re.search(r'data-url="(/course/sections/[^"]+)"', card)
    if m:
        c["multiSectionsUrl"] = m.group(1)
    m = re.search(r"<!-- Begin: Location -->(.*?)<!-- End: Location -->", right, re.S)
    loc = text(m.group(1)) if m else ""
    if loc:
        c["location"] = loc
    return c


def parse_links(page):
    """The course page's 'Links' buttons (The Coop, Syllabus, Canvas Site, Q Report, …) → [{label, url}]."""
    links = []
    for href, inner in re.findall(r'<a\s[^>]*href="(https?://[^"]+)"[^>]*class="btn btn-sm btn-light[^"]*"[^>]*>(.*?)</a>', page, re.S) + \
            re.findall(r'<a\s[^>]*class="btn btn-sm btn-light[^"]*"[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        label = text(re.sub(r"<svg.*?</svg>", "", inner, flags=re.S))
        if label and not any(l["url"] == html.unescape(href) for l in links):
            links.append({"label": label, "url": html.unescape(href)})
    return links


def parse_detail(page):
    """Extra fields from a public course detail page."""
    t = page
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>", "", t, flags=re.S)
    plain = text(t)
    d = {}

    def after(label, pattern=r"([^\n]{1,200}?)"):
        m = re.search(re.escape(label) + r"\s*:?\s*" + pattern + r"(?= [A-Z][a-z]+(?: [A-Z/&][a-zA-Z/&]*)*:? |$)", plain)
        return m.group(1).strip() if m else None

    m = re.search(r"Class Number:\s*(\d+)", plain)
    if m:
        d["classNumber"] = m.group(1)
    m = re.search(r"Credits\s+([\d.\-– ]+?)\s", plain)
    if m:
        d["credits"] = m.group(1).strip()
    m = re.search(r"Course Component\s+(.+?)\s+(?:NOTE:|Subject\s)", plain)
    if m:
        d["component"] = m.group(1).strip()
    d["needsSections"] = "requires additional sections" in plain
    m = re.search(r"General Education\s+((?:(?!General Education).)+?)\s+Quantitative Reasoning", plain)
    if m and m.group(1).strip() != "N/A":
        d["genEd"] = m.group(1).strip()
    m = re.search(r"Divisional Distribution\s+(.+?)\s+Course Level", plain)
    if m and m.group(1).strip() != "N/A":
        d["divisional"] = m.group(1).strip()
    m = re.search(r"Description\s+(.+?)\s+(?:Course Notes|Recommended Prep|School)\s", plain)
    if m:
        d["fullDescription"] = m.group(1).strip()
    m = re.search(r"Full Term\s+([A-Z][a-z]+\.? \d{1,2}, \d{4} – [A-Z][a-z]+\.? \d{1,2}, \d{4})", plain)
    if m:
        d["dates"] = m.group(1)
    m = re.search(r"Consent:\s*(.+?)\s+Enrollment:", plain)
    if m:
        d["consent"] = m.group(1)
    m = re.search(r'href="(https?://[^"]*qreports[^"]*|https?://[^"]*q\.fas[^"]*)"', page)
    if m:
        d["qReport"] = html.unescape(m.group(1))
    d["links"] = parse_links(page)
    for l in d["links"]:
        if l["label"] == "Syllabus":
            d["syllabus"] = l["url"]
        elif l["label"] == "Canvas Site":
            d["canvas"] = l["url"]
    return d


# ---------------------------------------------------------------- scraping

def search_page(term, school, page, query=""):
    params = {"q": query, "school": school, "term": term, "sort": "subject_catalog", "page": page}
    url = f"{BASE}/search/?{urllib.parse.urlencode(params)}"
    raw = get(url, accept="application/json")
    return json.loads(raw)


def scrape_search(term, school, delay, workers):
    first = search_page(term, school, 1)
    total = int(first["total_hits"])
    per_page = max(1, first["hits"].count("<!-- Course Card -->"))
    pages = (total + per_page - 1) // per_page
    print(f"{term} / {school}: {total} courses across {pages} pages")

    results = {1: first}

    def fetch(p):
        time.sleep(delay)
        return p, search_page(term, school, p)

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (p, data) in enumerate(ex.map(fetch, range(2, pages + 1)), 2):
            results[p] = data
            if i % 20 == 0 or i == pages:
                print(f"  page {i}/{pages}")

    courses = []
    for p in sorted(results):
        for card in results[p]["hits"].split("<!-- Course Card -->")[1:]:
            c = parse_card(card)
            if c:
                courses.append(c)
    return courses


def parse_class_sections(page):
    """Rows of a course's 'Multiple Sections' panel → [{id, label, component, meetings, notes, url}]."""
    try:
        page = json.loads(page)["html"]
    except Exception:  # noqa: BLE001
        pass
    out = []
    for row in page.split("<!-- Section -->")[1:]:
        link = re.search(r'href="(/course/[^"]+)"[^>]*>\s*(.*?)</a>', row, re.S)
        label = re.sub(r"^Section\s+", "", text(link.group(2))) if link else str(len(out) + 1)
        instr = [text(x) for x in re.findall(r'<span class="link-body">(.*?)</span>', row, re.S)]
        out.append({
            "id": f"cls-{label}",
            "label": label,
            "component": "Class section",
            "meetings": parse_meetings(row),
            **({"notes": instr} if instr else {}),
            **({"url": BASE + html.unescape(link.group(1))} if link else {}),
        })
    return out


def add_class_sections(courses, delay, workers):
    todo = [c for c in courses if c.get("multiSectionsUrl")]
    if not todo:
        return
    print(f"Fetching section lists for {len(todo)} multi-section courses…")

    def fetch(c):
        time.sleep(delay)
        try:
            old = {x["label"]: x for x in c.get("classSections", [])}
            c["classSections"] = parse_class_sections(get(BASE + c["multiSectionsUrl"]))
            for x in c["classSections"]:  # keep links fetched on earlier runs
                if "links" in old.get(x["label"], {}):
                    x["links"] = old[x["label"]]["links"]
        except Exception as e:  # noqa: BLE001
            print(f"  failed {c['code']}: {e}", file=sys.stderr)

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(fetch, todo))


def add_details(courses, delay, workers):
    for c in courses:  # multi-section courses link to their sections' pages instead
        if not c.get("url") and c.get("classSections") and c["classSections"][0].get("url"):
            c["url"] = c["classSections"][0]["url"]
    todo = [c for c in courses if c.get("url") and ("classNumber" not in c or "links" not in c)]
    print(f"Fetching {len(todo)} detail pages…")

    def fetch(c):
        time.sleep(delay)
        try:
            c.update(parse_detail(get(c["url"])))
        except Exception as e:  # noqa: BLE001
            print(f"  failed {c['code']}: {e}", file=sys.stderr)
        return c

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, _ in enumerate(ex.map(fetch, todo), 1):
            if i % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}")

    # each parallel section of a multi-section course has its own Canvas site
    secs = [x for c in courses for x in c.get("classSections", []) if x.get("url") and "links" not in x]
    if secs:
        print(f"Fetching links for {len(secs)} class sections…")

        def fetch_sec(x):
            time.sleep(delay)
            try:
                x["links"] = parse_links(get(x["url"]))
            except Exception as e:  # noqa: BLE001
                print(f"  failed {x['url']}: {e}", file=sys.stderr)

        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(fetch_sec, secs))


def key(c):
    return f"{c['term']}|{c['courseId']}|{c['offerNbr']}|{c.get('session', '')}"


def load_existing():
    path = os.path.join(DATA_DIR, "courses.json")
    if os.path.exists(path):
        with open(path) as f:
            return {key(c): c for c in json.load(f)}
    return {}


def save(all_courses):
    os.makedirs(DATA_DIR, exist_ok=True)
    lst = sorted(all_courses.values(), key=lambda c: (c["term"], c["subject"], c["catalog"]))
    with open(os.path.join(DATA_DIR, "courses.json"), "w") as f:
        json.dump(lst, f, ensure_ascii=False, separators=(",", ":"))
    terms = sorted({c["term"] for c in lst})
    with open(os.path.join(DATA_DIR, "index.json"), "w") as f:
        json.dump({"terms": terms, "updated": time.strftime("%Y-%m-%d %H:%M"), "count": len(lst)}, f)
    print(f"Saved {len(lst)} courses → data/courses.json")


def main():
    sys.stdout.reconfigure(line_buffering=True)  # show progress live even when output goes to a file
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--term", default="2027 Spring", help='e.g. "2027 Spring", "2026 Fall", or "All"')
    ap.add_argument("--school", default="FAS", help="FAS, HKS, HLS, GSD, … or All")
    ap.add_argument("--details", action="store_true", help="also fetch each course page (class number, credits, gen ed, needs-sections flag)")
    ap.add_argument("--delay", type=float, default=0.25, help="seconds between requests per worker")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    existing = load_existing()
    courses = scrape_search(args.term, args.school, args.delay, args.workers)
    # keep previously fetched details/sections
    for c in courses:
        old = existing.get(key(c))
        if old:
            for k, v in old.items():
                c.setdefault(k, v)
    add_class_sections(courses, args.delay, args.workers)
    if args.details:
        add_details(courses, args.delay, args.workers)
    for c in courses:
        existing[key(c)] = c
    save(existing)


if __name__ == "__main__":
    main()
