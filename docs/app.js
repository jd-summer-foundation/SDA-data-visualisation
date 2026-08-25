/* SDA Market Explorer
   One dataset, one profile component, rendered identically at every level:
   Australia, each state/territory, each SA4, and each SA3. */
"use strict";

const RATIO_GOOD = 1.25;   // comfortably supplied
const RATIO_TIGHT = 1.0;   // below this, fewer places than participants

let DATA = null;
let VAC = null;                       // loaded on first entry to the vacancy view
let BY_ID = new Map();
let CHILDREN = new Map();
let current = null;
let view = "supply";
let childLevel = null;
let vacChildLevel = null;
let sort = { key: null, dir: -1 };
let vacSort = { key: null, dir: -1 };

/* ---------- formatting ---------- */
const fmt = v => (v === null || v === undefined) ? null : Math.round(v).toLocaleString("en-AU");
const cell = v => { const s = fmt(v); return s === null ? '<span class="nil">&mdash;</span>' : s; };

const pct = (v, dp = 1) =>
  (v === null || v === undefined) ? null : (v * 100).toFixed(dp) + "%";
const pctCell = v => pct(v) ?? '<span class="nil">&mdash;</span>';

function ratioChip(r) {
  if (r === null || r === undefined) return '<span class="nil">&mdash;</span>';
  const cls = r < RATIO_TIGHT ? "r-crit" : r < RATIO_GOOD ? "r-warn" : "r-good";
  // Form as well as number: the glyph carries the verdict where colour cannot.
  const mark = r < RATIO_TIGHT ? "▼" : r < RATIO_GOOD ? "◆" : "▲";
  const label = r < RATIO_TIGHT ? "fewer places than participants"
              : r < RATIO_GOOD ? "roughly balanced" : "more places than participants";
  return `<span class="ratio ${cls}" title="${r.toFixed(2)} places per participant — ${label}">`
       + `<i aria-hidden="true">${mark}</i>${r.toFixed(2)}<span class="sr-only"> — ${label}</span></span>`;
}

/* ---------- loading ---------- */
async function boot() {
  let res;
  try {
    res = await fetch("data/sda.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    document.getElementById("loading").innerHTML =
      `Could not load data/sda.json (${err.message}).<br>`
      + `Run <code>python3 scripts/extract_sda.py &lt;workbook.xlsx&gt;</code> to build it.`;
    return;
  }

  DATA.geographies.forEach(g => {
    BY_ID.set(g.id, g);
    if (!CHILDREN.has(g.parent)) CHILDREN.set(g.parent, []);
    CHILDREN.get(g.parent).push(g);
  });

  document.getElementById("brandSub").textContent = `NDIS Supplement P · as at ${DATA.meta.as_at}`;
  document.getElementById("loading").hidden = true;
  document.getElementById("view").hidden = false;

  wireSearch();
  wireViewSwitch();
  window.addEventListener("hashchange", routeFromHash);
  routeFromHash();
}

/* The hash is either a bare geography id — every link ever published — or
   "vacancy!<id>". Splitting on the first "!" keeps the old links working, and
   ids may themselves contain colons ("sa4:VIC - Geelong"). */
function parseHash() {
  const raw = decodeURIComponent(location.hash.replace(/^#/, ""));
  const cut = raw.indexOf("!");
  const name = cut === -1 ? "supply" : raw.slice(0, cut);
  const id = cut === -1 ? raw : raw.slice(cut + 1);
  return { view: name === "vacancy" ? "vacancy" : "supply", id: id || "national" };
}

const hashFor = (name, id) =>
  "#" + (name === "vacancy" ? "vacancy!" : "") + encodeURIComponent(id);

function routeFromHash() {
  const route = parseHash();
  view = route.view;
  render(BY_ID.has(route.id) ? route.id : "national");
}

function go(id, name = view) {
  const next = hashFor(name, id);
  if (location.hash === next) { view = name; render(id); }
  else location.hash = next;
}

function wireViewSwitch() {
  document.getElementById("viewSwitch").addEventListener("click", e => {
    const btn = e.target.closest("button[data-view]");
    if (btn && btn.dataset.view !== view) go(current.id, btn.dataset.view);
  });
}

/* The vacancy bundle is only fetched when someone actually asks for it, so the
   supply view still loads one file. */
async function loadVacancies() {
  if (VAC) return VAC;
  const res = await fetch("data/vacancies.json");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  VAC = await res.json();
  return VAC;
}

/* ---------- search ---------- */
function wireSearch() {
  const input = document.getElementById("search");
  const box = document.getElementById("results");
  let active = -1, shown = [];

  const close = () => { box.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };

  function draw(query) {
    const q = query.trim().toLowerCase();
    if (!q) { close(); return; }
    shown = DATA.geographies.filter(g => {
      const hay = (g.level === "National" ? "australia national" : `${g.name} ${g.state || ""} ${g.level}`).toLowerCase();
      return hay.includes(q);
    }).slice(0, 40);

    if (!shown.length) {
      box.innerHTML = '<div class="result-none">No matching geography.</div>';
    } else {
      box.innerHTML = shown.map((g, i) =>
        `<button class="result" role="option" data-i="${i}" aria-selected="${i === active}">`
        + `<span class="result-lvl">${g.level}</span>`
        + `<span>${g.level === "National" ? "Australia" : g.name}`
        + `${g.state && g.level !== "State" ? ` <span style="color:var(--ink-3)">· ${g.state}</span>` : ""}</span></button>`
      ).join("");
    }
    box.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  input.addEventListener("input", () => { active = -1; draw(input.value); });
  input.addEventListener("keydown", e => {
    if (box.hidden || !shown.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      draw(input.value);
      box.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); pick(shown[active]);
    } else if (e.key === "Escape") { close(); }
  });
  box.addEventListener("click", e => {
    const btn = e.target.closest(".result");
    if (btn) pick(shown[+btn.dataset.i]);
  });
  document.addEventListener("click", e => {
    if (!e.target.closest(".picker")) close();
  });

  function pick(g) { input.value = ""; close(); go(g.id); }
}

/* ---------- render ---------- */
function render(id) {
  current = BY_ID.get(id);
  renderChrome(current);

  document.querySelectorAll("#viewSwitch button").forEach(btn =>
    btn.setAttribute("aria-pressed", String(btn.dataset.view === view)));
  document.getElementById("viewSupply").hidden = view !== "supply";
  document.getElementById("viewVacancy").hidden = view !== "vacancy";

  if (view === "vacancy") {
    loadVacancies()
      .then(() => { if (view === "vacancy") renderVacancy(current); })
      .catch(err => {
        document.getElementById("vacEmpty").hidden = false;
        document.getElementById("vacEmpty").innerHTML =
          `Could not load data/vacancies.json (${err.message}).<br>`
          + `Run <code>python3 scripts/extract_vacancies.py &lt;vacancies.csv&gt; `
          + `--postcodes &lt;australian_postcodes.csv&gt;</code> to build it.`;
        document.getElementById("vacBody").hidden = true;
      });
  } else {
    renderSupply(current);
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

/* Breadcrumbs, title and place name are the same in both views. */
function renderChrome(g) {
  document.title = `${g.level === "National" ? "Australia" : g.name} — SDA Market Explorer`;

  // breadcrumbs
  const trail = [];
  for (let n = g; n; n = n.parent ? BY_ID.get(n.parent) : null) trail.unshift(n);
  document.getElementById("crumbs").innerHTML = trail.map((n, i) => {
    const label = n.level === "National" ? "Australia" : n.name;
    return i === trail.length - 1
      ? `<span class="here">${label}</span>`
      : `<a href="#${encodeURIComponent(n.id)}">${label}</a><span aria-hidden="true">›</span>`;
  }).join("");

  document.getElementById("placeName").textContent = g.level === "National" ? "Australia" : g.name;
  document.getElementById("placeMeta").textContent =
    [g.level === "National" ? "All regions" : g.level,
     g.state && g.level !== "State" ? g.state : null,
     `as at ${DATA.meta.as_at}`].filter(Boolean).join(" · ");

}

function renderSupply(g) {
  const cats = DATA.meta.design_categories;
  const comparable = DATA.meta.comparable_categories;

  renderTiles(g);
  renderCategoryTable(g, cats);
  renderChart(g, comparable);
  renderBreakdowns(g);
  renderChildren(g, comparable);
  renderTrend(g);
  renderNotes(g);

  document.getElementById("footNote").textContent =
    `Rows for ${g.level === "National" ? "Australia" : g.name} read from the published `
    + `${g.level === "SA3" ? "SA3" : "SA4"}-level tables of NDIS Supplement P, as at ${DATA.meta.as_at}. `
    + `State and national figures are the NDIA's own published subtotals, which reconcile exactly `
    + `with the sum of their regions.`;
}

function renderTiles(g) {
  const t = g.totals;
  const places = DATA.meta.design_categories
    .reduce((sum, c) => sum + (g.categories[c].enrolled_places || 0), 0);
  const missing = t.need_without_category;
  const share = (missing && t.participants_with_need)
    ? ` · ${(missing / t.participants_with_need * 100).toFixed(0)}% of need` : "";

  const tiles = [
    ["Enrolled dwellings", cell(t.enrolled_dwellings), null],
    ...(g.has_places ? [["Enrolled places", cell(places), "resident capacity, all categories"]] : []),
    ["Participants with need", cell(t.participants_with_need),
      t.participants_sda_in_use != null
        ? `${fmt(t.participants_sda_in_use)} using SDA · ${fmt(t.participants_eligible_not_using)} eligible, not yet using`
        : null],
    ...(g.has_places ? [["Pipeline dwellings", cell(t.pipeline_dwellings), "intended, not guaranteed"]] : []),
    ["No design category recorded", cell(missing), missing ? `unallocated demand${share}` : null],
  ];

  document.getElementById("tiles").innerHTML = tiles.map(([k, v, note]) =>
    `<div class="tile"><dt>${k}</dt><dd>${v}${note ? `<div class="tile-note">${note}</div>` : ""}</dd></div>`
  ).join("");
}

function renderCategoryTable(g, cats) {
  const comparable = new Set(DATA.meta.comparable_categories);
  document.getElementById("tableSub").textContent = g.has_places
    ? "Places are the unit comparable with participants · a dwelling may hold several"
    : "Places are not published below SA4, so no ratio can be formed at SA3";

  const rows = cats.map(c => {
    const x = g.categories[c];
    const isComparable = comparable.has(c);
    const blank = !x.enrolled_dwellings && !x.participants_with_need && !x.pipeline_dwellings;
    if (blank && !isComparable) return "";
    return `<tr${isComparable ? "" : ' class="dim"'}>`
      + `<td>${c}${isComparable ? "" : '<div style="font-weight:400;font-size:11.5px;color:var(--ink-3)">no eligibility decisions issued</div>'}</td>`
      + `<td>${cell(x.enrolled_dwellings)}</td>`
      + `<td>${g.has_places ? cell(x.enrolled_places) : '<span class="nil">n/p</span>'}</td>`
      + `<td>${cell(x.participants_with_need)}</td>`
      + `<td>${g.has_places ? ratioChip(x.places_per_participant) : '<span class="nil">&mdash;</span>'}</td>`
      + `<td>${cell(x.pipeline_dwellings)}</td>`
      + `<td>${g.has_places ? cell(x.pipeline_places) : '<span class="nil">n/p</span>'}</td>`
      + `</tr>`;
  }).join("");

  const missing = g.totals.need_without_category;
  const extra = missing
    ? `<tr class="dim"><td>No category recorded<div style="font-weight:400;font-size:11.5px;color:var(--ink-3)">could not be extracted from NDIA systems</div></td>`
      + `<td class="nil">&mdash;</td><td class="nil">&mdash;</td><td>${cell(missing)}</td>`
      + `<td class="nil">&mdash;</td><td class="nil">&mdash;</td><td class="nil">&mdash;</td></tr>` : "";

  document.getElementById("catBody").innerHTML = rows + extra;
}

function renderChart(g, comparable) {
  const panel = document.getElementById("chartPanel");
  if (!g.has_places) { panel.hidden = true; return; }
  panel.hidden = false;

  const rows = comparable.map(c => ({ name: c, ...g.categories[c] }));
  const max = Math.max(1, ...rows.flatMap(r =>
    [r.enrolled_places || 0, r.participants_with_need || 0, r.pipeline_places || 0]));
  const pct = v => ((v || 0) / max * 100).toFixed(2) + "%";

  document.getElementById("gapChart").innerHTML = rows.map(r => {
    const line = (tag, cls, v, tip) => `
      <div class="bar-line" title="${tip}">
        <span class="bar-tag">${tag}</span>
        <span class="bar-track"><span class="bar ${cls}" style="width:${pct(v)}"></span></span>
        <span class="bar-val">${v == null ? "—" : fmt(v)}</span>
      </div>`;
    return `<div class="gap-row">
      <div class="gap-label"><span class="gap-name">${r.name}</span>${ratioChip(r.places_per_participant)}</div>
      <div class="bars">
        ${line("Places", "bar-supply", r.enrolled_places, `${r.name} — ${fmt(r.enrolled_places) || 0} enrolled places from ${fmt(r.enrolled_dwellings) || 0} dwellings`)}
        ${line("Need", "bar-demand", r.participants_with_need, `${r.name} — ${fmt(r.participants_with_need) || 0} participants with an identified need`)}
        ${line("Pipeline", "bar-pipe", r.pipeline_places, `${r.name} — ${fmt(r.pipeline_places) || 0} pipeline places (an intention, not guaranteed supply)`)}
      </div></div>`;
  }).join("");
}

function renderBreakdowns(g) {
  const draw = (host, sub, data, note) => {
    const entries = Object.entries(data).filter(([k, v]) => k !== "Total" && typeof v === "number");
    const max = Math.max(1, ...entries.map(([, v]) => v));
    document.getElementById(sub).textContent = note;
    document.getElementById(host).innerHTML = entries.length
      ? entries.map(([k, v]) => `
        <div class="minirow" title="${k} — ${fmt(v)} dwellings">
          <span class="lbl">${k}</span>
          <span><span class="minibar" style="width:${(v / max * 100).toFixed(2)}%"></span></span>
          <span class="val">${fmt(v)}</span>
        </div>`).join("")
      : '<p class="empty">No breakdown published for this region.</p>';
  };
  draw("buildBars", "buildSub", g.build_types, "Existing, legacy and new build");
  draw("resBars", "resSub", g.max_residents, "Enrolled maximum residents per dwelling");
}

function renderChildren(g, comparable) {
  const panel = document.getElementById("childPanel");
  const kids = CHILDREN.get(g.id) || [];
  if (!kids.length) { panel.hidden = true; return; }
  panel.hidden = false;

  const levels = [...new Set(kids.map(k => k.level))];
  if (!levels.includes(childLevel)) childLevel = levels[0];

  document.getElementById("levelSwitch").innerHTML = levels.length > 1
    ? levels.map(l => `<button type="button" data-level="${l}" aria-pressed="${l === childLevel}">${l}</button>`).join("")
    : "";
  document.getElementById("levelSwitch").onclick = e => {
    const btn = e.target.closest("button[data-level]");
    if (!btn) return;
    childLevel = btn.dataset.level;
    sort = { key: null, dir: -1 };
    renderChildren(g, comparable);
  };

  // "<State> - Other" rows exist for participants whose region is unknown; drop
  // them where they carry nothing, but keep them where they hold real counts.
  const hasData = k => (k.totals.enrolled_dwellings || 0) > 0
                    || (k.totals.participants_with_need || 0) > 0;
  const shown = kids.filter(k => k.level === childLevel && hasData(k));
  document.getElementById("childTitle").textContent =
    `${shown.length} ${childLevel === "State" ? "states and territories" : `${childLevel} regions`} within `
    + `${g.level === "National" ? "Australia" : g.name}`;

  const withPlaces = shown.some(s => s.has_places);
  const cols = [
    { key: "name", label: "Region", num: false },
    { key: "dwellings", label: "Enrolled<br>dwellings", get: s => s.totals.enrolled_dwellings },
    { key: "need", label: "Participants<br>with need", get: s => s.totals.participants_with_need },
    ...(withPlaces ? comparable.map(c => ({
      key: c, label: c.replace(/ /g, "<br>"), ratio: true,
      get: s => s.categories[c].places_per_participant
    })) : []),
  ];

  document.getElementById("childHead").innerHTML = cols.map(c =>
    `<th scope="col" class="sortable" data-key="${c.key}"${sort.key === c.key ? ` aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : ""}>`
    + `${c.label} <span class="sortcue" aria-hidden="true">${sort.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span></th>`
  ).join("");

  const rows = [...shown];
  if (sort.key) {
    const col = cols.find(c => c.key === sort.key);
    rows.sort((a, b) => {
      if (!col.get) return sort.dir * a.name.localeCompare(b.name);
      const x = col.get(a), y = col.get(b);
      // Regions with no value sort last regardless of direction.
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return sort.dir * (x - y);
    });
  } else {
    rows.sort((a, b) => (b.totals.enrolled_dwellings || 0) - (a.totals.enrolled_dwellings || 0));
  }

  document.getElementById("childBody").innerHTML = rows.map(s =>
    `<tr class="linked" data-id="${encodeURIComponent(s.id)}">`
    + cols.map(c => c.key === "name"
        ? `<td class="region"><a href="#${encodeURIComponent(s.id)}">${s.name}</a></td>`
        : `<td>${c.ratio ? ratioChip(c.get(s)) : cell(c.get(s))}</td>`).join("")
    + `</tr>`).join("");

  document.getElementById("childHead").onclick = e => {
    const th = e.target.closest("th[data-key]");
    if (!th) return;
    const key = th.dataset.key;
    sort = (sort.key === key) ? { key, dir: -sort.dir } : { key, dir: key === "name" ? 1 : -1 };
    renderChildren(g, comparable);
  };
  document.getElementById("childBody").onclick = e => {
    if (e.target.closest("a")) return;   // let the link handle its own navigation
    const tr = e.target.closest("tr[data-id]");
    if (tr) go(decodeURIComponent(tr.dataset.id));
  };
}

function renderTrend(g) {
  const panel = document.getElementById("trendPanel");
  const trend = DATA.national_trend;
  // The supplement publishes history only nationally, so this is the one level
  // where a trend can honestly be drawn.
  if (g.level !== "National" || !trend.quarters.length) { panel.hidden = true; return; }
  panel.hidden = false;

  const q = trend.quarters;
  const dwellings = trend.series.enrolled_dwellings || [];
  const need = (trend.series.sda_in_use || []).map(
    (v, i) => v + (trend.series.sda_eligible_not_using || [])[i]);
  if (!dwellings.length || !need.length) { panel.hidden = true; return; }

  const W = 900, H = 300, M = { t: 22, r: 136, b: 34, l: 46 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const yMax = Math.ceil(Math.max(...need, ...dwellings) / 7000) * 7000;
  const x = i => M.l + (i / (q.length - 1)) * iw;
  const y = v => M.t + ih - (v / yMax) * ih;
  const line = s => s.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = q.length - 1;
  const out = [`<svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="Enrolled dwellings grew from ${fmt(dwellings[0])} to ${fmt(dwellings[last])} between ${q[0]} and ${q[last]}, while participants with an SDA need grew from ${fmt(need[0])} to ${fmt(need[last])}.">`];

  for (let t = 0; t <= yMax; t += 7000) {
    out.push(`<line class="grid-line" x1="${M.l}" y1="${y(t)}" x2="${M.l + iw}" y2="${y(t)}"/>`);
    out.push(`<text x="${M.l - 9}" y="${y(t) + 3.5}" text-anchor="end">${t / 1000}k</text>`);
  }
  out.push(`<line class="axis-line" x1="${M.l}" y1="${M.t + ih}" x2="${M.l + iw}" y2="${M.t + ih}"/>`);
  q.forEach((label, i) => {
    if (i % 4 === 0 || i === last)
      out.push(`<text x="${x(i)}" y="${M.t + ih + 19}" text-anchor="middle">${label}</text>`);
  });

  out.push(`<path d="${line(need)}" fill="none" stroke="var(--demand)" stroke-width="2" stroke-linejoin="round"/>`);
  out.push(`<path d="${line(dwellings)}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`);

  [[need, "--demand", "Participants", "with SDA need"],
   [dwellings, "--accent", "Enrolled", "dwellings"]].forEach(([series, hue, l1, l2]) => {
    out.push(`<circle cx="${x(last)}" cy="${y(series[last])}" r="4.5" fill="var(${hue})" stroke="var(--surface)" stroke-width="2"/>`);
    out.push(`<text class="ser-label" x="${x(last) + 11}" y="${y(series[last]) - 3}">${l1}</text>`);
    out.push(`<text class="ser-label" x="${x(last) + 11}" y="${y(series[last]) + 12}">${l2}</text>`);
    out.push(`<text x="${x(last) + 11}" y="${y(series[last]) + 26}">${fmt(series[last])}</text>`);
  });

  q.forEach((label, i) => {
    out.push(`<g><title>${label} — ${fmt(dwellings[i])} enrolled dwellings · ${fmt(need[i])} participants with an SDA need</title>`
      + `<rect x="${x(i) - iw / (q.length - 1) / 2}" y="${M.t}" width="${iw / (q.length - 1)}" height="${ih}" fill="transparent"/></g>`);
  });
  out.push("</svg>");
  document.getElementById("trendChart").innerHTML = out.join("");

  const growth = (a, b) => `${((b / a - 1) * 100).toFixed(1)}%`;
  document.getElementById("trendNote").innerHTML =
    `Enrolled dwellings grew <b>${growth(dwellings[0], dwellings[last])}</b> between ${q[0]} and ${q[last]}, `
    + `while participants with an identified SDA need rose <b>${growth(need[0], need[last])}</b>. `
    + `Aggregate supply is catching up quickly, so the category shortfalls above are a question of `
    + `<b>composition</b> — which design categories, in which regions — rather than volume alone.`;
}

function renderNotes(g) {
  const cal = DATA.meta.derivation_calibration;
  const missing = g.totals.need_without_category;
  const share = (missing && g.totals.participants_with_need)
    ? (missing / g.totals.participants_with_need * 100).toFixed(0) : null;

  const notes = [
    ["t-block", "Places per participant is not a waiting list.",
     "Enrolled places include places that are <b>already occupied</b>, and participants with an SDA need "
     + "include people already living in SDA. A figure below 1.00 does not mean that many people are waiting. "
     + "What it does show is a mismatch of <b>mix</b>: a participant assessed as needing Fully Accessible but "
     + "housed in a Basic dwelling appears on both sides, in different categories."],
    ...(share ? [["t-block", `${share}% of demand here has no design category.`,
     `<b>${fmt(missing)}</b> of ${fmt(g.totals.participants_with_need)} participants could not have an eligible `
     + "design category extracted from NDIA systems, so they sit outside every ratio above. Where that share is "
     + "large, treat the individual category ratios as indicative."]] : []),
    ["t-care", "The pipeline is an intention, not a supply forecast.",
     "The NDIA states that pipeline dwellings may never be enrolled, may be enrolled in a different design "
     + "category, and that some already-enrolled dwellings remain in the data &mdash; overstating it. From March 2026, "
     + "dwellings that have not progressed within 36 months are removed."],
    ["t-care", "Small counts are suppressed, not zero.",
     "The NDIA publishes counts below a threshold as <b>&lt;11</b>, <b>&lt;5</b> or <b>n/a</b>. These are shown as "
     + "&mdash; rather than 0, and are excluded from totals, so figures in thin rural regions read low."],
    ...(g.has_places ? [["t-info", "Existing-stock places are derived, within a measured margin.",
     "The NDIA publishes places for new builds only. Places for existing and legacy stock are derived by "
     + "multiplying dwelling counts by the resident capacity named in each column header. Applying that same "
     + `arithmetic to new builds reproduces the NDIA's published figure exactly for <b>${(cal.exact_share * 100).toFixed(1)}%</b> `
     + `of ${cal.values_checked} values, with a largest single gap of ${cal.largest_difference_places} places and a net bias of `
     + `${(cal.net_bias_on_sa4_totals * 100).toFixed(2)}% &mdash; because a dwelling's enrolled maximum residents can be `
     + "lower than its dwelling type implies."]] : [
     ["t-info", "SA3 has no places figure.",
      "The dwelling-form cross-tabs the places derivation depends on are published at SA4 and above only, so "
      + "no places or ratio can be formed at SA3. Dwelling counts and participant need are still shown."]]),
    ["t-care", "Basic and Multi-Design Category have no demand counterpart.",
     "Neither is issued as an SDA eligibility decision &mdash; Basic decisions are now folded into "
     + "&ldquo;no category recorded&rdquo; &mdash; so no ratio is formed for them."],
  ];

  document.getElementById("notes").innerHTML = notes.map(([tag, head, body]) =>
    `<div class="note"><span class="note-tag ${tag}">${tag === "t-block" ? "Must read" : tag === "t-care" ? "Caution" : "Method"}</span>`
    + `<p><b>${head}</b> ${body}</p></div>`).join("");
}

/* ---------- vacancy view ---------- */

// Zero-valued keys are dropped from the JSON to keep it small; absent means 0.
const num = (obj, key) => (obj && obj[key]) || 0;
const shareOf = (part, whole) => whole ? part / whole : null;

function renderVacancy(g) {
  // A region with nothing listed has no entry at all; the tiles and notes still
  // render, so give them an empty profile rather than a missing one.
  const profile = VAC.regions[g.id] || {
    listings: 0, vacant_places: 0, enrolled_places: null, rate: null,
    depth: { whole: {}, rooms: {}, multi_dwelling: {} },
    by_category: [], by_capacity: [], by_form: [], by_feature: [],
    price_bands: [], top_suburbs: [],
  };
  const empty = document.getElementById("vacEmpty");
  const body = document.getElementById("vacBody");

  renderVacTiles(g, profile);
  renderVacNotes(g, profile);

  document.getElementById("footNote").textContent =
    `Vacancy listings exported from Housing Hub as at ${VAC.meta.as_at}, counted against `
    + `enrolled places from NDIS Supplement P as at ${VAC.meta.sda_as_at}. `
    + `SA4 and SA3 are assigned from each listing's suburb and postcode — the export does not `
    + `carry a statistical geography — and every one of the ${fmt(VAC.meta.listings)} listings resolved.`;

  if (!profile.listings) {
    body.hidden = true;
    empty.hidden = false;
    empty.innerHTML = `<b>No SDA vacancies are listed in ${g.level === "National" ? "Australia" : g.name}.</b> `
      + `That is an absence of listings on Housing Hub, which is not the same as an absence of `
      + `vacancy — see the notes below.`;
    return;
  }
  empty.hidden = true;
  body.hidden = false;

  renderVacDepth(g, profile);
  renderVacCategories(g, profile);
  renderVacForms(profile);
  renderVacFeatures(profile);
  renderVacBridge(g);
  renderVacChildren(g);
  renderVacPrice(profile);
  renderVacSuburbs(profile);
}

function renderVacTiles(g, p) {
  const whole = num(p.depth.whole, "places");
  const tiles = [
    ["Vacant places", cell(p.vacant_places),
      `${fmt(p.listings)} listing${p.listings === 1 ? "" : "s"}`],
    ...(p.rate != null ? [["Share of enrolled places", pctCell(p.rate),
      `of ${fmt(p.enrolled_places)} enrolled places`]] : []),
    ["In wholly empty dwellings", cell(whole),
      p.vacant_places ? `${pct(shareOf(whole, p.vacant_places), 0)} of vacant places` : null],
    ["In otherwise occupied dwellings", cell(num(p.depth.rooms, "places")),
      `${fmt(num(p.depth.rooms, "listings"))} listings with a spare room`],
  ];
  document.getElementById("vacTiles").innerHTML = tiles.map(([k, v, note]) =>
    `<div class="tile"><dt>${k}</dt><dd>${v}${note ? `<div class="tile-note">${note}</div>` : ""}</dd></div>`
  ).join("");
}

/* The headline. A vacancy is only comparable with another once you know
   whether it is a dwelling standing empty or one spare room in a share house,
   and that split is almost entirely a function of how many people the dwelling
   holds — so capacity is the axis. */
function stackRow(label, sub, parts, total, scale, extra = "") {
  const seg = (cls, v, tip) => v
    ? `<span class="stackseg ${cls}" style="width:${(v / total * 100).toFixed(2)}%" title="${tip}"></span>` : "";
  return `<div class="stackrow ${extra}">
    <span class="lbl">${label}${sub ? `<span class="sub">${sub}</span>` : ""}</span>
    <span><span class="stackbar" style="width:${(total / scale * 100).toFixed(2)}%">
      ${seg("seg-whole", parts.whole, `${fmt(parts.whole)} places in wholly empty dwellings`)}
      ${seg("seg-rooms", parts.rooms, `${fmt(parts.rooms)} places in otherwise occupied dwellings`)}
      ${seg("seg-multi", parts.multi, `${fmt(parts.multi)} places in listings covering several dwellings`)}
    </span></span>
    <span class="val">${fmt(total)}${parts.whole ? ` · ${pct(shareOf(parts.whole, total), 0)}` : ""}</span>
  </div>`;
}

function renderVacDepth(g, p) {
  const rows = p.by_capacity.filter(r => num(r, "vacant_places"));
  const scale = Math.max(1, ...rows.map(r => num(r, "vacant_places")));
  const parts = r => ({ whole: num(r, "whole_places"), rooms: num(r, "room_places"),
                        multi: num(r, "surplus_places") });

  const total = { whole: num(p.depth.whole, "places"), rooms: num(p.depth.rooms, "places"),
                  multi: num(p.depth.multi_dwelling, "places") };

  document.getElementById("vacDepthSub").textContent =
    "Vacant places by the number of residents the dwelling holds · whole dwelling, or one room in it";

  document.getElementById("vacDepth").innerHTML =
    stackRow("All vacancies", `${fmt(p.listings)} listings`, total, p.vacant_places, p.vacant_places, "total")
    + rows.map(r => stackRow(
        r.label,
        `${fmt(num(r, "listings"))} listing${num(r, "listings") === 1 ? "" : "s"}`,
        parts(r), num(r, "vacant_places"), scale)).join("");

  const one = rows.find(r => r.capacity === 1);
  const big = rows.filter(r => r.capacity >= 4)
                  .reduce((a, r) => ({ v: a.v + num(r, "vacant_places"), w: a.w + num(r, "whole_places") }),
                          { v: 0, w: 0 });
  document.getElementById("vacDepthNote").innerHTML =
    `<b>${fmt(total.whole)} of ${fmt(p.vacant_places)} vacant places (${pct(shareOf(total.whole, p.vacant_places), 0)})</b> `
    + `are in dwellings standing completely empty; ${fmt(total.rooms)} are single rooms in dwellings someone `
    + `already lives in. The split is mostly a question of dwelling size`
    + (one ? `: a ${one.label.toLowerCase()} dwelling is empty or it is not` : "")
    + (big.v ? `, while only ${pct(shareOf(big.w, big.v), 0)} of vacancy in dwellings of four or more `
             + `residents is a whole empty dwelling` : "")
    + `. A spare room is a matching problem; an empty dwelling is stranded capital.`;
}

/* Bar length is the rate where a denominator exists, and the raw count where it
   does not — Supplement P publishes no places below SA4. */
function miniBars(host, rows, { value, label, tip, note, scale }) {
  // Counts scale to the largest row; shares of a whole scale to 1, so they stay
  // comparable between regions. Seeding at 1 would flatten every fraction.
  const max = scale === "share" ? 1 : Math.max(...rows.map(value), Number.MIN_VALUE);
  document.getElementById(host).innerHTML = rows.length
    ? rows.map(r => `
      <div class="minirow" title="${tip(r)}">
        <span class="lbl">${label(r)}</span>
        <span><span class="minibar" style="width:${(value(r) / max * 100).toFixed(2)}%"></span></span>
        <span class="val">${note(r)}</span>
      </div>`).join("")
    : '<p class="empty">Nothing to show for this region.</p>';
}

function renderVacCategories(g, p) {
  const rated = p.by_category.some(r => r.rate != null);
  const rows = p.by_category.filter(r => rated ? r.rate != null : num(r, "vacant_places"));
  document.getElementById("vacCatSub").textContent = rated
    ? "Vacant places as a share of enrolled places"
    : "Vacant places · no rate, because Supplement P publishes no places below SA4";

  miniBars("vacCatBars", rows, {
    value: r => rated ? r.rate : num(r, "vacant_places"),
    label: r => r.category,
    tip: r => `${r.category} — ${fmt(num(r, "vacant_places"))} vacant places`
      + (r.enrolled_places ? ` of ${fmt(r.enrolled_places)} enrolled` : "")
      + `, ${fmt(num(r, "whole_listings"))} of ${fmt(num(r, "listings"))} listings a whole dwelling`,
    note: r => rated ? pctCell(r.rate) : fmt(num(r, "vacant_places")),
  });
}

function renderVacForms(p) {
  const rows = p.by_form;
  const scale = Math.max(1, ...rows.map(r => num(r, "vacant_places")));
  document.getElementById("vacFormBars").innerHTML = rows.map(r => stackRow(
    r.form,
    `${fmt(num(r, "listings"))} listing${num(r, "listings") === 1 ? "" : "s"}`,
    { whole: num(r, "whole_places"), rooms: num(r, "room_places"), multi: num(r, "surplus_places") },
    num(r, "vacant_places"), scale)).join("");
}

function renderVacFeatures(p) {
  const panel = document.getElementById("vacFeaturePanel");
  if (!p.by_feature.length) { panel.hidden = true; return; }
  panel.hidden = false;

  const rows = p.by_feature.flatMap(f => [
    { label: `${f.feature} — yes`, side: f.with },
    { label: `${f.feature} — no`, side: f.without },
  ]);
  miniBars("vacFeatureBars", rows, {
    value: r => shareOf(num(r.side, "whole_places"), num(r.side, "vacant_places")) || 0,
    label: r => r.label,
    tip: r => `${r.label} — ${fmt(num(r.side, "whole_places"))} of ${fmt(num(r.side, "vacant_places"))} `
      + `vacant places are a whole empty dwelling`,
    note: r => pctCell(shareOf(num(r.side, "whole_places"), num(r.side, "vacant_places"))),
    scale: "share",
  });
}

/* The one place the two datasets can be checked against each other: where
   Supplement P reports more enrolled places per participant than a region's
   assessed need, more of those places turn up listed as vacant. */
function renderVacBridge(g) {
  const panel = document.getElementById("vacBridgePanel");
  const points = VAC.bridge;
  if (!points.length) { panel.hidden = true; return; }
  panel.hidden = false;

  // Only ids that actually carry points, so the note never claims a highlight
  // that is not on screen. An SA3 has no points of its own and cannot reach its
  // SA4 — Supplement P hangs SA3 off the state — so it highlights nothing.
  const withPoints = new Set(points.map(p => p.region_id));
  const here = new Set(
    (g.level === "National" ? []
      : g.level === "State" ? points.filter(p => p.state === g.state).map(p => p.region_id)
      : [g.id]).filter(id => withPoints.has(id)));

  const W = 900, H = 340, M = { t: 18, r: 20, b: 52, l: 58 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const xMax = Math.ceil(Math.max(...points.map(p => p.places_per_participant)) * 2) / 2;
  const yMax = Math.ceil(Math.max(...points.map(p => p.rate)) * 20) / 20;
  const x = v => M.l + Math.min(v / xMax, 1) * iw;
  const y = v => M.t + ih - (v / yMax) * ih;

  const corr = VAC.meta.bridge_correlation;
  const wr = corr.within_region;
  const out = [`<svg class="scatter" viewBox="0 0 ${W} ${H}" role="img" aria-label="`
    + `Across ${corr.points} SA4 and design category combinations, regions with more enrolled places `
    + `per participant tend to have a higher share of those places listed vacant. `
    + `Spearman rank correlation ${corr.spearman.toFixed(2)}`
    + (wr ? `, rising to ${wr.r.toFixed(2)} when categories are compared within a single region` : "")
    + `. Pooled vacancy runs `
    + corr.tertiles.map(t => `${pct(t.rate, 1)} in the ${t.label.toLowerCase()} of the range`).join(", ")
    + `.">`];

  for (let t = 0; t <= yMax + 1e-9; t += yMax / 4) {
    out.push(`<line class="grid-line" x1="${M.l}" y1="${y(t).toFixed(1)}" x2="${M.l + iw}" y2="${y(t).toFixed(1)}"/>`);
    out.push(`<text x="${M.l - 9}" y="${(y(t) + 3.5).toFixed(1)}" text-anchor="end">${(t * 100).toFixed(0)}%</text>`);
  }
  // 1.00 places per participant is where a region has exactly as many places as
  // participants assessed as needing that category.
  out.push(`<line class="axis-line" x1="${x(1)}" y1="${M.t}" x2="${x(1)}" y2="${M.t + ih}"/>`);
  out.push(`<text x="${x(1)}" y="${M.t - 5}" text-anchor="middle">1.00</text>`);
  out.push(`<line class="axis-line" x1="${M.l}" y1="${M.t + ih}" x2="${M.l + iw}" y2="${M.t + ih}"/>`);
  for (let t = 0; t <= xMax + 1e-9; t += xMax / 5) {
    out.push(`<text x="${x(t).toFixed(1)}" y="${M.t + ih + 19}" text-anchor="middle">${t.toFixed(1)}</text>`);
  }
  out.push(`<text class="axis-title" x="${M.l + iw / 2}" y="${H - 8}" text-anchor="middle">Enrolled places per participant with that need &rarr;</text>`);
  out.push(`<text class="axis-title" transform="translate(14 ${M.t + ih / 2}) rotate(-90)" text-anchor="middle">Share listed vacant &rarr;</text>`);

  // Highlighted points last, so they sit above the cloud.
  [...points].sort((a, b) => Number(here.has(a.region_id)) - Number(here.has(b.region_id)))
    .forEach(p => {
      const mine = here.has(p.region_id);
      out.push(`<g><title>${p.region} (${p.state}) — ${p.category}: `
        + `${fmt(p.vacant_places)} of ${fmt(p.enrolled_places)} enrolled places listed vacant `
        + `(${pct(p.rate)}), ${p.places_per_participant.toFixed(2)} places per participant</title>`
        + `<circle class="pt${mine ? " pt-here" : ""}" cx="${x(p.places_per_participant).toFixed(1)}" `
        + `cy="${y(p.rate).toFixed(1)}" r="${mine ? 6 : 5}"/></g>`);
    });
  out.push("</svg>");
  document.getElementById("vacBridgeChart").innerHTML = out.join("");

  // The pooled figure is the least informative way to state this, in both
  // directions, so the note gives the comparison that survives the coverage
  // caveat and the one that does not.
  const worked = corr.by_category.filter(c => c.p != null && c.p < 0.06);
  const didnt = corr.by_category.filter(c => !(c.p != null && c.p < 0.06));
  const list = rows => rows.map(c => c.category).join(" and ");
  // Coefficient and p together, so a marginal result reads as marginal rather
  // than being lumped in with a clear one.
  const detail = rows => rows.map(c =>
    `${c.category} (&rho; = ${c.r.toFixed(2)}, p = ${c.p.toFixed(2)})`).join(" and ");
  const low = corr.tertiles[0], high = corr.tertiles[corr.tertiles.length - 1];

  document.getElementById("vacBridgeNote").innerHTML =
    `Each point is one design category in one SA4. The two datasets are independent — one is the NDIA's `
    + `enrolment and eligibility record, the other a listings platform — and they agree in direction: `
    + `rank correlation <b>&rho; = ${corr.spearman.toFixed(2)}</b> across ${corr.points} points, `
    + `<b>${corr.spearman_excluding_vic.toFixed(2)}</b> with Victoria excluded. In plain terms, the third of the `
    + `market with the most places per participant runs <b>${pct(high.rate, 1)}</b> vacant against `
    + `<b>${pct(low.rate, 1)}</b> for the third with the fewest.`
    + (wr ? `<br><br>The comparison that carries the most weight is <b>within</b> a region: holding the `
      + `SA4 constant and asking which of its categories sit advertised, the correlation rises to `
      + `<b>${wr.r.toFixed(2)}</b> (${wr.points} points across ${wr.regions} regions, p = ${wr.p}). That matters `
      + `because the listing-propensity problem stamped across this whole view is a property of the `
      + `<i>region</i> — a provider base that advertises more inflates every category it holds alike — `
      + `so it cancels when the comparison stays inside one region.` : "")
    + (worked.length && didnt.length
      ? `<br><br>Held the other way it is much weaker. Within a single design category, comparing regions, `
        + `only ${detail(worked)} show the relationship; for ${list(didnt)} it is `
        + `indistinguishable from zero. So this supports reading a high places-per-participant figure as `
        + `genuine slack in a market — it does not support predicting one region's vacancy from its ratio.`
      : "")
    + (here.size ? ` Points in ${g.level === "National" ? "Australia" : g.name} are highlighted.` : "");
}

function renderVacChildren(g) {
  const panel = document.getElementById("vacChildPanel");
  const kids = (CHILDREN.get(g.id) || []).filter(k => VAC.regions[k.id]);
  if (!kids.length) { panel.hidden = true; return; }
  panel.hidden = false;

  const levels = [...new Set(kids.map(k => k.level))];
  if (!levels.includes(vacChildLevel)) vacChildLevel = levels[0];

  document.getElementById("vacLevelSwitch").innerHTML = levels.length > 1
    ? levels.map(l => `<button type="button" data-level="${l}" aria-pressed="${l === vacChildLevel}">${l}</button>`).join("")
    : "";
  document.getElementById("vacLevelSwitch").onclick = e => {
    const btn = e.target.closest("button[data-level]");
    if (!btn) return;
    vacChildLevel = btn.dataset.level;
    vacSort = { key: null, dir: -1 };
    renderVacChildren(g);
  };

  const shown = kids.filter(k => k.level === vacChildLevel);
  document.getElementById("vacChildTitle").textContent =
    `${shown.length} ${vacChildLevel === "State" ? "states and territories" : `${vacChildLevel} regions`} with `
    + `vacancies listed, within ${g.level === "National" ? "Australia" : g.name}`;

  const P = k => VAC.regions[k.id];
  const cols = [
    { key: "name", label: "Region" },
    { key: "places", label: "Vacant<br>places", get: k => P(k).vacant_places },
    { key: "rate", label: "Share of<br>enrolled places", get: k => P(k).rate, format: pctCell },
    { key: "whole", label: "Of that, wholly<br>empty dwellings",
      get: k => shareOf(num(P(k).depth.whole, "places"), P(k).vacant_places), format: pctCell },
    { key: "listings", label: "Listings", get: k => P(k).listings },
  ];

  document.getElementById("vacChildHead").innerHTML = cols.map(c =>
    `<th scope="col" class="sortable" data-key="${c.key}"${vacSort.key === c.key ? ` aria-sort="${vacSort.dir === 1 ? "ascending" : "descending"}"` : ""}>`
    + `${c.label} <span class="sortcue" aria-hidden="true">${vacSort.key === c.key ? (vacSort.dir === 1 ? "▲" : "▼") : "↕"}</span></th>`
  ).join("");

  const rows = [...shown];
  const col = cols.find(c => c.key === vacSort.key);
  if (col) {
    rows.sort((a, b) => {
      if (!col.get) return vacSort.dir * a.name.localeCompare(b.name);
      const p = col.get(a), q = col.get(b);
      if (p == null && q == null) return 0;
      if (p == null) return 1;          // regions with no value sort last either way
      if (q == null) return -1;
      return vacSort.dir * (p - q);
    });
  } else {
    rows.sort((a, b) => P(b).vacant_places - P(a).vacant_places);
  }

  document.getElementById("vacChildBody").innerHTML = rows.map(k =>
    `<tr class="linked" data-id="${encodeURIComponent(k.id)}">`
    + cols.map(c => c.key === "name"
        ? `<td class="region"><a href="${hashFor("vacancy", k.id)}">${k.name}</a></td>`
        : `<td>${(c.format || cell)(c.get(k))}</td>`).join("")
    + `</tr>`).join("");

  document.getElementById("vacChildHead").onclick = e => {
    const th = e.target.closest("th[data-key]");
    if (!th) return;
    const key = th.dataset.key;
    vacSort = (vacSort.key === key) ? { key, dir: -vacSort.dir } : { key, dir: key === "name" ? 1 : -1 };
    renderVacChildren(g);
  };
  document.getElementById("vacChildBody").onclick = e => {
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr[data-id]");
    if (tr) go(decodeURIComponent(tr.dataset.id));
  };
}

function renderVacPrice(p) {
  const panel = document.getElementById("vacPricePanel");
  if (!p.price_bands.length) { panel.hidden = true; return; }
  panel.hidden = false;

  const bands = new Map(VAC.meta.price_bands.map(b => [b.label, b]));
  const money = v => "$" + Math.round(v / 1000) + "k";
  document.getElementById("vacPriceSub").textContent =
    "Quartiles of maximum price per room, set nationally";

  miniBars("vacPriceBars", p.price_bands, {
    value: r => num(r, "vacant_places"),
    label: r => {
      const b = bands.get(r.label);
      const range = b.from == null ? `under ${money(b.to)}`
                  : b.to == null ? `${money(b.from)} and over`
                  : `${money(b.from)}–${money(b.to)}`;
      return `${r.label}<span class="sub">${range}</span>`;
    },
    tip: r => `${r.label} — ${fmt(num(r, "vacant_places"))} vacant places, `
      + `${pct(shareOf(num(r, "whole_places"), num(r, "vacant_places")), 0)} of them a whole empty dwelling`,
    note: r => fmt(num(r, "vacant_places")),
  });
}

function renderVacSuburbs(p) {
  const panel = document.getElementById("vacSuburbPanel");
  if (!p.top_suburbs.length) { panel.hidden = true; return; }
  panel.hidden = false;

  miniBars("vacSuburbBars", p.top_suburbs, {
    value: r => num(r, "vacant_places"),
    label: r => r.suburb,
    tip: r => `${r.suburb} — ${fmt(num(r, "vacant_places"))} vacant places across `
      + `${fmt(num(r, "listings"))} listing${num(r, "listings") === 1 ? "" : "s"}`,
    note: r => fmt(num(r, "vacant_places")),
  });
}

function renderVacNotes(g, p) {
  const meta = VAC.meta;
  const assigned = meta.match.postcode + meta.match.override;
  const notes = [
    ["t-block", "Housing Hub is a listings platform, not a vacancy census.",
     "Only vacancies a provider chose to advertise appear here, and providers list at very different "
     + "rates. Victoria shows <b>17.3%</b> of its enrolled places as vacant against New South Wales' "
     + "<b>6.0%</b> — a gap far too large to be real, and better read as a difference in how much of "
     + "each market advertises here. Compare categories and dwelling types within a region freely; "
     + "compare one region against another only with this in mind."],
    ["t-info", "Whole-dwelling and single-room vacancies are derived, not published.",
     "The export gives a vacancy count and a building type. Where the count reaches the resident "
     + "capacity the building type names, the dwelling is counted as wholly empty; below it, the "
     + "difference is counted as rooms in a dwelling someone already lives in. "
     + `<b>${fmt(num(p.depth.multi_dwelling, "listings"))}</b> listing${num(p.depth.multi_dwelling, "listings") === 1 ? "" : "s"} here `
     + "report more vacancies than the dwelling can hold, which can only mean one listing covering "
     + "several dwellings; those surplus places are kept in a third bucket rather than assigned to either."],
    ["t-care", "Two dates, not one.",
     `Vacancies are as at <b>${meta.as_at}</b>; the enrolled places they are divided by are as at `
     + `<b>${meta.sda_as_at}</b>. Every rate on this page straddles those two months, and a rate is `
     + "suppressed where fewer than 50 enrolled places sit underneath it."],
    ["t-care", "Design category and dwelling features do not predict whole-dwelling vacancy.",
     "It is tempting to read the category and feature charts causally. Fitting a model to the 1,910 "
     + "shared dwellings in this export, once dwelling size and form are held constant, design "
     + "category, onsite overnight assistance, a breakout room and price all lose any independent "
     + "association with whether a vacancy is the whole dwelling. Dwelling size is doing nearly all "
     + "the work. Read those two charts as description, not explanation."],
    ["t-info", "Regions are assigned from postcode and suburb.",
     `The export carries no statistical geography, so each listing is matched to an SA4 through a `
     + `postcode and locality concordance. All <b>${fmt(meta.listings)}</b> listings resolved: `
     + `${fmt(meta.match.suburb)} on an exact suburb and postcode, and ${fmt(assigned)} on the postcode `
     + `alone or a hand-checked correction. Vacancy appears in `
     + `<b>${meta.regions_with_vacancy.SA4}</b> of the 88 SA4 regions.`],
    ["t-care", "No rate below SA4.",
     "Supplement P publishes the dwelling cross-tabs the places derivation needs at SA4 and above "
     + `only, so SA3 pages show counts and the whole-versus-rooms split but no rate. `
     + `${fmt(meta.sa3_unresolved_listings)} listings sit in a locality with no SA3 counterpart in the `
     + "supplement and are counted at SA4 and above only."],
  ];
  document.getElementById("vacNotes").innerHTML = notes.map(([tag, head, body]) =>
    `<div class="note"><span class="note-tag ${tag}">${tag === "t-block" ? "Must read" : tag === "t-care" ? "Caution" : "Method"}</span>`
    + `<p><b>${head}</b> ${body}</p></div>`).join("");
}

boot();
