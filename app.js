/* SDA Market Explorer
   One dataset, one profile component, rendered identically at every level:
   Australia, each state/territory, each SA4, and each SA3. */
"use strict";

/* Both ends of this measure are a problem, so it has four states, not three.
   Below 1.0 a region has fewer places than participants; 1.0 to 1.5 is the
   balanced band; above that, stock has been built past the need recorded
   against it -- High Physical Support has 77 of 88 regions above 1.0 and 49%
   of its places in regions at 3.0 or more, which a "more is better" scale
   reported as uniformly healthy. */
const RATIO_TIGHT = 1.0;   // below this, fewer places than participants
const RATIO_GOOD = 1.5;    // top of the balanced band
const RATIO_HIGH = 2.5;    // beyond this, far past the recorded need

let DATA = null;
let GEO = null;
let BY_ID = new Map();
let CHILDREN = new Map();
let current = null;
let childLevel = null;
let sort = { key: null, dir: -1 };
let substitution = false;
let mapCategory = "Fully Accessible";

/* High Physical Support is defined cumulatively on top of Fully Accessible --
   an HPS dwelling must meet every Fully Accessible requirement plus
   ceiling-hoist provision, 950mm door openings and backup power -- so HPS
   stock can house someone assessed for Fully Accessible. The reverse does not
   hold, and Improved Liveability (sensory and cognitive) and Robust
   (resilience) sit on different axes, so nothing substitutes for them.

   Allowing substitution therefore reports the two as a single pooled
   category: one body of stock against one body of demand. An earlier version
   passed the surplus down as a waterfall instead, which credited Fully
   Accessible without debiting High Physical Support -- so the same places
   backed two comfortable-looking ratios at once, and three of the four
   categories were identical in both readings.

   Pooling counts Fully Accessible stock against High Physical Support need,
   which physically does not work. In this file that never flatters anything:
   no region of the 88 has High Physical Support below 1.0 while the pooled
   figure reads 1.0 or above, because Fully Accessible is short almost
   everywhere and so has no surplus to lend upwards. Pooling is also the more
   conservative of the two -- against the waterfall it moves 14 regions down
   from "far above" to "above" and 7 from "above" to "balanced", and none up.
   Worth re-checking when the numbers move. */
const POOL_NAME = "High Physical Support + Fully Accessible";
const POOL_OF = ["High Physical Support", "Fully Accessible"];

/* The comparable categories the current supply reading is expressed in. */
function categoriesFor() {
  const cs = DATA.meta.comparable_categories;
  return substitution
    ? cs.filter(c => POOL_OF.indexOf(c) < 0).concat([POOL_NAME])
    : cs.slice();
}

/* Every category the table lists, with the pooled row standing where High
   Physical Support would have been. */
function tableCategories() {
  if (!substitution) return DATA.meta.design_categories;
  const out = [];
  for (const c of DATA.meta.design_categories) {
    if (c === POOL_OF[0]) out.push(POOL_NAME);
    else if (c !== POOL_OF[1]) out.push(c);
  }
  return out;
}

/* One category's figures, summed over its members if it is the pool. A
   suppressed member makes the whole total unknown rather than smaller: the
   NDIA publishes small counts as "<11", and adding that as zero would
   understate supply and demand alike. */
function figuresFor(g, c) {
  const members = c === POOL_NAME ? POOL_OF : [c];
  const add = f => members.reduce((t, m) => {
    const v = g.categories[m][f];
    return (t === null || v == null) ? null : t + v;
  }, 0);
  const places = add("enrolled_places");
  const need = add("participants_with_need");
  return {
    enrolled_dwellings: add("enrolled_dwellings"),
    enrolled_places: places,
    participants_with_need: need,
    pipeline_dwellings: add("pipeline_dwellings"),
    pipeline_places: add("pipeline_places"),
    ratio: (places != null && need) ? Math.round(places / need * 1000) / 1000 : null,
  };
}

/* The figures the current view is built from, keyed by the categories of the
   current reading. */
function supplyFor(g) {
  if (!g.has_places) return null;
  const out = {};
  for (const c of categoriesFor()) out[c] = figuresFor(g, c);
  return out;
}

/* ---------- formatting ---------- */
const fmt = v => (v === null || v === undefined) ? null : Math.round(v).toLocaleString("en-AU");
const cell = v => { const s = fmt(v); return s === null ? '<span class="nil">&mdash;</span>' : s; };

function ratioChip(r) {
  if (r === null || r === undefined) return '<span class="nil">&mdash;</span>';
  const cls = r < RATIO_TIGHT ? "r-crit" : r < RATIO_GOOD ? "r-good"
            : r < RATIO_HIGH ? "r-over" : "r-over2";
  // Form as well as number: the glyph carries the verdict where colour cannot,
  // and the two above-band states are told apart by the figure itself.
  const mark = r < RATIO_TIGHT ? "▼" : r < RATIO_GOOD ? "◆" : "▲";
  const label = r < RATIO_TIGHT ? "fewer places than participants"
              : r < RATIO_GOOD ? "balanced"
              : r < RATIO_HIGH ? "above the need recorded against it"
              : "far above the need recorded against it";
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

  // The map is an enhancement, not the point of the page: if its geometry is
  // missing or unreadable the rest of the explorer still works, so this
  // failure is swallowed rather than surfaced.
  try {
    const geo = await fetch("data/sa4-geometry.json");
    if (geo.ok) GEO = await geo.json();
  } catch (err) {
    GEO = null;
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
  wireModeSwitch();
  wireMapCategory();
  window.addEventListener("hashchange", routeFromHash);
  routeFromHash();
}

function routeFromHash() {
  const id = decodeURIComponent(location.hash.replace(/^#/, "")) || "national";
  render(BY_ID.has(id) ? id : "national");
}

function go(id) {
  if (location.hash === "#" + encodeURIComponent(id)) render(id);
  else location.hash = encodeURIComponent(id);
}

/* Re-render while keeping one element where it was on screen. Not scrolling
   is not enough on its own: substitution drops a row from the category table,
   so everything below it moves up by a row's height. */
function inPlace(anchorId, run) {
  const at = () => document.getElementById(anchorId).getBoundingClientRect().top;
  const before = at();
  run();
  const shift = at() - before;
  if (shift) window.scrollBy(0, shift);
}

function wireMapCategory() {
  // Supply mode is shared with the table's toggle, so this re-renders the
  // whole profile rather than just the map -- the two must never disagree.
  document.getElementById("mapModeSwitch").addEventListener("click", e => {
    const btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    substitution = btn.dataset.mode === "substitution";
    inPlace("mapModeSwitch", () => render(current.id));
  });

  document.getElementById("mapSwitch").addEventListener("click", e => {
    const btn = e.target.closest("button[data-cat]");
    if (!btn) return;
    mapCategory = btn.dataset.cat;
    // Only the map changes, but its legend gains and loses rows with the
    // category, which moves the map itself.
    inPlace("mapSwitch", () => renderMap(current));
  });
}

function wireModeSwitch() {
  document.getElementById("modeSwitch").addEventListener("click", e => {
    const btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    substitution = btn.dataset.mode === "substitution";
    inPlace("modeSwitch", () => render(current.id));
  });
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
  // Toggles re-render the profile in place. Jumping to the top is right when
  // the reader has moved to another geography and wrong when they have just
  // changed how the same one is counted.
  const moved = !current || current.id !== id;
  current = BY_ID.get(id);
  const g = current;
  const cats = tableCategories();
  const comparable = categoriesFor();

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

  document.querySelectorAll("#modeSwitch button").forEach(b =>
    b.setAttribute("aria-pressed", String((b.dataset.mode === "substitution") === substitution)));
  document.getElementById("modeSwitch").hidden = !g.has_places;

  const note = document.getElementById("modeNote");
  note.hidden = !(g.has_places && substitution);
  note.innerHTML =
    "<b>A model, not a count.</b> High Physical Support is defined cumulatively on top of Fully "
    + "Accessible, so an HPS dwelling meets the Fully Accessible standard and could house someone "
    + "assessed for it. Here the two are reported as <b>one pooled category</b> &mdash; one body of "
    + "stock against one body of demand &mdash; rather than as a donor and a borrower, which would "
    + "let the same places back two comfortable ratios at once. Improved Liveability and Robust are "
    + "unchanged: nothing substitutes for them. Pooling does count Fully Accessible stock against "
    + "High Physical Support need, which is not physically possible; in this file it never flatters "
    + "a region, because Fully Accessible is short almost everywhere. Every dwelling is still "
    + "<b>enrolled</b> in one category, and SDA payment follows the participant&rsquo;s funded "
    + "category, so this shows physical suitability rather than what a provider would be paid.";

  renderTiles(g);
  renderCategoryTable(g, cats);
  renderChart(g, comparable);
  renderMap(g);
  renderBreakdowns(g);
  renderChildren(g, comparable);
  renderTrend(g);
  renderNotes(g);

  document.getElementById("footNote").textContent =
    `Rows for ${g.level === "National" ? "Australia" : g.name} read from the published `
    + `${g.level === "SA3" ? "SA3" : "SA4"}-level tables of NDIS Supplement P, as at ${DATA.meta.as_at}. `
    + `State and national figures are the NDIA's own published subtotals, which reconcile exactly `
    + `with the sum of their regions.`;
  if (moved) window.scrollTo({ top: 0, behavior: "instant" });
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
  const comparable = new Set(categoriesFor());
  document.getElementById("placesHead").innerHTML =
    substitution ? "Usable<br>places" : "Enrolled<br>places";
  document.getElementById("tableSub").textContent = !g.has_places
    ? "Places are not published below SA4, so no ratio can be formed at SA3"
    : substitution
      ? "High Physical Support and Fully Accessible pooled — one body of stock against one body of demand"
      : "Places are the unit comparable with participants · a dwelling may hold several";

  const rows = cats.map(c => {
    const x = figuresFor(g, c);
    const isComparable = comparable.has(c);
    const blank = !x.enrolled_dwellings && !x.participants_with_need && !x.pipeline_dwellings;
    if (blank && !isComparable) return "";
    return `<tr${isComparable ? "" : ' class="dim"'}>`
      + `<td>${c}${isComparable ? "" : '<div style="font-weight:400;font-size:11.5px;color:var(--ink-3)">no eligibility decisions issued</div>'}</td>`
      + `<td>${cell(x.enrolled_dwellings)}</td>`
      + `<td>${g.has_places ? cell(x.enrolled_places) : '<span class="nil">n/p</span>'}</td>`
      + `<td>${cell(x.participants_with_need)}</td>`
      + `<td>${g.has_places ? ratioChip(x.ratio) : '<span class="nil">&mdash;</span>'}</td>`
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

  const rows = comparable.map(c => ({ name: c, ...figuresFor(g, c) }));

  document.getElementById("chartLegend").innerHTML = [
    ['<i class="swatch" style="background:var(--accent)"></i>',
      substitution ? "Usable places" : "Enrolled places"],
    ['<i class="swatch" style="background:var(--demand)"></i>', "Participants with need"],
    ['<i class="swatch" style="background:var(--accent);opacity:.34"></i>', "Pipeline places"],
  ].map(([sw, label]) => `<span>${sw}${label}</span>`).join("");

  document.querySelector("#chartPanel .panel-sub").textContent = substitution
    ? "Shared scale · High Physical Support and Fully Accessible pooled into one category"
    : "Shared scale · pipeline shown lighter, as an intention rather than supply";
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
    const placesLine = line("Places", "bar-supply", r.enrolled_places,
      `${r.name} — ${fmt(r.enrolled_places) || 0} places from ${fmt(r.enrolled_dwellings) || 0} dwellings`);
    return `<div class="gap-row">
      <div class="gap-label"><span class="gap-name">${r.name}</span>${ratioChip(r.ratio)}</div>
      <div class="bars">
        ${placesLine}
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
      get: s => (supplyFor(s) || {})[c]?.ratio ?? null
    })) : []),
  ];

  document.getElementById("childHead").innerHTML = cols.map(c =>
    `<th scope="col" class="sortable" data-key="${c.key}"${sort.key === c.key ? ` aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : ""}>`
    + `${c.label} <span class="sortcue" aria-hidden="true">${sort.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span></th>`
  ).join("");

  const rows = [...shown];
  // The pooled column appears and disappears with the toggle, so a sort key
  // can outlive its column.
  if (sort.key && !cols.some(c => c.key === sort.key)) sort = { key: null, dir: -1 };
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

/* ---------- map ---------- */

/* Diverging, because both ends are a problem. Below 1.0 a region has fewer
   places than participants; far above it, stock has been built well past the
   need recorded against it. A red-to-green scale treats more as always
   better, which paints High Physical Support -- where 49% of places sit in
   regions at 3.0 or above, and in real markets rather than tiny ones -- as
   uniformly healthy.

   1.5 and 2.5 are where the mass actually sits. Of the 88 regions, High
   Physical Support puts 29 between them and 35 above, and Robust 15 and 24,
   while Fully Accessible and Improved Liveability barely reach the band.
   Breaks are fixed across the four categories so the maps stay comparable.

   Note these are not ratioChip()'s cuts: the chips still read 1.25 and over
   as simply good. */
const MAP_BREAKS = [0.5, 0.75, RATIO_TIGHT, RATIO_GOOD, RATIO_HIGH];

/* Which capital is worth an inset. Hobart, Darwin and Canberra are a single
   SA4 each, so an inset would show nothing the main map does not. */
const STATE_INSET = { NSW: "Greater Sydney", VIC: "Greater Melbourne",
                      QLD: "Greater Brisbane", WA: "Greater Perth",
                      SA: "Greater Adelaide" };

const MAP_DEFS =
  '<svg class="m-defs" aria-hidden="true">'
  + '<defs><pattern id="mapNil" width="7" height="7" patternUnits="userSpaceOnUse"'
  + ' patternTransform="rotate(45)">'
  + '<rect width="7" height="7" fill="var(--map-nil-bg)"/>'
  + '<line x1="0" y1="0" x2="0" y2="7" stroke="var(--map-nil-ink)" stroke-width="2"/>'
  + '</pattern></defs></svg>';

function mapClass(r) {
  if (r === null || r === undefined) return "m-nil";
  let i = 0;
  while (i < MAP_BREAKS.length && r >= MAP_BREAKS[i]) i++;
  return "m" + (i + 1);
}

/* Bounds of a set of already-projected paths. A state map is a crop of the
   national geometry rather than a second copy of it, which is why the file
   carries one national view and five insets and nothing per state. */
const boxCache = new Map();
function pathBox(key, ds) {
  if (boxCache.has(key)) return boxCache.get(key);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const d of ds) {
    const re = /(-?[\d.]+),(-?[\d.]+)/g;
    let m;
    while ((m = re.exec(d))) {
      const x = +m[1], y = +m[2];
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  const pad = Math.max(x1 - x0, y1 - y0) * 0.05;
  const box = [x0 - pad, y0 - pad, x1 - x0 + pad * 2, y1 - y0 + pad * 2]
    .map(n => n.toFixed(1)).join(" ");
  boxCache.set(key, box);
  return box;
}

function renderMap(g) {
  const panel = document.getElementById("mapPanel");
  // SA3 carries no places and so no ratio -- there is nothing to colour.
  if (!GEO || !GEO.views || g.level === "SA3") { panel.hidden = true; return; }
  panel.hidden = false;

  const cats = categoriesFor();
  // The pooled category exists only in one reading, so a selection can go
  // stale when the toggle moves.
  if (cats.indexOf(mapCategory) < 0) {
    mapCategory = substitution ? POOL_NAME : "Fully Accessible";
  }
  const cat = mapCategory;
  const scope = g.level === "National" ? null : g.state;
  const nat = GEO.views.national;
  const inScope = id => !scope || (BY_ID.get(id) || {}).state === scope;

  const ratioOf = id => {
    const r = BY_ID.get(id);
    const s = r && supplyFor(r);
    return s && s[cat] ? s[cat].ratio : null;
  };

  /* An anchor rather than a click handler: that gives keyboard focus, the
     screen-reader name and the deep link for free, and hashchange already
     routes it. */
  const region = (id, d) => {
    if (!inScope(id)) return '<path class="m-out" d="' + d + '"/>';
    const r = BY_ID.get(id);
    const v = ratioOf(id);
    const x = r.categories[cat] || {};
    const verdict = v === null ? "no ratio — no places and no identified need"
      : v < RATIO_TIGHT ? "fewer places than participants"
      : v < 1.5 ? "balanced"
      : v < RATIO_HIGH ? "more places than participants"
      : "far more places than the need recorded against them";
    return '<a class="m-a' + (id === g.id ? " m-here" : "") + '"'
      + ' href="#' + encodeURIComponent(id) + '">'
      + "<title>" + r.name + " — "
      + (v === null ? "" : v.toFixed(2) + " places per participant · ")
      + verdict + " · " + (fmt(x.enrolled_places) || "not disclosed")
      + " places, " + (fmt(x.participants_with_need) || "not disclosed")
      + " participants</title>"
      + '<path class="' + mapClass(v) + '" d="' + d + '"/></a>';
  };

  const draw = (view, box, label) => {
    const out = ['<svg viewBox="' + box + '" role="img" aria-label="' + label + '">'];
    for (const id in view.regions) out.push(region(id, view.regions[id]));
    out.push('<path class="m-mesh" d="' + view.mesh + '"/></svg>');
    return out.join("");
  };

  const ids = Object.keys(nat.regions).filter(inScope);
  const vals = ids.map(ratioOf);
  const known = vals.filter(v => v !== null).length;
  const short = vals.filter(v => v !== null && v < RATIO_TIGHT).length;
  const over = vals.filter(v => v !== null && v >= RATIO_HIGH).length;
  const where = scope || "Australia";
  // known can be short of the region count: a region with neither places nor
  // need has no ratio, and must not be counted as though it had one.
  const label = cat + ", places per participant by SA4 region. " + short + " of the "
    + known + " regions with a ratio in " + where
    + " have fewer places than participants with an identified need"
    + (substitution ? ", allowing substitution" : "") + ". "
    + over + " sit at " + RATIO_HIGH.toFixed(2) + " or above.";

  document.getElementById("mapMain").innerHTML = MAP_DEFS + draw(
    nat, scope ? pathBox(scope, ids.map(i => nat.regions[i]))
               : "0 0 " + nat.width + " " + nat.height, label);

  const insets = scope
    ? (STATE_INSET[scope] ? [STATE_INSET[scope]] : [])
    : Object.keys(STATE_INSET).map(k => STATE_INSET[k]);
  document.getElementById("mapInsets").innerHTML = insets.map(name => {
    const v = GEO.views["gccsa:" + name];
    if (!v) return "";
    return '<figure class="map-inset">'
      + draw(v, "0 0 " + v.width + " " + v.height, name + ", " + cat)
      + "<figcaption>" + name.replace("Greater ", "") + "</figcaption></figure>";
  }).join("");

  document.getElementById("mapSwitch").innerHTML =
    cats.map(c =>
      '<button type="button" data-cat="' + c + '" aria-pressed="'
      + (c === cat) + '">' + (c === POOL_NAME ? "HPS + Fully Accessible" : c)
      + "</button>").join("");

  /* The same toggle as the table above, repeated here because the table is
     usually scrolled off screen by the time the map is in view. */
  document.getElementById("mapModeSwitch").innerHTML =
    [["enrolled", "As enrolled"], ["substitution", "Allowing substitution"]].map(
      m => '<button type="button" data-mode="' + m[0] + '" aria-pressed="'
        + ((m[0] === "substitution") === substitution) + '">' + m[1] + "</button>").join("");

  /* Say so when the toggle cannot change this map: nothing substitutes for
     Improved Liveability or Robust, and silence reads as a broken control. */
  const inert = document.getElementById("mapModeNote");
  inert.hidden = !substitution || cat === POOL_NAME;
  inert.textContent = inert.hidden ? "" :
    "Substitution does not change this map: nothing substitutes for " + cat
    + ". Only High Physical Support and Fully Accessible combine, and they do so "
    + "as a single pooled category.";

  document.getElementById("mapSub").textContent =
    (substitution ? "Allowing substitution" : "As enrolled") + " · "
    + (scope ? where + ", " + ids.length + " regions"
             : "all " + ids.length + " SA4 regions")
    + " · click a region to open it";

  const sw = c => '<span class="' + c + '"></span>';
  document.getElementById("mapLegend").innerHTML =
    '<div class="mrow"><i class="g-crit">▼</i><span class="msw">'
    + sw("m1") + sw("m2") + sw("m3") + "</span><span>fewer places than participants</span>"
    + '<span class="mticks">under 1.00</span></div>'
    + '<div class="mrow"><i class="g-good">◆</i><span class="msw">' + sw("m4")
    + "</span><span>balanced</span>"
    + '<span class="mticks">1.00 – 1.50</span></div>'
    + '<div class="mrow"><i class="g-over">▲</i><span class="msw">'
    + sw("m5") + sw("m6")
    + "</span><span>above the need recorded against it</span>"
    + '<span class="mticks">1.50 – 2.50, then 2.50 and over</span></div>'
    // Only worth a legend row when something in view actually uses it.
    + (vals.some(v => v === null)
        ? '<div class="mrow"><i></i><span class="msw">' + sw("m-nil")
          + "</span><span>no ratio — no places and no identified need</span></div>"
        : "");

  const tot = BY_ID.get("national").totals;
  const miss = tot.need_without_category, all = tot.participants_with_need;
  document.getElementById("mapNote").innerHTML =
    "<b>Colour shows the ratio, not the size of the market.</b> A region with four "
    + "participants and one with nine hundred can read the same; open a region for the counts "
    + "behind it. And the ratio is a mismatch of <b>mix</b>, not a waiting list — a "
    + "participant assessed for one category but housed in another appears on both sides, in "
    + "different categories. " + (miss && all
      ? "A further <b>" + fmt(miss) + "</b> of " + fmt(all) + " participants ("
        + (miss / all * 100).toFixed(1) + "%) have no design category recorded, so no "
        + "category-specific map can place them at all."
      : "");
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

boot();
