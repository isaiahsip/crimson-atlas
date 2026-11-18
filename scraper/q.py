#!/usr/bin/env python3
"""
Fetch Q Report (course evaluation) summaries: average workload and recommendation score.

    python3 scraper/q.py                # 3 most recent reports per course
    python3 scraper/q.py --terms 5      # use more past offerings
    python3 scraper/q.py --limit 20     # quick trial run

Needs your signed-in Q Reports session:
    copy the Cookie header from a request to qreports.fas.harvard.edu into .harvard-q-cookie

Writes data/q.json, which is gitignored: Q results are restricted to the Harvard
community, so they stay on your machine and are not published with the site.
Read-only GET requests. Finished reports are cached, so reruns only fetch what's new.
"""
import argparse
import concurrent.futures as cf
import html
import http.cookiejar
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import DATA_DIR, ROOT, SSL_CTX  # noqa: E402
from probe_q import cookie_for, fetch as q_fetch  # noqa: E402

QBASE = "https://qreports.fas.harvard.edu"
OUT = os.path.join(DATA_DIR, "q.json")
INDEX_CACHE = os.path.join(ROOT, "debug", "q-index.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"


# ---------------------------------------------------------------- report index (qreports, needs cookie)

def index_page(start, length=100):
    p = [("search", ""), ("school", "FAS"), ("term", ""), ("department", ""), ("subject", ""), ("instructor", ""), ("draw", "1")]
    for i, c in enumerate(["title", "instructor", "department", "term"]):
        p += [(f"columns[{i}][data]", c), (f"columns[{i}][name]", ""), (f"columns[{i}][searchable]", "true"),
              (f"columns[{i}][orderable]", "true"), (f"columns[{i}][search][value]", ""), (f"columns[{i}][search][regex]", "false")]
    p += [("order[0][column]", "0"), ("order[0][dir]", "asc"), ("start", str(start)), ("length", str(length)),
          ("search[value]", ""), ("search[regex]", "false")]
    status, body, _ = q_fetch(f"{QBASE}/search/api?{urllib.parse.urlencode(p)}")
    if status != 200:
        sys.exit("Q Reports session expired (or cookie missing). Copy a fresh cookie into .harvard-q-cookie and rerun.")
    return json.loads(body)


def load_index(refresh):
    if not refresh and os.path.exists(INDEX_CACHE) and time.time() - os.path.getmtime(INDEX_CACHE) < 7 * 86400:
        return json.load(open(INDEX_CACHE))
    first = index_page(0)
    total = first["recordsFiltered"]
    rows = first["data"]
    print(f"Downloading report index: {total} reports…")
    for start in range(100, total, 100):
        time.sleep(0.3)
        rows += index_page(start)["data"]
        if start % 1000 == 0:
            print(f"  {start}/{total}")
    os.makedirs(os.path.dirname(INDEX_CACHE), exist_ok=True)
    json.dump(rows, open(INDEX_CACHE, "w"))
    return rows


# ---------------------------------------------------------------- report pages (bluera, opened from their links)

class BlueOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not urllib.parse.urlparse(newurl).hostname.endswith("bluera.com"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


BLUE = urllib.request.build_opener(BlueOnly, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                   urllib.request.HTTPSHandler(context=SSL_CTX))


def get_report(url, retries=3):
    for attempt in range(retries):
        try:
            with BLUE.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def to_text(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    t = re.sub(r"</(tr|div|p|h\d|table|li)>", "\n", t)
    t = re.sub(r"</t[dh]>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


def parse_report(page):
    """→ {hours, hoursN, recommend, recommendN, overall, overallN, responded, invited} (missing keys if not in report)."""
    t = to_text(page)
    out = {}
    num = r"([\d.]+)"
    m = re.search(r"how many hours per week[^|]{0,200}-Statistics\.\s*Statistics \| Value \|\s*Response Count \| (\d+) \|.{0,60}?Mean \| " + num, t)
    if m:
        out["hoursN"], out["hours"] = int(m.group(1)), float(m.group(2))
    m = re.search(r"How strongly would you recommend this course to your peers\?\s*\.\s*Options \| Score \| Count \| Percentage \|((?:[^|]+\| \d \| \d+ \| \d+% \|\s*){1,5})", t)
    if m:
        out["recommendN"] = sum(int(x) for x in re.findall(r"\| \d \| (\d+) \| \d+% \|", m.group(1)))
    m = re.search(r"recommend this course to your peers\?\s*-Statistics\.\s*Statistics \| Value \|.{0,80}?Mean \| " + num, t)
    if m:
        out["recommend"] = float(m.group(1))
    m = re.search(r"Evaluate the course overall\.\s*\|\s*(\d+)\s*\|(?:\s*\d+%\s*\|){5}\s*" + num, t)
    if m:
        out["overallN"], out["overall"] = int(m.group(1)), float(m.group(2))
    m = re.search(r"Responded \| (\d+) \|\s*Invited \| (\d+)", t)
    if m:
        out["responded"], out["invited"] = int(m.group(1)), int(m.group(2))
    return out


def wavg(items, key, wkey):
    pairs = [(x[key], x.get(wkey) or x.get("responded") or 1) for x in items if key in x]
    tot = sum(w for _, w in pairs)
    return round(sum(v * w for v, w in pairs) / tot, 2) if tot else None


# ---------------------------------------------------------------- main

def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terms", type=int, default=3, help="most recent offerings to average per course")
    ap.add_argument("--limit", type=int, help="only the first N courses (trial run)")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    if not cookie_for(QBASE + "/"):
        sys.exit("Missing .harvard-q-cookie. See README → Q Reports.")
    courses = json.load(open(os.path.join(DATA_DIR, "courses.json")))
    wanted = sorted({c["courseId"] for c in courses})
    if args.limit:
        wanted = wanted[:args.limit]

    # index → courseId → strm → report (one per offering; instructor rows of the same offering share course stats)
    by_course = {}
    for r in load_index(args.refresh_index):
        parts = (r.get("blueCourseId") or "").split("-")
        if len(parts) < 3 or not r.get("url"):
            continue
        offering = by_course.setdefault(parts[1], {}).setdefault(parts[2], {"term": r["term"], "url": r["url"], "blueId": r["blueCourseId"], "instructors": []})
        if r.get("instructor") and r["instructor"] not in offering["instructors"]:
            offering["instructors"].append(r["instructor"])

    cache = {}
    if os.path.exists(OUT):
        for cid, v in json.load(open(OUT)).items():
            for t in v.get("terms", []):
                cache[t["blueId"]] = t

    jobs = []
    for cid in wanted:
        for strm in sorted(by_course.get(cid, {}), reverse=True)[:args.terms]:
            o = by_course[cid][strm]
            if o["blueId"] not in cache:
                jobs.append(o)
    have = sum(1 for cid in wanted if cid in by_course)
    print(f"{have} of {len(wanted)} courses have Q reports. Fetching {len(jobs)} reports ({len(cache)} cached)…")

    lock = threading.Lock()
    done = [0]
    fails = [0]

    def build():
        out = {}
        for cid in wanted:
            terms = [cache[by_course[cid][s]["blueId"]] for s in sorted(by_course.get(cid, {}), reverse=True)[:args.terms]
                     if by_course[cid][s]["blueId"] in cache]
            terms = [t for t in terms if "hours" in t or "recommend" in t or "overall" in t]
            if terms:
                out[cid] = {"hours": wavg(terms, "hours", "hoursN"), "recommend": wavg(terms, "recommend", "recommendN"),
                            "overall": wavg(terms, "overall", "overallN"), "terms": terms}
        return out

    def save():
        tmp = OUT + ".tmp"
        json.dump(build(), open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, OUT)

    def work(o):
        time.sleep(args.delay)
        try:
            stats = parse_report(get_report(o["url"]))
        except Exception as e:  # noqa: BLE001
            with lock:
                fails[0] += 1
            print(f"  failed {o['blueId']}: {e}", file=sys.stderr)
            return
        with lock:
            cache[o["blueId"]] = {"term": o["term"], "blueId": o["blueId"], "instructors": o["instructors"], "url": o["url"], **stats}
            done[0] += 1
            if done[0] % 100 == 0:
                print(f"  {done[0]}/{len(jobs)}")
                save()

    if jobs:
        work(jobs[0])  # first request alone: sets up the report viewer session
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(work, jobs[1:]))
    save()
    out = build()
    print(f"Done: {done[0]} fetched, {fails[0]} failed. {len(out)} courses have Q data → data/q.json (local only, gitignored)")


if __name__ == "__main__":
    main()
