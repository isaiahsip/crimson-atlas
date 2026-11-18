# Crimson Atlas

I did not write a single line of this code, it was all Claude.

An Atlas-style course planner for Harvard. Search courses, see their time blocks pop up on a weekly calendar as you type, and build a schedule with lectures, discussion sections, and labs.

Course data comes from my.harvard's course search and is stored as static JSON in `data/`, so the site is plain HTML/JS with no backend or build step.

Inspired by [Atlas](https://atlas.ai.umich.edu), which is copyrighted and the property of the University of Michigan. This project is not affiliated with or endorsed by the University of Michigan or Harvard.

## Features

- Live search: course codes (`cs 50`, `ec10a`), titles, instructors, descriptions
- Sort by start/end time; filter by days, "starts after" / "ends by", department, Gen Ed
- Matching courses preview on the calendar as you type; hover a result to highlight it
- Schedule saved in your browser, with conflicts outlined in red and a "Fits my schedule" filter
- Discussion, lab, and parallel class sections shown dashed on the calendar until you pick one (one pick per type)
- Hand-entered section options for sections my.harvard hasn't posted yet
- Course links like on my.harvard: Syllabus, Canvas Site, Q Report, The Coop
- `.ics` export for Google Calendar / Apple Calendar
- Multiple draft schedules (new, duplicate, rename, delete, switch)
- Export a draft to a `.json` file or copy a share link; importing asks whether to add a new draft or replace the current one

## Run locally

```sh
python3 -m http.server 8000
# open http://localhost:8000
```

(The page loads `data/courses.json` with `fetch`, so opening `index.html` directly from disk won't work. Use a local server.)

## Publish on GitHub Pages

1. Create an empty repository on GitHub.
2. Push this folder:
   ```sh
   git add -A
   git commit -m "Crimson Atlas"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
3. On GitHub, go to **Settings → Pages**, set **Source: Deploy from a branch**, and pick **main / (root)**.
4. The site appears at `https://<you>.github.io/<repo>/` within a minute or two.

## Refreshing the course data

All scripts use only the Python standard library.

```sh
# Public data: courses, meeting times, parallel sections, course links (~10 min with --details)
python3 scraper/scrape.py --term "2027 Spring" --school FAS --details
python3 scraper/scrape.py --term "2026 Fall"   --school FAS --details   # more terms merge in

# Discussion/lab section times (needs a signed-in my.harvard session, see below)
python3 scraper/sections.py            # courses flagged as needing a section
python3 scraper/sections.py --refresh  # re-check later; departments post times over time
```

Then commit the updated `data/` and push. Pages redeploys automatically.

### Section times and your cookie

my.harvard only shows discussion/lab times to signed-in students. `sections.py` reads them with your own session:

1. Sign in at https://my.harvard.edu. Open DevTools → Network, reload, click the `my.harvard.edu` request, and copy the **Cookie** request header value.
2. `pbpaste > .harvard-cookie`
3. `python3 scraper/sections.py`

It only makes read-only requests (the same section list the Add to Cart popup loads), so nothing is added to your cart. If your session expires mid-run, refresh the cookie and rerun; finished courses are kept.

**Privacy:** `.harvard-cookie` works like your login. It and `debug/` (raw signed-in pages from `probe_auth.py`) are in `.gitignore`, so they never reach GitHub. The published `data/courses.json` contains only course information: titles, times, instructors, section times, and links. Nothing about your account goes in it.

## Tests

Browser smoke tests use Playwright (`pip install playwright && playwright install chromium`):

```sh
python3 -m http.server 8765 &
for t in tests/ui_test*.py; do python3 "$t" out.png; done
```

## Layout

```
index.html, app.js, styles.css   the site
data/courses.json, index.json    scraped course data (committed)
scraper/scrape.py                public course search + course pages
scraper/sections.py              section times (signed-in)
scraper/probe_auth.py            debugging helper for the signed-in pages
tests/                           Playwright smoke tests
```

Thanks to Amy for the idea ♥
