/* Crimson Atlas — course search + weekly calendar for my.harvard data.
 * Data: data/courses.json (from scraper/scrape.py). State persists in localStorage.
 */
(() => {
  "use strict";

  // ------------------------------------------------------------ constants
  const DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
  const DAY_NAMES = { Mo: "Mon", Tu: "Tue", We: "Wed", Th: "Thu", Fr: "Fri", Sa: "Sat", Su: "Sun" };
  const PALETTE = ["#a51c30", "#2563eb", "#0f8a5f", "#c2410c", "#7c3aed", "#0e7490", "#b45309", "#be185d", "#4d7c0f", "#475569"];
  const PAGE = 80;          // results rendered per "page"
  const PREVIEW_N = 12;     // ghost-preview this many top results
  const PX_PER_MIN = 0.9;   // calendar vertical scale
  const STORE = "crimson-atlas-v1";

  // Common short names → my.harvard subject codes
  const ALIASES = {
    cs: "compsci", ec: "econ", ecs: "econ", math: "math", stat: "stat", stats: "stat", am: "applmath",
    "applied math": "applmath", es: "engsci", ls: "lifesci", gov: "gov", hist: "hist", phil: "phil",
    psy: "psy", psych: "psy", soc: "sociol", ec10: "econ 10", physci: "physci", phys: "physics",
    chem: "chem", mcb: "mcb", oeb: "oeb", sls: "sls", hum: "hum", gened: "gened", ge: "gened",
    eng: "english", engl: "english", lit: "complit", hds: "hist-lit", vs: "afvs", afvs: "afvs",
  };

  // ------------------------------------------------------------ state
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  let ALL = [];          // all courses
  let BY_KEY = new Map();
  let results = [];
  let shown = PAGE;
  let hoverKey = null;

  const saved = load();
  const state = {
    term: saved.term || "",
    sort: saved.sort || "relevance",
    days: new Set(saved.days || []),
    after: saved.after || "",
    before: saved.before || "",
    hideTba: saved.hideTba ?? true,
    fits: saved.fits ?? false,
    previewAll: saved.previewAll ?? true,
    dept: "",
    gened: "",
    // drafts: [{ id, name, schedule }], where schedule is key -> { color, picks: {component: optionId}, options: [...] }
    // (schedules saved before drafts existed become "Schedule 1")
    drafts: saved.drafts?.length ? saved.drafts : [{ id: "d-" + Math.random().toString(36).slice(2, 9), name: "Schedule 1", schedule: saved.schedule || {} }],
    activeDraft: saved.activeDraft,
    schedule: null, // always the active draft's schedule object
    theme: saved.theme || "",
  };
  if (!state.drafts.some((d) => d.id === state.activeDraft)) state.activeDraft = state.drafts[0].id;
  state.schedule = state.drafts.find((d) => d.id === state.activeDraft).schedule;

  function load() {
    try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; }
  }
  function persist() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ ...state, days: [...state.days], dept: undefined, gened: undefined, schedule: undefined }));
    } catch { /* storage unavailable */ }
  }

  // ------------------------------------------------------------ helpers
  const keyOf = (c) => `${c.term}|${c.courseId}|${c.offerNbr}|${c.session || ""}`;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const toMin = (hhmm) => { if (!hhmm) return null; const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
  const toHHMM = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
  function fmt(min) {
    let h = Math.floor(min / 60), m = min % 60;
    const ap = h >= 12 ? "pm" : "am";
    h = h % 12 || 12;
    return m ? `${h}:${String(m).padStart(2, "0")}${ap}` : `${h}${ap}`;
  }
  const timed = (m) => m && m.start != null && m.end != null && m.days && m.days.length;
  const meetingStr = (m) => timed(m) ? `${m.days.join(" ")} ${fmt(m.start)}–${fmt(m.end)}` : (m.days?.length ? `${m.days.join(" ")} TBA` : "TBA");
  const firstStart = (c) => { const ts = (c.meetings || []).filter(timed).map((m) => m.start); return ts.length ? Math.min(...ts) : null; };
  const lastEnd = (c) => { const ts = (c.meetings || []).filter(timed).map((m) => m.end); return ts.length ? Math.max(...ts) : null; };
  const uid = () => Math.random().toString(36).slice(2, 9);
  /** Readable text color (dark or white) on top of a course color, so light custom colors stay legible. */
  function textOn(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return "#fff";
    const n = parseInt(m[1], 16);
    const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const L = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
    return L > 0.4 ? "#1c1b1a" : "#fff";
  }

  /** Every section option for a course: scraped + manually entered, each tagged with a component. */
  function sectionOptions(c, entry) {
    // "Multiple Sections" courses: each parallel class section is an option, listed first
    const scraped = [...(c.classSections || []), ...(c.sections || [])].map((x) => ({ ...x, label: x.label || x.id, component: x.component || "Section", source: "scraped", meetings: x.meetings || [] }));
    // manual options join the course's (first) real section type, e.g. "Discussion"
    // manual options carry their own type; older ones (saved without one) join the first real type
    const fallback = c.sections?.[0]?.component || "Section";
    const manual = (entry?.options || []).map((o) => ({ ...o, component: o.component || fallback, source: "manual", meetings: [{ days: o.days, start: o.start, end: o.end }] }));
    return [...scraped, ...manual];
  }
  /** Options grouped by component (Discussion, Laboratory, …): Map<component, option[]> */
  function sectionGroups(c, entry) {
    const g = new Map();
    for (const o of sectionOptions(c, entry)) {
      if (!g.has(o.component)) g.set(o.component, []);
      g.get(o.component).push(o);
    }
    return g;
  }
  const pickedSections = (c, entry) => sectionOptions(c, entry).filter((o) => (entry?.picks || {})[o.component] === o.id);
  const timedSections = (c) => (c.sections || []).filter((x) => (x.meetings || []).some(timed));
  const timedClassSections = (c) => (c.classSections || []).filter((x) => (x.meetings || []).some(timed));

  /** The course's my.harvard "Links" (The Coop, Syllabus, Canvas Site, Q Report). A picked parallel section's own Canvas site wins. */
  function courseLinks(c, entry) {
    let links = (c.links || []).slice();
    if (!links.length) {
      if (c.syllabus) links.push({ label: "Syllabus", url: c.syllabus });
      if (c.qReport) links.push({ label: "Q Report", url: c.qReport });
    }
    const picked = entry ? pickedSections(c, entry).find((o) => o.component === "Class section") : null;
    const secCanvas = picked?.links?.find((l) => l.label === "Canvas Site");
    if (secCanvas) {
      links = links.filter((l) => l.label !== "Canvas Site");
      links.splice(Math.min(2, links.length), 0, { label: `Canvas Site (${picked.label})`, url: secCanvas.url });
    }
    return links;
  }
  const linkA = (l, text = l.label) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(text)} ↗</a>`;

  // ------------------------------------------------------------ search
  function normalizeQuery(q) {
    q = q.toLowerCase().trim();
    // "cs50" → "cs 50"
    q = q.replace(/\b([a-z]{2,})(\d+[a-z]*)\b/g, "$1 $2");
    return q;
  }

  function buildIndex(c) {
    c._code = c.code.toLowerCase();
    c._subj = (c.subject || "").toLowerCase();
    c._cat = (c.catalog || "").toLowerCase();
    c._title = (c.title || "").toLowerCase();
    c._instr = (c.instructors || []).join(" ").toLowerCase();
    c._dept = (c.department || "").toLowerCase();
    c._desc = ((c.fullDescription || c.description || "") + " " + (c.genEd || "")).toLowerCase();
    const lec = (c.meetings || []).filter(timed);
    c._alts = lec.length ? [lec] : timedClassSections(c).map((x) => x.meetings.filter(timed));
    const starts = c._alts.flat().map((m) => m.start), ends = c._alts.flat().map((m) => m.end);
    c._start = starts.length ? Math.min(...starts) : null;
    c._end = ends.length ? Math.max(...ends) : null;
  }

  function score(c, q, tokens) {
    if (!q) return 1;
    let s = 0;
    // subject + catalog style query ("compsci 50", "cs 50", "econ 10a")
    const m = q.match(/^([a-z&-]+)\s+(\d+[a-z]*)$/);
    if (m) {
      const subj = ALIASES[m[1]] || m[1];
      if (c._subj === subj || c._subj.startsWith(subj)) {
        if (c._cat === m[2]) s += 1000;
        else if (c._cat.startsWith(m[2])) s += 500 - c._cat.length;
      }
    }
    if (c._code === q) s += 1000;
    if (c._title === q) s += 400;
    if (c._title.includes(q)) s += 150;
    for (const raw of tokens) {
      const alts = [raw, ALIASES[raw]].filter(Boolean);
      let hit = 0;
      for (const t of alts) {
        if (c._subj === t) hit = Math.max(hit, 60);
        else if (c._cat === t) hit = Math.max(hit, 50);
        else if (c._code.includes(t)) hit = Math.max(hit, 35);
        if (new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(c._title)) hit = Math.max(hit, 30);
        else if (c._title.includes(t)) hit = Math.max(hit, 18);
        if (c._instr.includes(t)) hit = Math.max(hit, 25);
        if (c._dept.includes(t)) hit = Math.max(hit, 12);
        if (c._desc.includes(t)) hit = Math.max(hit, 4);
      }
      if (!hit) return 0; // every token must match somewhere
      s += hit;
    }
    return s;
  }

  function scheduledBlocks(excludeKey) {
    const blocks = [];
    for (const [k, entry] of Object.entries(state.schedule)) {
      if (k === excludeKey) continue;
      const c = BY_KEY.get(k);
      if (!c) continue;
      for (const m of (c.meetings || []).filter(timed)) blocks.push(m);
      for (const sec of pickedSections(c, entry)) for (const m of sec.meetings.filter(timed)) blocks.push(m);
    }
    return blocks;
  }
  const overlaps = (a, b) => a.days.some((d) => b.days.includes(d)) && a.start < b.end && b.start < a.end;
  function conflictsWithSchedule(c, blocks) {
    return (c.meetings || []).filter(timed).some((m) => blocks.some((b) => overlaps(m, b)));
  }
  function fitsSchedule(c, blocks) {
    if (conflictsWithSchedule(c, blocks)) return false;
    for (const opts of sectionGroups(c).values()) {
      const ok = opts.some((o) => o.meetings.filter(timed).every((m) => !blocks.some((b) => overlaps(m, b))));
      if (!ok) return false;
    }
    return true;
  }

  function runSearch() {
    const q = normalizeQuery($("#q").value);
    const tokens = q.split(/\s+/).filter(Boolean);
    const after = toMin(state.after), before = toMin(state.before);
    const blocks = state.fits ? scheduledBlocks() : null;

    const out = [];
    for (const c of ALL) {
      if (state.term && c.term !== state.term) continue;
      if (state.dept && c.department !== state.dept) continue;
      if (state.gened && c.genEd !== state.gened && c.divisional !== state.gened) continue;
      if (state.hideTba && !c._alts.length) continue;
      // a multi-section course passes if any one of its sections passes
      const passes = (tm) =>
        !(state.days.size && tm.some((m) => m.days.some((d) => !state.days.has(d)))) &&
        !(after != null && tm.some((m) => m.start < after)) &&
        !(before != null && tm.some((m) => m.end > before));
      if (c._alts.length ? !c._alts.some(passes) : (state.days.size || after != null || before != null)) continue;
      if (blocks && !state.schedule[keyOf(c)] && !fitsSchedule(c, blocks)) continue;
      const s = score(c, q, tokens);
      if (!s) continue;
      c._score = s;
      out.push(c);
    }

    const byCode = (a, b) => a.subject.localeCompare(b.subject) || a.catalog.localeCompare(b.catalog, undefined, { numeric: true });
    const nullLast = (v, desc) => (v == null ? (desc ? -Infinity : Infinity) : v);
    const sorters = {
      relevance: (a, b) => b._score - a._score || byCode(a, b),
      start: (a, b) => nullLast(a._start) - nullLast(b._start) || byCode(a, b),
      "start-desc": (a, b) => nullLast(b._start, true) - nullLast(a._start, true) || byCode(a, b),
      end: (a, b) => nullLast(a._end) - nullLast(b._end) || byCode(a, b),
      code: byCode,
      title: (a, b) => a.title.localeCompare(b.title),
    };
    const sortKey = !q && state.sort === "relevance" ? "code" : state.sort;
    out.sort(sorters[sortKey]);
    results = out;
    shown = PAGE;
    renderResults();
    renderCalendar();
  }

  // ------------------------------------------------------------ results list
  function secTag(c) {
    const ts = timedSections(c);
    if (ts.length) {
      const kinds = [...new Set(ts.map((x) => x.component.toLowerCase()))].join(" + ");
      return `<span class="tag sec" title="${esc(kinds)}">${ts.length} ${ts.length === 1 ? "section" : "sections"}</span>`;
    }
    return c.needsSections || c.sections?.length ? '<span class="tag sec" title="Requires a section; times not posted yet">section TBA</span>' : "";
  }
  function renderResults() {
    const list = $("#results");
    const blocks = scheduledBlocks();
    $("#resultMeta").textContent = `${results.length.toLocaleString()} course${results.length === 1 ? "" : "s"}`;
    const html = results.slice(0, shown).map((c) => {
      const k = keyOf(c);
      const entry = state.schedule[k];
      const added = !!entry;
      const conflict = !added && !fitsSchedule(c, blocks);
      const cs = c.classSections || [];
      const when = (c.meetings || []).filter((m) => m.days?.length || timed(m)).map(meetingStr).join(" · ")
        || (cs.length ? `${cs.length} sections: ${cs.slice(0, 3).map((x) => x.meetings.map(meetingStr).join(", ") || "TBA").join(" | ")}${cs.length > 3 ? " | …" : ""}` : "TBA");
      return `<li class="result${added ? " added" : ""}" data-k="${esc(k)}" tabindex="0">
        ${added ? `<span class="swatch" style="background:${entry.color}"></span>` : ""}
        <div class="code">${esc(c.code)} ${secTag(c)} ${conflict ? '<span class="tag warn">conflict</span>' : ""}</div>
        <div class="title">${esc(c.title)}</div>
        <div class="meta"><span class="when">${esc(when)}</span>${c.instructors?.length ? `<span>${esc(c.instructors.join(", "))}</span>` : ""}${c.genEd ? `<span>${esc(c.genEd)}</span>` : ""}</div>
        <button class="add" title="${added ? "Remove from" : "Add to"} schedule" aria-label="${added ? "Remove" : "Add"} ${esc(c.code)}">${added ? "✓" : "+"}</button>
      </li>`;
    }).join("");
    list.innerHTML = html + (results.length > shown ? `<li><button class="ghost-btn more">Show more (${(results.length - shown).toLocaleString()} left)</button></li>` : "");
    if (!results.length) list.innerHTML = `<li class="empty" style="padding:14px">No courses match. Try loosening the time or day filters.</li>`;
  }

  // ------------------------------------------------------------ calendar
  function collectEvents() {
    const events = [];
    const solid = [];
    for (const [k, entry] of Object.entries(state.schedule)) {
      const c = BY_KEY.get(k);
      if (!c || (state.term && c.term !== state.term)) continue;
      for (const m of (c.meetings || []).filter(timed)) {
        const e = { k, c, m, kind: "lecture", color: entry.color, label: c.code, sub: c.component || "Lecture" };
        events.push(e); solid.push(e);
      }
      const picks = entry.picks || {};
      for (const [comp, opts] of sectionGroups(c, entry)) {
        const chosen = opts.find((o) => o.id === picks[comp]);
        if (chosen) {
          for (const m of chosen.meetings.filter(timed)) {
            const e = { k, c, m, kind: "section", color: entry.color, label: c.code, sub: `${comp} ${chosen.label}`, optId: chosen.id };
            events.push(e); solid.push(e);
          }
        } else {
          for (const o of opts) for (const m of o.meetings.filter(timed)) {
            events.push({ k, c, m, kind: "option", color: entry.color, label: c.code, sub: `${comp} ${o.label} · click to pick`, optId: o.id });
          }
        }
      }
    }
    // conflicts among solid blocks
    for (let i = 0; i < solid.length; i++) for (let j = i + 1; j < solid.length; j++) {
      if (solid[i].k !== solid[j].k || solid[i].kind !== solid[j].kind) {
        if (overlaps(solid[i].m, solid[j].m)) solid[i].conflict = solid[j].conflict = true;
      }
    }
    // previews
    if (state.previewAll && $("#q").value.trim()) {
      for (const c of results.slice(0, PREVIEW_N)) {
        const k = keyOf(c);
        if (state.schedule[k] || k === hoverKey) continue;
        for (const m of c._alts.flat()) events.push({ k, c, m, kind: "ghost", color: "#8a8580", label: c.code, sub: "" });
      }
    }
    if (hoverKey && !state.schedule[hoverKey]) {
      const c = BY_KEY.get(hoverKey);
      if (c) {
        for (const m of (c.meetings || []).filter(timed)) events.push({ k: hoverKey, c, m, kind: "preview", color: "#1c1b1a", label: c.code, sub: `${fmt(m.start)}–${fmt(m.end)}` });
        for (const o of [...timedClassSections(c), ...timedSections(c)]) for (const m of o.meetings.filter(timed)) {
          events.push({ k: hoverKey, c, m, kind: "preview-sec", color: "#1c1b1a", label: c.code, sub: `${o.component} ${o.label}` });
        }
      }
    }
    return events;
  }

  function renderCalendar({ skipSchedule = false } = {}) {
    const events = collectEvents();
    const usedDays = new Set(["Mo", "Tu", "We", "Th", "Fr"]);
    let lo = 9 * 60, hi = 18 * 60;
    for (const e of events) {
      e.m.days.forEach((d) => usedDays.add(d));
      lo = Math.min(lo, Math.floor(e.m.start / 60) * 60);
      hi = Math.max(hi, Math.ceil(e.m.end / 60) * 60);
    }
    const days = DAYS.filter((d) => usedDays.has(d));
    const height = (hi - lo) * PX_PER_MIN;
    const cal = $("#calendar");
    cal.style.setProperty("--ndays", days.length);

    let h = `<div class="cal-head"></div>` + days.map((d) => `<div class="cal-head">${DAY_NAMES[d]}</div>`).join("");
    h += `<div class="cal-times" style="height:${height}px">`;
    for (let t = lo; t <= hi; t += 60) h += `<div style="top:${(t - lo) * PX_PER_MIN}px">${t < hi ? fmt(t) : ""}</div>`;
    h += `</div>`;

    for (const d of days) {
      h += `<div class="cal-col" data-day="${d}" style="height:${height}px">`;
      for (let t = lo; t < hi; t += 30) h += `<div class="cal-line${t % 60 ? " half" : ""}" style="top:${(t - lo) * PX_PER_MIN}px"></div>`;
      const dayEvents = events.filter((e) => e.m.days.includes(d)).sort((a, b) => a.m.start - b.m.start || b.m.end - a.m.end);
      layoutLanes(dayEvents);
      for (const e of dayEvents) {
        const top = (e.m.start - lo) * PX_PER_MIN, ht = Math.max(16, (e.m.end - e.m.start) * PX_PER_MIN - 2);
        const w = 100 / e.lanes, left = e.lane * w;
        const cls = ["ev", e.kind, e.conflict ? "conflict" : ""].join(" ");
        const style = `top:${top}px;height:${ht}px;left:calc(${left}% + 2px);width:calc(${w}% - 4px);--c:${e.color};--on:${textOn(e.color)};background:${e.color}`;
        h += `<div class="${cls}" style="${style}" data-k="${esc(e.k)}" ${e.optId ? `data-opt="${esc(e.optId)}"` : ""} title="${esc(`${e.label} — ${e.c.title}\n${e.sub ? e.sub + " · " : ""}${fmt(e.m.start)}–${fmt(e.m.end)}${e.conflict ? "\n⚠ conflict" : ""}`)}">
          <b>${esc(e.label)}</b>${ht > 28 ? `<span>${esc(e.sub)}</span>` : ""}${ht > 44 ? `<span>${fmt(e.m.start)}–${fmt(e.m.end)}</span>` : ""}
        </div>`;
      }
      h += `</div>`;
    }
    cal.innerHTML = h;
    if (!skipSchedule) renderSchedule();
  }

  /** Assign side-by-side lanes to overlapping events within a day. */
  function layoutLanes(evts) {
    let cluster = [], clusterEnd = -1;
    const flush = () => {
      const lanes = [];
      for (const e of cluster) {
        let i = lanes.findIndex((end) => end <= e.m.start);
        if (i < 0) { i = lanes.length; lanes.push(0); }
        lanes[i] = e.m.end; e.lane = i;
      }
      cluster.forEach((e) => (e.lanes = lanes.length));
      cluster = [];
    };
    for (const e of evts) {
      if (e.m.start >= clusterEnd && cluster.length) flush();
      cluster.push(e);
      clusterEnd = Math.max(clusterEnd, e.m.end);
    }
    if (cluster.length) flush();
  }

  // ------------------------------------------------------------ schedule panel
  function renderSchedule() {
    renderDrafts();
    const list = $("#schedList");
    const entries = Object.entries(state.schedule).map(([k, e]) => [k, e, BY_KEY.get(k)]).filter(([, , c]) => c && (!state.term || c.term === state.term));
    let credits = 0, mins = 0;
    for (const [, e, c] of entries) {
      credits += parseFloat(c.credits) || 0;
      for (const m of (c.meetings || []).filter(timed)) mins += (m.end - m.start) * m.days.length;
      for (const sec of pickedSections(c, e)) for (const m of sec.meetings.filter(timed)) mins += (m.end - m.start) * m.days.length;
    }
    $("#schedSummary").textContent = entries.length
      ? `${entries.length} course${entries.length > 1 ? "s" : ""}${credits ? ` · ${credits} credits` : ""} · ${(mins / 60).toFixed(1)} hrs/week in class`
      : "";
    if (!entries.length) {
      list.innerHTML = `<li class="empty">Search on the left and click <b>+</b> to add courses. Hover a result to preview it on the calendar.</li>`;
      return;
    }
    list.innerHTML = entries.map(([k, e, c]) => {
      const picks = e.picks || {};
      const groups = [...sectionGroups(c, e)];
      const optBtn = (o) => {
        const on = picks[o.component] === o.id;
        const tip = [on ? "Unpick" : "Pick this section", ...(o.notes || [])].join(" · ");
        return `<span style="display:inline-flex;align-items:center">
          <button class="${on ? "on" : ""}" data-pick="${esc(o.id)}" title="${esc(tip)}">${esc(o.label)} · ${esc(o.meetings.map(meetingStr).join(", ") || "TBA")}</button>
          ${o.source === "manual" ? `<button class="x-btn" data-delopt="${esc(o.id)}" title="Delete this option" aria-label="Delete option">✕</button>` : ""}
        </span>`;
      };
      const groupHtml = groups.map(([comp, opts]) => {
        const chosen = opts.find((o) => o.id === picks[comp]);
        const timedOpts = opts.filter((o) => o.meetings.some(timed));
        const status = chosen
          ? `<b style="color:var(--text)">${esc(chosen.label)} · ${esc(chosen.meetings.map(meetingStr).join(", ") || "TBA")}</b>`
          : timedOpts.length
            ? `<i>${timedOpts.length} option${timedOpts.length > 1 ? "s" : ""} dashed on the calendar. Click one to pick it.</i>`
            : "<i>times not posted yet. Add the options yourself with + Add section option.</i>";
        const shownOpts = opts.filter((o) => o.meetings.some(timed) || o.source === "manual" || o.id === picks[comp]);
        return `<div class="line">${esc(comp)}: ${status}</div>${shownOpts.length ? `<div class="section-picker">${shownOpts.map(optBtn).join("")}</div>` : ""}`;
      }).join("");
      return `<li class="sched-item" data-k="${esc(k)}" style="--c:${e.color};--on:${textOn(e.color)}">
        <div class="top"><b>${esc(c.code)}</b><span>${esc(c.title)}</span><span class="spacer"></span>
          <button class="link-btn" data-addopt>${openFormKey === k ? "Done adding" : "+ Add section option"}</button>
          <button class="link-btn" data-info>Details</button>
          <button class="x-btn" data-remove title="Remove course" aria-label="Remove ${esc(c.code)}">✕</button></div>
        <div class="lines">
          ${c.classSections?.length && !(c.meetings || []).some(timed) ? "" : `<div class="line">${esc(c.component || "Lecture")}: ${esc((c.meetings || []).map(meetingStr).join(" · ") || "TBA")}</div>`}
          ${groupHtml || (c.needsSections ? '<div class="line"><i>Requires a section. Add the options with + Add section option.</i></div>' : "")}
          ${(() => { const ls = courseLinks(c, e).filter((l) => l.label !== "The Coop"); return ls.length ? `<div class="line quick-links">${ls.map((l) => linkA(l, l.label.replace(" Site", "").replace(" Report", " Guide"))).join("")}</div>` : ""; })()}
          <div class="form-slot"></div>
        </div>
      </li>`;
    }).join("");
    attachSectionForm();
  }

  const lastFormType = {}; // remembers the type last used in each course's form
  let openFormKey = null; // course whose "add section option" form is open (survives re-renders)

  function toggleSectionForm(k) {
    openFormKey = openFormKey === k ? null : k;
    renderSchedule();
  }

  function attachSectionForm() {
    if (!openFormKey) return;
    const li = $(`.sched-item[data-k="${CSS.escape(openFormKey)}"]`);
    if (!li) { openFormKey = null; return; }
    const k = openFormKey;
    const slot = $(".form-slot", li);
    slot.appendChild($("#sectionFormTpl").content.cloneNode(true));
    const form = $("form", slot);
    const entry = state.schedule[k];
    // Type dropdown: this course's section types, the common ones, and "Other…"
    const c = BY_KEY.get(k);
    const groups = sectionGroups(c, entry);
    const types = [...new Set([...groups.keys(), "Discussion", "Laboratory", "Section"])];
    form.component.innerHTML = types.map((t) => `<option>${esc(t)}</option>`).join("") + `<option value="__other">Other…</option>`;
    // default to the first type that has no posted times yet (most likely the one being typed in)
    const untimed = [...groups.entries()].find(([, opts]) => !opts.some((o) => o.meetings.some(timed)));
    form.component.value = lastFormType[k] && types.includes(lastFormType[k]) ? lastFormType[k] : (untimed ? untimed[0] : types[0]);
    const autoLabel = () => {
      const t = form.component.value;
      const n = sectionOptions(c, entry).filter((o) => o.source === "manual" && o.component === t).length + 1;
      return `${t === "Laboratory" ? "Lab" : t} ${n}`;
    };
    let labelEdited = false;
    form.label.value = autoLabel();
    form.label.addEventListener("input", () => (labelEdited = true));
    form.component.addEventListener("change", () => {
      if (form.component.value === "__other") {
        const name = (prompt("Section type name (e.g. Tutorial, Recitation):") || "").trim();
        if (!name) { form.component.value = types[0]; return; }
        form.component.insertAdjacentHTML("afterbegin", `<option>${esc(name)}</option>`);
        form.component.value = name;
      }
      if (!labelEdited) form.label.value = autoLabel();
    });
    $$(".days button", form).forEach((b) => b.addEventListener("click", () => b.classList.toggle("on")));
    form.start.focus();
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const days = $$(".days button.on", form).map((b) => b.dataset.d);
      const start = toMin(form.start.value), end = toMin(form.end.value);
      if (!days.length) { alert("Pick at least one day."); return; }
      if (start == null || end == null || end <= start) { alert("End time must be after start time."); return; }
      entry.options = entry.options || [];
      const component = form.component.value === "__other" ? "Section" : form.component.value;
      lastFormType[k] = component;
      entry.options.push({ id: "m-" + uid(), label: form.label.value.trim() || component, component, days, start, end });
      persist();
      renderCalendar(); // re-renders the schedule; form stays open for the next option
      renderResults();
    });
  }

  // ------------------------------------------------------------ actions
  function toggleCourse(k) {
    if (state.schedule[k]) {
      delete state.schedule[k];
      if (openFormKey === k) openFormKey = null;
    } else {
      const used = new Set(Object.values(state.schedule).map((e) => e.color));
      const color = PALETTE.find((p) => !used.has(p)) || PALETTE[Object.keys(state.schedule).length % PALETTE.length];
      state.schedule[k] = { color, picks: {}, options: [] };
    }
    persist();
    renderResults();
    renderCalendar();
  }

  function pickSection(k, optId) {
    const e = state.schedule[k], c = BY_KEY.get(k);
    if (!e || !c) return;
    const o = sectionOptions(c, e).find((x) => x.id === optId);
    if (!o) return;
    e.picks = e.picks || {};
    if (e.picks[o.component] === optId) delete e.picks[o.component];
    else e.picks[o.component] = optId;
    persist();
    renderCalendar();
    renderResults();
  }

  function openDrawer(k) {
    const c = BY_KEY.get(k);
    if (!c) return;
    const added = !!state.schedule[k];
    const row = (label, v) => (v ? `<dt>${label}</dt><dd>${esc(v)}</dd>` : "");
    $("#drawerBody").innerHTML = `
      <div class="code">${esc(c.code)}</div>
      <h3>${esc(c.title)}</h3>
      <div class="muted">${esc(c.instructors?.join(", ") || "Instructor TBA")}</div>
      <div class="actions">
        <button class="btn" data-toggle="${esc(k)}">${added ? "Remove from schedule" : "Add to schedule"}</button>
        ${c.url ? linkA({ url: c.url }, "my.harvard") : ""}
        ${courseLinks(c, state.schedule[k]).map((l) => linkA(l)).join("")}
      </div>
      <dl>
        ${row("Term", `${c.term} · ${c.session || ""}`)}
        ${row("Meets", (c.meetings || []).map(meetingStr).join(" · ") || "TBA")}
        ${row("Dates", c.dates)}
        ${row("Department", c.department)}
        ${row("Component", c.component)}
        ${row("Credits", c.credits)}
        ${row("Gen Ed", c.genEd)}
        ${row("Divisional", c.divisional)}
        ${row("Consent", c.consent)}
        ${row("Class #", c.classNumber)}
        ${[...sectionGroups(c, state.schedule[k]).entries()].map(([comp, opts]) => {
          const t = opts.filter((o) => o.meetings.some(timed));
          return `<dt>${esc(comp)}</dt><dd>${t.length ? t.map((o) => `${esc(o.label)}: ${esc(o.meetings.map(meetingStr).join(", "))}${o.notes ? ` <span class="muted">(${esc(o.notes.join(", "))})</span>` : ""}${(o.links || []).filter((l) => l.label === "Canvas Site").map((l) => ` · ${linkA(l, "Canvas")}`).join("")}`).join("<br>") : "Required, times not posted yet"}</dd>`;
        }).join("") || (c.needsSections ? row("Sections", "Requires an additional section") : "")}
      </dl>
      <p>${esc(c.fullDescription || c.description || "No description.")}</p>`;
    $("#drawer").classList.add("open");
    $("#drawer").setAttribute("aria-hidden", "false");
  }
  const closeDrawer = () => { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); };

  function exportIcs() {
    const entries = Object.entries(state.schedule).map(([k, e]) => [e, BY_KEY.get(k)]).filter(([, c]) => c && (!state.term || c.term === state.term));
    if (!entries.length) return alert("Nothing on your schedule yet.");
    const BYDAY = { Mo: "MO", Tu: "TU", We: "WE", Th: "TH", Fr: "FR", Sa: "SA", Su: "SU" };
    const JS_DAY = { Su: 0, Mo: 1, Tu: 2, We: 3, Th: 4, Fr: 5, Sa: 6 };
    const parseDate = (s) => { const d = new Date(String(s).replace(/\./g, "").replace(/Sept/, "Sep")); return isNaN(d) ? null : d; };
    const pad = (n) => String(n).padStart(2, "0");
    const stamp = (d, min) => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}T${pad(Math.floor(min / 60))}${pad(min % 60)}00`;
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Crimson Atlas//EN"];
    for (const [e, c] of entries) {
      const range = (c.dates || "").split("–").map((s) => parseDate(s.trim()));
      const [from, to] = range.length === 2 && range[0] && range[1] ? range : [new Date(), new Date(Date.now() + 1000 * 3600 * 24 * 100)];
      const blocks = (c.meetings || []).filter(timed).map((m) => [m, c.component || "Lecture"]);
      for (const sec of pickedSections(c, e)) sec.meetings.filter(timed).forEach((m) => blocks.push([m, `${sec.component} ${sec.label}`]));
      for (const [m, what] of blocks) {
        const first = new Date(from);
        while (!m.days.includes(Object.keys(JS_DAY).find((d) => JS_DAY[d] === first.getDay()))) first.setDate(first.getDate() + 1);
        lines.push("BEGIN:VEVENT", `UID:${uid()}@crimson-atlas`, `SUMMARY:${c.code} ${what}`, `DESCRIPTION:${c.title.replace(/[,;]/g, "\\$&")}`,
          `DTSTART;TZID=America/New_York:${stamp(first, m.start)}`, `DTEND;TZID=America/New_York:${stamp(first, m.end)}`,
          `RRULE:FREQ=WEEKLY;BYDAY=${m.days.map((d) => BYDAY[d]).join(",")};UNTIL=${stamp(to, 23 * 60 + 59)}`, "END:VEVENT");
      }
    }
    lines.push("END:VCALENDAR");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/calendar" }));
    a.download = `schedule-${(state.term || "harvard").replace(/\s+/g, "-")}.ics`;
    a.click();
  }

  // ------------------------------------------------------------ drafts, export / import
  const activeDraft = () => state.drafts.find((d) => d.id === state.activeDraft);
  const draftCount = (d) => Object.keys(d.schedule).length;

  function toast(msg, ms = 3500) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove("show"), ms);
  }

  function uniqueName(base) {
    const names = new Set(state.drafts.map((d) => d.name));
    if (!names.has(base)) return base;
    for (let i = 2; ; i++) if (!names.has(`${base} (${i})`)) return `${base} (${i})`;
  }
  const nextDefaultName = () => uniqueName(`Schedule ${state.drafts.length + 1}`);

  function renderDrafts() {
    $("#draftSel").innerHTML = state.drafts
      .map((d) => `<option value="${esc(d.id)}">${esc(d.name)} · ${draftCount(d)} course${draftCount(d) === 1 ? "" : "s"}</option>`).join("")
      + `<option disabled>──────────</option><option value="__new">＋ New draft</option>`;
    $("#draftSel").value = state.activeDraft;
    $("#schedTitle").textContent = activeDraft().name;
  }

  function switchDraft(id) {
    const d = state.drafts.find((x) => x.id === id);
    if (!d) return;
    state.activeDraft = id;
    state.schedule = d.schedule;
    openFormKey = null;
    persist();
    renderResults();
    renderCalendar();
  }

  function addDraft(name, schedule = {}) {
    const d = { id: "d-" + uid(), name, schedule };
    state.drafts.push(d);
    switchDraft(d.id);
    return d;
  }

  /** Portable form of a draft. Keys plus code/term so it still resolves if the data is re-scraped. */
  function serializeDraft(d) {
    return {
      app: "crimson-atlas",
      version: 1,
      name: d.name,
      exported: new Date().toISOString(),
      courses: Object.entries(d.schedule).map(([key, e]) => {
        const c = BY_KEY.get(key);
        return { key, code: c?.code, term: c?.term, color: e.color, picks: e.picks || {}, options: e.options || [] };
      }),
    };
  }

  /** Ask whether an import goes into a new draft or replaces the one being viewed. Resolves "new" | "replace" | "cancel". */
  function askImportTarget(name, count, missing) {
    const dlg = $("#importDialog");
    const cur = activeDraft();
    $("#importMsg").textContent =
      `"${name}" has ${count} course${count === 1 ? "" : "s"}${missing ? ` (${missing} couldn't be found and will be skipped)` : ""}. ` +
      `Add it as a new draft, or replace "${cur.name}"${draftCount(cur) ? ` (${draftCount(cur)} course${draftCount(cur) === 1 ? "" : "s"})` : " (empty)"}?`;
    $("#importReplace").textContent = `Replace "${cur.name}"`;
    return new Promise((resolve) => {
      const onClick = (e) => {
        const b = e.target.closest("[data-choice]");
        if (!b) return;
        finish(b.dataset.choice);
      };
      const onCancel = (e) => { e.preventDefault(); finish("cancel"); }; // Esc key
      const finish = (choice) => {
        dlg.removeEventListener("click", onClick);
        dlg.removeEventListener("cancel", onCancel);
        dlg.close();
        resolve(choice);
      };
      dlg.addEventListener("click", onClick);
      dlg.addEventListener("cancel", onCancel);
      dlg.showModal();
    });
  }

  async function importPayload(data, source) {
    if (!data || data.app !== "crimson-atlas" || !Array.isArray(data.courses)) {
      alert(`That ${source} isn't a Crimson Atlas schedule.`);
      return;
    }
    const schedule = {}, missing = [];
    for (const x of data.courses) {
      let key = BY_KEY.has(x.key) ? x.key : null;
      if (!key && x.code) { // course data was re-scraped: match on term + code instead
        const c = ALL.find((y) => y.code === x.code && (!x.term || y.term === x.term));
        if (c) key = keyOf(c);
      }
      if (!key) { missing.push(x.code || x.key); continue; }
      schedule[key] = {
        color: /^#[0-9a-f]{6}$/i.test(x.color || "") ? x.color : PALETTE[Object.keys(schedule).length % PALETTE.length],
        picks: x.picks && typeof x.picks === "object" ? x.picks : {},
        options: Array.isArray(x.options) ? x.options : [],
      };
    }
    const name = String(data.name || "Imported schedule").slice(0, 60);
    const n0 = Object.keys(schedule).length;
    if (!n0) {
      alert(`None of the courses in that ${source} exist in the current course data.`);
      return;
    }
    const choice = await askImportTarget(name, n0, missing.length);
    if (choice === "cancel") return;
    let target;
    if (choice === "replace") { // keep the draft's name, swap its contents
      target = activeDraft();
      target.schedule = schedule;
      switchDraft(target.id);
    } else {
      target = addDraft(uniqueName(name), schedule);
    }
    // jump to the term the imported courses are in
    const terms = Object.keys(schedule).map((k) => BY_KEY.get(k).term);
    if (terms.length && !terms.includes(state.term)) {
      state.term = terms[0];
      $("#term").value = state.term;
      fillFacetSelects();
      persist();
      runSearch();
    }
    const n = Object.keys(schedule).length;
    toast(`Imported ${n} course${n === 1 ? "" : "s"} into "${target.name}".`);
    if (missing.length) toast(`Imported ${n} course${n === 1 ? "" : "s"} into "${target.name}". Skipped (not in current data): ${missing.join(", ")}`, 7000);
  }

  // URL-safe base64 for share links (handles non-ASCII names)
  const toB64 = (str) => btoa(String.fromCharCode(...new TextEncoder().encode(str))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const fromB64 = (b) => new TextDecoder().decode(Uint8Array.from(atob(b.replace(/-/g, "+").replace(/_/g, "/")), (ch) => ch.charCodeAt(0)));

  function importFromHash() {
    const m = location.hash.match(/^#import=([\w-]+)/);
    if (!m) return;
    history.replaceState(null, "", location.pathname + location.search);
    let data;
    try { data = JSON.parse(fromB64(m[1])); } catch { alert("That share link is broken or incomplete."); return; }
    importPayload(data, "link");
  }

  function wireDrafts() {
    $("#draftSel").addEventListener("change", (e) => {
      if (e.target.value === "__new") addDraft(nextDefaultName());
      else switchDraft(e.target.value);
    });
    // "⋯" menu: open/close; any item click closes it
    const menu = $("#draftMenu"), menuBtn = $("#draftMenuBtn");
    const setMenu = (open) => { menu.hidden = !open; menuBtn.setAttribute("aria-expanded", String(open)); };
    menuBtn.addEventListener("click", (e) => { e.stopPropagation(); setMenu(menu.hidden); });
    menu.addEventListener("click", () => setMenu(false));
    document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) setMenu(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });
    $("#draftNew").addEventListener("click", () => addDraft(nextDefaultName()));
    $("#draftDup").addEventListener("click", () => {
      const d = activeDraft();
      addDraft(uniqueName(`${d.name} copy`), JSON.parse(JSON.stringify(d.schedule)));
    });
    $("#draftRename").addEventListener("click", () => {
      const d = activeDraft();
      const name = (prompt("Rename draft:", d.name) || "").trim().slice(0, 60);
      if (name && name !== d.name) { d.name = uniqueName(name); persist(); renderDrafts(); }
    });
    $("#draftDelete").addEventListener("click", () => {
      const d = activeDraft();
      if (draftCount(d) && !confirm(`Delete "${d.name}" and its ${draftCount(d)} course(s)? This can't be undone. (Export it first if you might want it back.)`)) return;
      state.drafts = state.drafts.filter((x) => x !== d);
      if (!state.drafts.length) state.drafts.push({ id: "d-" + uid(), name: "Schedule 1", schedule: {} });
      switchDraft(state.drafts[0].id);
    });
    $("#exportBtn").addEventListener("click", () => {
      const d = activeDraft();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(serializeDraft(d), null, 2)], { type: "application/json" }));
      a.download = `${d.name.replace(/[^\w\- ]+/g, "").trim() || "schedule"}.crimson-atlas.json`;
      a.click();
      toast(`Exported "${d.name}".`);
    });
    $("#importBtn").addEventListener("click", () => $("#importFile").click());
    $("#importFile").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      e.target.value = "";
      if (!f) return;
      try { await importPayload(JSON.parse(await f.text()), "file"); }
      catch { alert("Couldn't read that file. Is it a Crimson Atlas export?"); }
    });
    $("#shareBtn").addEventListener("click", async () => {
      const d = activeDraft();
      if (!draftCount(d)) return toast("This draft is empty. Add some courses first.");
      const p = serializeDraft(d);
      delete p.exported;
      const url = `${location.origin}${location.pathname}#import=${toB64(JSON.stringify(p))}`;
      try { await navigator.clipboard.writeText(url); toast("Link copied. Opening it adds this schedule as a draft."); }
      catch { prompt("Copy this link:", url); }
    });
  }

  let searchTimer;
  const runSearchSoon = () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 60); };

  // ------------------------------------------------------------ wiring
  function wire() {
    $("#q").addEventListener("input", runSearchSoon);
    $("#term").addEventListener("change", (e) => { state.term = e.target.value; fillFacetSelects(); persist(); runSearch(); });
    $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; persist(); runSearch(); });
    $("#after").addEventListener("change", (e) => { state.after = e.target.value; persist(); runSearch(); });
    $("#before").addEventListener("change", (e) => { state.before = e.target.value; persist(); runSearch(); });
    $("#dept").addEventListener("change", (e) => { state.dept = e.target.value; runSearch(); });
    $("#gened").addEventListener("change", (e) => { state.gened = e.target.value; runSearch(); });
    for (const id of ["hideTba", "fits", "previewAll"]) {
      $("#" + id).addEventListener("change", (e) => { state[id] = e.target.checked; persist(); runSearch(); });
    }
    $$("#days button").forEach((b) => b.addEventListener("click", () => {
      state.days.has(b.dataset.d) ? state.days.delete(b.dataset.d) : state.days.add(b.dataset.d);
      b.classList.toggle("on");
      persist(); runSearch();
    }));

    const results = $("#results");
    results.addEventListener("click", (e) => {
      if (e.target.closest(".more")) { shown += PAGE; renderResults(); return; }
      const li = e.target.closest(".result");
      if (!li) return;
      if (e.target.closest(".add")) toggleCourse(li.dataset.k);
      else openDrawer(li.dataset.k);
    });
    results.addEventListener("keydown", (e) => {
      const li = e.target.closest(".result");
      if (li && e.key === "Enter") toggleCourse(li.dataset.k);
    });
    const setHover = (k) => { if (k !== hoverKey) { hoverKey = k; renderCalendarOnly(); } };
    results.addEventListener("mouseover", (e) => setHover(e.target.closest(".result")?.dataset.k || null));
    results.addEventListener("focusin", (e) => setHover(e.target.closest(".result")?.dataset.k || null));
    results.addEventListener("mouseleave", () => setHover(null));

    $("#calendar").addEventListener("click", (e) => {
      const ev = e.target.closest(".ev");
      if (!ev) return;
      if (ev.dataset.opt) pickSection(ev.dataset.k, ev.dataset.opt);
      else openDrawer(ev.dataset.k);
    });

    $("#schedList").addEventListener("click", (e) => {
      const li = e.target.closest(".sched-item");
      if (!li) return;
      const k = li.dataset.k;
      if (e.target.closest("[data-remove]")) toggleCourse(k);
      else if (e.target.closest("[data-info]")) openDrawer(k);
      else if (e.target.closest("[data-addopt]")) toggleSectionForm(k);
      else if (e.target.closest("[data-pick]")) pickSection(k, e.target.closest("[data-pick]").dataset.pick);
      else if (e.target.closest("[data-delopt]")) {
        const id = e.target.closest("[data-delopt]").dataset.delopt;
        const entry = state.schedule[k];
        entry.options = (entry.options || []).filter((o) => o.id !== id);
        for (const [comp, pid] of Object.entries(entry.picks || {})) if (pid === id) delete entry.picks[comp];
        persist(); renderCalendar(); renderResults();
      }
    });

    $("#clearSched").addEventListener("click", () => {
      if (confirm("Remove every course (and your section options) from this term's schedule?")) {
        for (const k of Object.keys(state.schedule)) if (!state.term || BY_KEY.get(k)?.term === state.term) delete state.schedule[k];
        persist(); renderResults(); renderCalendar();
      }
    });
    $("#exportIcs").addEventListener("click", exportIcs);
    wireDrafts();
    $(".drawer-close").addEventListener("click", closeDrawer);
    $("#drawer").addEventListener("click", (e) => {
      const t = e.target.closest("[data-toggle]");
      if (t) { toggleCourse(t.dataset.toggle); openDrawer(t.dataset.toggle); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeDrawer();
      if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); $("#q").focus(); }
    });
    $("#theme").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      state.theme = dark ? "light" : "dark";
      document.documentElement.dataset.theme = state.theme;
      persist();
    });
  }

  // hover only changes the calendar; don't rebuild the schedule panel (keeps open forms intact)
  const renderCalendarOnly = () => renderCalendar({ skipSchedule: true });

  function fillFacetSelects() {
    const inTerm = ALL.filter((c) => !state.term || c.term === state.term);
    const depts = [...new Set(inTerm.map((c) => c.department).filter(Boolean))].sort();
    $("#dept").innerHTML = `<option value="">All departments</option>` + depts.map((d) => `<option>${esc(d)}</option>`).join("");
    const gens = [...new Set(inTerm.flatMap((c) => [c.genEd, c.divisional]).filter(Boolean))].sort();
    $("#gened").innerHTML = `<option value="">Any Gen Ed / divisional</option>` + gens.map((d) => `<option>${esc(d)}</option>`).join("");
    $("#gened").hidden = !gens.length;
    state.dept = state.gened = "";
  }

  async function init() {
    if (state.theme) document.documentElement.dataset.theme = state.theme;
    $("#sort").value = state.sort;
    $("#after").value = state.after;
    $("#before").value = state.before;
    $("#hideTba").checked = state.hideTba;
    $("#fits").checked = state.fits;
    $("#previewAll").checked = state.previewAll;
    $$("#days button").forEach((b) => b.classList.toggle("on", state.days.has(b.dataset.d)));
    wire();

    let index;
    try {
      [ALL, index] = await Promise.all([
        fetch("data/courses.json").then((r) => r.json()),
        fetch("data/index.json").then((r) => r.json()).catch(() => ({})),
      ]);
    } catch (err) {
      $("#results").innerHTML = `<li class="empty" style="padding:14px">Couldn't load <code>data/courses.json</code>. Run the scraper, then serve this folder with <code>python3 -m http.server</code>.</li>`;
      return;
    }
    ALL.forEach(buildIndex);
    BY_KEY = new Map(ALL.map((c) => [keyOf(c), c]));
    // migrate schedules saved before multi-component picks
    for (const [k, e] of Object.entries(state.schedule)) {
      e.picks = e.picks || {};
      if (e.sectionId) {
        const c = BY_KEY.get(k);
        const o = c && sectionOptions(c, e).find((x) => x.id === e.sectionId);
        if (o) e.picks[o.component] = o.id;
        delete e.sectionId;
      }
    }

    const terms = index.terms || [...new Set(ALL.map((c) => c.term))].sort();
    $("#term").innerHTML = terms.map((t) => `<option>${esc(t)}</option>`).join("");
    if (!terms.includes(state.term)) state.term = terms[terms.length - 1] || "";
    $("#term").value = state.term;
    $("#stats").textContent = `${ALL.length.toLocaleString()} courses${index.updated ? ` · updated ${index.updated}` : ""}`;
    fillFacetSelects();
    runSearch();
    importFromHash();
  }

  init();
})();
