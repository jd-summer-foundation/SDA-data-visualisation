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
/* The surplus view reads every design category at once by default: the
   question it answers is "how much stock is standing spare here", and that is
   a total before it is a breakdown. */
const SURPLUS_ALL = "__all";

const RATIO_TIGHT = 1.0;   // below this, fewer places than participants
const RATIO_GOOD = 1.5;    // top of the balanced band
const RATIO_HIGH = 2.5;    // beyond this, far past the recorded need

let DATA = null;
let VAC = null;                       // loaded on first entry to the vacancy view
let GEO = null;
let BY_ID = new Map();
let CHILDREN = new Map();
let current = null;
let view = "supply";
let childLevel = null;
let vacChildLevel = null;
let sort = { key: null, dir: -1 };
let vacSort = { key: null, dir: -1 };
let substitution = false;
let mapCategory = "Fully Accessible";
let heatSort = { key: null, dir: -1 };
/* Whether the band tally weights each region by the participants it holds.
   Weighted by default: a region is not a person, and counting each once
   whatever its size is the reading that needs justifying, not this one. */
let bandWeighted = true;
/* Which states in the region grid are open. Eighty-eight SA4 rows is more
   than a reader can hold at once, and the state rows carry the NDIA's own
   subtotals, so the grid opens as eight readable rows and the regions are
   expanded a state at a time. */
let heatExpanded = new Set();

/* Surplus view state. The threshold is a tolerance, not a target: a region is
   only counted as holding surplus once it is this far past its own recorded
   need, so the figure is not moved by a region sitting a place or two over. */
let surplusThreshold = 1.05;
let surplusCategory = SURPLUS_ALL;
let surplusSort = { key: null, dir: -1 };
let surplusExpanded = new Set();

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

/* A geography's enrolled places over every design category, not only the
   comparable ones -- the whole resident capacity that sits behind its
   dwellings. Totals carry dwellings but not places, so it is summed from the
   categories, and the tiles and the SA4 grid read it from here so neither can
   report a different capacity for the same region. */
function totalPlaces(g) {
  if (!g.has_places) return null;
  return DATA.meta.design_categories
    .reduce((sum, c) => sum + (g.categories[c].enrolled_places || 0), 0);
}

/* The figures the current view is built from, keyed by the categories of the
   current reading. */
function supplyFor(g) {
  if (!g.has_places) return null;
  const out = {};
  for (const c of categoriesFor()) out[c] = figuresFor(g, c);
  return out;
}


/* ---------- surplus ---------- */

/* A ratio says whether a region is long or short; it cannot say by how much,
   because it has no units. 4.22 places per participant in Geelong High
   Physical Support is the same number whether it stands for four spare places
   or four hundred. This section converts the long end of that measure into the
   unit the question "what is the plan for existing surplus SDA?" is actually
   asked in: dwellings standing past the need recorded against them.

   Three deliberate choices, each of which understates rather than overstates:

   1. A tolerance, not a target. Surplus is measured past THRESHOLD x need, not
      past need itself, so a region carrying a few places of headroom is not
      reported as holding surplus stock. 1.05 and 1.20 are offered; 1.05 is the
      default because it is the weaker claim of the two, and anything it does
      not clear is not worth arguing about.

   2. Substitution is directional and the donor is debited. High Physical
      Support is defined cumulatively on top of Fully Accessible, so HPS stock
      can cover an FA shortfall -- and when it does, those places stop being
      HPS surplus. That is the difference between this and the waterfall
      removed from the supply view: here the borrowed places are subtracted
      from the lender, so the same place cannot be spare and in use at once.
      Fully Accessible cannot substitute upwards, and nothing substitutes for
      Improved Liveability or Robust, so those three are read on their own.
      Across the pooled pair the total is identical to the supply view's
      pooling; the waterfall only decides which category it is booked against.

   3. Dwellings are approximated. The supplement publishes places against
      participants and dwellings against nothing, so the only bridge between
      them is the region's own average -- its enrolled places divided by its
      enrolled dwellings, in that category. Surplus places are divided by that
      average and rounded DOWN. */

const SURPLUS_THRESHOLDS = [[1.05, "5% over need"], [1.2, "20% over need"]];
/* Grid order, and the order of the map's category buttons: the two
   substituting categories adjacent, so a row can be read across. */
const SURPLUS_ORDER = ["Improved Liveability", "High Physical Support",
                       "Fully Accessible", "Robust"];
const SURPLUS_BREAKS = [1, 10, 25, 50, 100];

/* Places per dwelling for one category, from the smallest geography that
   publishes both. A region with places but no dwellings recorded in a category
   falls back to its state and then to Australia rather than dropping out: the
   average is a conversion factor, not a finding, and a coarser one is better
   than none. */
function placesPerDwelling(g, c) {
  for (let n = g; n; n = n.parent ? BY_ID.get(n.parent) : null) {
    const x = n.categories && n.categories[c];
    if (x && x.enrolled_dwellings && x.enrolled_places) {
      return x.enrolled_places / x.enrolled_dwellings;
    }
  }
  return null;
}

/* The total row of a surplus record: the four categories added up. A
   suppressed category is skipped rather than counted as zero, and the record
   says so, because a total quietly missing a member is the one number here
   that could be read as complete when it is not. */
function surplusTotal(rec) {
  let dwellings = 0, excess = 0, known = 0, partial = 0;
  for (const c of SURPLUS_ORDER) {
    const x = rec[c];
    if (!x || x.dwellings === null) { partial++; continue; }
    dwellings += x.dwellings;
    excess += x.excess_places;
    known++;
  }
  return { dwellings: known ? dwellings : null, excess_places: known ? excess : null,
           partial, lent: rec[POOL_OF[0]] ? rec[POOL_OF[0]].lent : 0 };
}

/* One geography's surplus, by category, at the current threshold and reading.
   Null propagates exactly as it does in figuresFor(): the NDIA publishes small
   counts as "<11", and reading that as zero on the demand side would invent
   surplus that may not exist. */
function surplusFor(g, T = surplusThreshold) {
  if (!g.has_places) return null;
  const at = c => (g.categories && g.categories[c]) || {};

  /* What High Physical Support is asked to cover before any of it counts as
     spare. Only when substitution is allowed -- read as enrolled, each
     category answers for its own need alone. */
  let owed = 0;
  if (substitution) {
    const x = at(POOL_OF[1]);
    owed = (x.enrolled_places == null || x.participants_with_need == null)
      ? null
      : Math.max(0, T * x.participants_with_need - x.enrolled_places);
  }

  const rec = {};
  for (const c of SURPLUS_ORDER) {
    const lent = (c === POOL_OF[0]) ? owed : 0;
    const x = at(c);
    const excess = (lent === null || x.enrolled_places == null || x.participants_with_need == null)
      ? null
      : Math.max(0, x.enrolled_places - T * x.participants_with_need - lent);
    const ppd = placesPerDwelling(g, c);
    rec[c] = {
      excess_places: excess,
      places_per_dwelling: ppd,
      dwellings: (excess === null || !ppd) ? null : Math.floor(excess / ppd),
      lent: lent || 0,
    };
  }
  rec.total = surplusTotal(rec);
  return rec;
}

/* Surplus summed over a set of regions. State and national rows are built this
   way rather than from the NDIA's own subtotals, which the rest of the site
   uses: surplus is regional by definition, and a subtotal would net a shortfall
   in one region against a surplus in another and report the difference as
   though nowhere were short. */
function surplusAgg(recs) {
  const rec = {};
  for (const c of SURPLUS_ORDER) {
    let dwellings = 0, excess = 0, lent = 0, known = 0, partial = 0;
    for (const r of recs) {
      const x = r && r[c];
      if (!x || x.dwellings === null) { partial++; continue; }
      dwellings += x.dwellings;
      excess += x.excess_places;
      lent += x.lent;
      known++;
    }
    rec[c] = { dwellings: known ? dwellings : null, excess_places: known ? excess : null,
               places_per_dwelling: null, lent, partial };
  }
  rec.total = surplusTotal(rec);
  rec.total.partial = SURPLUS_ORDER.reduce((n, c) => n + (rec[c].partial || 0), 0);
  return rec;
}

/* The categories the surplus panels show: the published comparable ones, in
   the grid's order. Fully Accessible keeps its own column even when
   substitution is on -- it is where the reader looks to see what High Physical
   Support has just been made to cover. */
const surplusCats = () => SURPLUS_ORDER.filter(c =>
  DATA.meta.comparable_categories.indexOf(c) >= 0);

/* Six classes on one ramp. Zero is its own class and reads as near-blank, so
   the regions holding stock are the only thing on the map with colour in it. */
function surplusClass(v) {
  if (v === null || v === undefined) return "m-nil";
  let i = 0;
  while (i < SURPLUS_BREAKS.length && v >= SURPLUS_BREAKS[i]) i++;
  return "s" + i;
}

/* ---------- formatting ---------- */
const fmt = v => (v === null || v === undefined) ? null : Math.round(v).toLocaleString("en-AU");
const cell = v => { const s = fmt(v); return s === null ? '<span class="nil">&mdash;</span>' : s; };

const pct = (v, dp = 1) =>
  (v === null || v === undefined) ? null : (v * 100).toFixed(dp) + "%";
const pctCell = v => pct(v) ?? '<span class="nil">&mdash;</span>';

/* The four states of the measure, in one place. Chips, heat cells, the map
   and the band tally all read from here, so none of them can come to describe
   the same cut differently. Form as well as colour: the glyph carries the
   verdict where colour cannot, and the two above-band states are told apart by
   the figure itself. `swatch` is the map class that stands for the band where
   one colour has to represent it -- the map subdivides "under" three ways, and
   m2 is its middle. */
const RATIO_BANDS = [
  { short: "Under",    mark: "▼", chip: "r-crit",  swatch: "m2",
    label: "fewer places than participants" },
  { short: "Balanced", mark: "◆", chip: "r-good",  swatch: "m4",
    label: "balanced" },
  { short: "Over",     mark: "▲", chip: "r-over",  swatch: "m5",
    label: "above the need recorded against it" },
  { short: "Far over", mark: "▲", chip: "r-over2", swatch: "m6",
    label: "far above the need recorded against it" },
];
const NO_RATIO = "no ratio — no places and no identified need";

const ratioBand = r => r < RATIO_TIGHT ? 0 : r < RATIO_GOOD ? 1 : r < RATIO_HIGH ? 2 : 3;
const ratioLabel = r => RATIO_BANDS[ratioBand(r)].label;
const ratioMark = r => RATIO_BANDS[ratioBand(r)].mark;

function ratioChip(r) {
  if (r === null || r === undefined) return '<span class="nil">&mdash;</span>';
  const b = RATIO_BANDS[ratioBand(r)];
  return `<span class="ratio ${b.chip}" title="${r.toFixed(2)} places per participant — ${b.label}">`
       + `<i aria-hidden="true">${b.mark}</i>${r.toFixed(2)}<span class="sr-only"> — ${b.label}</span></span>`;
}

/* Sortable header cells. Shared so a second table cannot quietly lose the
   aria-sort or the cue. */
function headCells(cols, st) {
  return cols.map(c =>
    `<th scope="col" class="sortable" data-key="${c.key}"`
    + (st.key === c.key ? ` aria-sort="${st.dir === 1 ? "ascending" : "descending"}"` : "") + ">"
    + `${c.label} <span class="sortcue" aria-hidden="true">`
    + `${st.key === c.key ? (st.dir === 1 ? "▲" : "▼") : "↕"}</span></th>`).join("");
}

/* Regions with no value sort last regardless of direction: a region without a
   ratio is unknown, not smallest. */
function rowCompare(col, dir) {
  return (a, b) => {
    if (!col.get) return dir * a.name.localeCompare(b.name);
    const x = col.get(a), y = col.get(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return dir * (x - y);
  };
}

/* "<State> - Other" rows exist for participants whose region is unknown; drop
   them where they carry nothing, but keep them where they hold real counts. */
const hasData = k => (k.totals.enrolled_dwellings || 0) > 0
                  || (k.totals.participants_with_need || 0) > 0;

/* The enrolled/substitution toggle is repeated beside the category table and
   the map: a reader deep in the page should not have to scroll back to the top
   to change the reading. Both are the one piece of state, so they are built and
   wired from here and cannot come to disagree. The region grid carries no
   switch -- it shows both readings as columns instead. */
const MODES = [["enrolled", "As enrolled"], ["substitution", "Allowing substitution"]];
const MODE_SWITCHES = ["modeSwitch", "mapModeSwitch", "surModeSwitch"];
const modeButtons = () => MODES.map(([mode, label]) =>
  `<button type="button" data-mode="${mode}" aria-pressed="`
  + `${(mode === "substitution") === substitution}">${label}</button>`).join("");

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
  wireViewSwitch();
  wireModeSwitch();
  wireMapCategory();
  wireBandSwitch();
  wireSurplusSwitches();
  window.addEventListener("hashchange", routeFromHash);
  routeFromHash();
}

/* The hash is either a bare geography id — every link ever published — or
   "<view>!<id>". Splitting on the first "!" keeps the old links working, and
   ids may themselves contain colons ("sa4:VIC - Geelong"). */
const VIEWS = new Set(["supply", "vacancy", "surplus"]);

function parseHash() {
  const raw = decodeURIComponent(location.hash.replace(/^#/, ""));
  const cut = raw.indexOf("!");
  const name = cut === -1 ? "supply" : raw.slice(0, cut);
  const id = cut === -1 ? raw : raw.slice(cut + 1);
  return { view: VIEWS.has(name) ? name : "supply", id: id || "national" };
}

// Supply is the bare id, so every link ever published still opens where it did.
const hashFor = (name, id) =>
  "#" + (name === "supply" ? "" : name + "!") + encodeURIComponent(id);

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
  for (const id of MODE_SWITCHES) {
    document.getElementById(id).addEventListener("click", e => {
      const btn = e.target.closest("button[data-mode]");
      if (!btn) return;
      substitution = btn.dataset.mode === "substitution";
      // Every panel is re-read, not just the one holding the button: supply
      // mode is shared, and two panels disagreeing about it would be a lie.
      inPlace(id, () => render(current.id));
    });
  }
}

/* Unlike the supply-mode switches above, this one is local to its own panel --
   it changes how the tally is counted, not what the page is reading -- so it
   re-renders that panel alone and leaves the rest of the profile untouched. */
function wireBandSwitch() {
  document.getElementById("bandModeSwitch").addEventListener("click", e => {
    const btn = e.target.closest("button[data-band]");
    if (!btn) return;
    bandWeighted = btn.dataset.band === "weighted";
    inPlace("bandModeSwitch", () => renderBands(current));
  });
}


/* The surplus view's own controls. The threshold switch is repeated on both of
   its panels for the same reason the supply-mode switch is repeated on the
   supply view's: a reader at the bottom of eighty-eight rows should not have
   to scroll back to the top to change it. Both write the one variable. */
const SURPLUS_THRESH_SWITCHES = ["surThreshSwitch", "surGridThreshSwitch"];
function wireSurplusSwitches() {
  for (const id of SURPLUS_THRESH_SWITCHES) {
    document.getElementById(id).addEventListener("click", e => {
      const btn = e.target.closest("button[data-thresh]");
      if (!btn) return;
      surplusThreshold = +btn.dataset.thresh;
      inPlace(id, () => renderSurplus(current));
    });
  }
  document.getElementById("surMapSwitch").addEventListener("click", e => {
    const btn = e.target.closest("button[data-cat]");
    if (!btn) return;
    surplusCategory = btn.dataset.cat;
    // Only the map changes, but its legend can gain and lose the hatch row,
    // which moves the map itself.
    inPlace("surMapSwitch", () => renderSurplusMap(current));
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
  renderChrome(current);

  document.querySelectorAll("#viewSwitch button").forEach(btn =>
    btn.setAttribute("aria-pressed", String(btn.dataset.view === view)));
  document.getElementById("viewSupply").hidden = view !== "supply";
  document.getElementById("viewVacancy").hidden = view !== "vacancy";
  document.getElementById("viewSurplus").hidden = view !== "surplus";

  if (view === "surplus") {
    renderSurplus(current);
  } else if (view === "vacancy") {
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
  if (moved) window.scrollTo({ top: 0, behavior: "instant" });
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
  const cats = tableCategories();
  const comparable = categoriesFor();

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
  renderHeat(g);
  renderBands(g);
  renderNotes(g);

  document.getElementById("footNote").textContent =
    `Rows for ${g.level === "National" ? "Australia" : g.name} read from the published `
    + `${g.level === "SA3" ? "SA3" : "SA4"}-level tables of NDIS Supplement P, as at ${DATA.meta.as_at}. `
    + `State and national figures are the NDIA's own published subtotals, which reconcile exactly `
    + `with the sum of their regions.`;
}

function renderTiles(g) {
  const t = g.totals;
  const places = totalPlaces(g);
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

  document.getElementById("childHead").innerHTML = headCells(cols, sort);

  const rows = [...shown];
  // The pooled column appears and disappears with the toggle, so a sort key
  // can outlive its column.
  if (sort.key && !cols.some(c => c.key === sort.key)) sort = { key: null, dir: -1 };
  if (sort.key) {
    rows.sort(rowCompare(cols.find(c => c.key === sort.key), sort.dir));
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

/* One legend for the scale, shared by the map and the heatmap below it. The
   two panels colour the same measure on the same breaks, so a second copy of
   this markup would only be a way for them to drift apart. */
function ratioLegend(showNil) {
  const sw = c => '<span class="' + c + '"></span>';
  return '<div class="mrow"><i class="g-crit">▼</i><span class="msw">'
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
    + (showNil
        ? '<div class="mrow"><i></i><span class="msw">' + sw("m-nil")
          + "</span><span>" + NO_RATIO + "</span></div>"
        : "");
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
    const verdict = v === null ? NO_RATIO : ratioLabel(v);
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

  document.getElementById("mapModeSwitch").innerHTML = modeButtons();

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

  document.getElementById("mapLegend").innerHTML = ratioLegend(vals.some(v => v === null));

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

/* ---------- supply heatmap ---------- */

/* A cell of the heatmap: the ratio's own colour behind the figure, rather than
   a chip's tint. Eighty-eight rows of tinted pills read as a pale wash; the
   full fill is what makes a column of short regions visible at a glance. */
function heatCell(r) {
  if (r === null || r === undefined)
    return `<td class="hc m-nil" title="${NO_RATIO}"><span class="sr-only">${NO_RATIO}</span></td>`;
  const label = ratioLabel(r);
  return `<td class="hc ${mapClass(r)}" title="${r.toFixed(2)} places per participant — ${label}">`
       + `<i aria-hidden="true">${ratioMark(r)}</i>${r.toFixed(2)}`
       + `<span class="sr-only"> — ${label}</span></td>`;
}

/* The grid reads every comparable category and the pooled column at once,
   rather than following the page's enrolled/substitution switch. The question
   it exists to answer -- can High Physical Support stock cover the Fully
   Accessible shortfall in this region? -- is a comparison between the two
   readings, so putting one of them behind a toggle is the one thing that makes
   it unanswerable. HPS, FA and the pool therefore sit side by side, out of the
   order the rest of the page uses, so all three can be read across a row.

   Spelled out, those three headers are eleven words over a grid that already
   scrolls sideways, so they are labelled by acronym, expanded in each header's
   own title and in the note under the grid. */
const HEAT_COLS = [
  { cat: "Improved Liveability", label: "Improved<br>Liveability" },
  { cat: "High Physical Support", label: abbrLabel("HPS", "High Physical Support") },
  { cat: "Fully Accessible", label: abbrLabel("FA", "Fully Accessible") },
  { cat: POOL_NAME, label: abbrLabel("HPS+FA", POOL_NAME + ", pooled") },
  { cat: "Robust", label: "Robust" },
];
function abbrLabel(short, full) {
  return `<abbr title="${full}">${short}</abbr>`;
}

/* The map reads one design category at a time and the region table one level
   at a time, so neither shows a category running short across the country
   while another runs long in the same places. This grid puts every SA4
   against every comparable category at once.

   It is coloured on the map's own six-class scale rather than the chips',
   for two reasons: the two panels then cannot tell different stories about
   the same number, and a chip's tint is light enough that eighty-eight rows
   of them read as a pale wash rather than a pattern. The full fill is what
   makes a short column or a long region visible without reading a figure.

   Regions sit under their state, and the state row carries the NDIA's own
   published subtotals -- not an average of the regions beneath it, which
   would weight a four-participant region equally with a nine-hundred one. */
/* The SA4s the reader's position puts in view, under their states: nationally
   every region, and below that the regions of the state they are in, so a
   region can be read against its peers. Shared by the grid and the tally
   beneath it, which must always be counting the same regions. */
function sa4Groups(g) {
  const scope = g.level === "National" ? null : g.state;
  return (CHILDREN.get("national") || [])
    .filter(st => !scope || st.state === scope)
    .map(st => ({
      state: st,
      kids: (CHILDREN.get(st.id) || []).filter(k => k.level === "SA4" && hasData(k)),
    }))
    .filter(gr => gr.kids.length);
}

function renderHeat(g) {
  const panel = document.getElementById("heatPanel");
  const scope = g.level === "National" ? null : g.state;
  const groups = sa4Groups(g);
  if (!groups.length) { panel.hidden = true; return; }
  panel.hidden = false;

  // Ratios are read straight from the figures rather than through the page's
  // current reading, which covers only one of these columns at a time.
  const pub = DATA.meta.comparable_categories;
  const cols = [
    { key: "name", label: "Region" },
    { key: "places", label: "Enrolled<br>places", get: totalPlaces },
    { key: "need", label: "Participants<br>with need", get: s => s.totals.participants_with_need },
    ...HEAT_COLS
      .filter(c => c.cat === POOL_NAME || pub.indexOf(c.cat) >= 0)
      .map(c => ({
        key: c.cat, label: c.label, heat: true,
        get: s => s.has_places ? figuresFor(s, c.cat).ratio : null,
      })),
  ];

  // A sort key can outlive its column if the published categories change.
  if (heatSort.key && !cols.some(c => c.key === heatSort.key)) heatSort = { key: null, dir: -1 };
  const cmp = heatSort.key
    ? rowCompare(cols.find(c => c.key === heatSort.key), heatSort.dir)
    : (a, b) => (totalPlaces(b) || 0) - (totalPlaces(a) || 0);
  // Sorting orders the regions inside each state and the states against each
  // other, on the state's own figure. Grouping is the point of the panel, so a
  // sort rearranges it rather than dissolving it.
  groups.forEach(gr => gr.kids.sort(cmp));
  groups.sort((a, b) => cmp(a.state, b.state));

  const regions = groups.reduce((n, gr) => n + gr.kids.length, 0);
  document.getElementById("heatTitle").textContent =
    `${regions} SA4 regions by design category`
    + (scope ? ` in ${groups[0].state.name}` : " across Australia");
  // Scoped to one state its regions are already the rows, so there is nothing
  // to expand and the instruction to do it would be a dead end.
  const one = groups.length === 1;
  document.getElementById("heatSub").textContent =
    "Places per participant · "
    + (one ? "" : "click ▸ to open a state's regions, ")
    + "click a column to sort, a row to open";

  document.getElementById("heatHead").innerHTML = headCells(cols, heatSort);

  const dataCells = s => cols.slice(1).map(c =>
    c.heat ? heatCell(c.get(s)) : `<td>${cell(c.get(s))}</td>`).join("");

  const body = document.getElementById("heatBody");
  let anyOpen = false;
  body.innerHTML = groups.map(gr => {
    const id = encodeURIComponent(gr.state.id);
    // Scoped to one state there is nothing to collapse the group in favour of,
    // so the control is not offered and the group cannot be shut.
    const open = one || heatExpanded.has(gr.state.id);
    if (open) anyOpen = true;
    const head =
      `<tr class="grouprow linked" data-id="${id}">`
      + `<td class="region">`
      + (one ? "" : `<button type="button" class="gtoggle" data-state="${id}"`
        + ` aria-expanded="${open}"><span class="sr-only">${open ? "Collapse" : "Expand"} `
        + `${gr.state.name}</span><span aria-hidden="true">${open ? "▾" : "▸"}</span></button>`)
      + `<a href="#${id}">${gr.state.name}</a>`
      + `<span class="gcount">${gr.kids.length} regions</span></td>`
      + dataCells(gr.state) + "</tr>";
    if (!open) return head;
    return head + gr.kids.map(s =>
      `<tr class="linked${s.id === g.id ? " here" : ""}" data-id="${encodeURIComponent(s.id)}">`
      + `<td class="region sa4"><a href="#${encodeURIComponent(s.id)}">${s.name}</a></td>`
      + dataCells(s) + "</tr>").join("");
  }).join("");

  // Closed, the pinned column holds nothing longer than "VIC 17 regions", and
  // the width a full SA4 name needs is width the coloured columns lose.
  document.getElementById("heatTable").classList.toggle("tight", !anyOpen);

  // The hatch is only worth a legend row when something in view actually uses it.
  document.getElementById("heatLegend").innerHTML =
    ratioLegend(!!body.querySelector("td.m-nil"));

  document.getElementById("heatNote").innerHTML =
    "<b>Colour shows the ratio, not the size of the market.</b> A region with four "
    + "participants and one with nine hundred can read the same, which is why the two "
    + "counts the ratio is formed from &mdash; places and participants &mdash; sit beside "
    + "them. Places, not dwellings: a dwelling may hold several, and it is places that are "
    + "the unit comparable with participants. The scale is the map's, on the same breaks, so a cell here "
    + "and a region there are always the same colour for the same figure. "
    + "<b>HPS</b> is High Physical Support and <b>FA</b> is Fully Accessible; "
    + "<b>HPS+FA</b> reports the two as one pooled category &mdash; one body of stock "
    + "against one body of demand &mdash; because an HPS dwelling meets the Fully "
    + "Accessible standard and could house someone assessed for it. It is a model, not a "
    + "count: every dwelling is still enrolled in one category.";

  // The grid scrolls inside its own panel, so a re-render must not throw the
  // reader back to the top of eighty-eight rows.
  const again = () => {
    const wrap = document.getElementById("heatWrap");
    const top = wrap.scrollTop, left = wrap.scrollLeft;
    renderHeat(g);
    wrap.scrollTop = top;
    wrap.scrollLeft = left;
  };

  document.getElementById("heatHead").onclick = e => {
    const th = e.target.closest("th[data-key]");
    if (!th) return;
    const key = th.dataset.key;
    heatSort = (heatSort.key === key) ? { key, dir: -heatSort.dir }
                                      : { key, dir: key === "name" ? 1 : -1 };
    again();
  };
  document.getElementById("heatBody").onclick = e => {
    const tog = e.target.closest("button.gtoggle");
    if (tog) {
      const sid = decodeURIComponent(tog.dataset.state);
      if (heatExpanded.has(sid)) heatExpanded.delete(sid);
      else heatExpanded.add(sid);
      again();
      return;
    }
    if (e.target.closest("a")) return;   // let the link handle its own navigation
    const tr = e.target.closest("tr[data-id]");
    if (tr) go(decodeURIComponent(tr.dataset.id));
  };
}

/* ---------- band tally ---------- */

/* The grid above shows every region against every reading; this counts them.
   It answers the question the grid raises but cannot state -- how widespread
   is this? -- and the answer is not close: Improved Liveability and Fully
   Accessible are short in the large majority of regions, High Physical
   Support long in the large majority, and largely the same regions.

   Rows are the grid's own columns, in the grid's own order, so the two panels
   cannot come to disagree about what is being counted or drift apart in how
   they arrange it. That puts the pooled reading directly beneath the two
   readings it combines, which is where the comparison wants it: pooling takes
   Fully Accessible from short almost everywhere to a genuinely mixed picture,
   while Improved Liveability does not move at all, nothing substituting for
   it. */
function renderBands(g) {
  const panel = document.getElementById("bandPanel");
  const regions = sa4Groups(g).flatMap(gr => gr.kids);
  if (!regions.length) { panel.hidden = true; return; }
  panel.hidden = false;

  /* Counted twice over. A region counts once whichever way it is read, so the
     count answers "how widespread", and a reader is right to wonder whether a
     crowd of small regions is carrying it. Weighting each region by the
     participants it holds in that category answers "how many people", and the
     weight has to be the category's own participants rather than the region's
     total need: Robust is between 1.6% and 20% of a region's need, so a
     region-total weight would misstate that row badly.

     Participants with need is also the denominator of the ratio itself, which
     makes it the natural weight and, unlike general population, something the
     supplement actually publishes per category. No cell of the 352 is
     suppressed and none has need without a ratio, so no participant falls out
     of the tally on the way through. */
  const pub = DATA.meta.comparable_categories;
  const tally = HEAT_COLS
    .filter(c => c.cat === POOL_NAME || pub.indexOf(c.cat) >= 0)
    .map(c => {
      const counts = RATIO_BANDS.map(() => 0);
      const weights = RATIO_BANDS.map(() => 0);
      let nil = 0, nilWeight = 0, need = 0;
      for (const s of regions) {
        const x = s.has_places ? figuresFor(s, c.cat) : { ratio: null, participants_with_need: null };
        const w = x.participants_with_need || 0;
        need += w;
        if (x.ratio === null) { nil++; nilWeight += w; }
        else { counts[ratioBand(x.ratio)]++; weights[ratioBand(x.ratio)] += w; }
      }
      return { cat: c.cat, counts, weights, nil, nilWeight, need };
    });

  const n = regions.length;
  // Whether any region lacks a ratio is a fact about the data rather than about
  // the reading, so the column keeps its place as the toggle moves.
  const anyNil = tally.some(t => t.nil);
  const of = t => t.cat;

  /* The two readings of a row, chosen between rather than shown at once. Each
     weighted row is a share of its OWN category's participants -- the
     denominators differ down the column, which is why the bar caption carries
     each row's total. */
  const reading = t => bandWeighted
    ? { values: t.weights, nilValue: t.nilWeight, total: t.need, unit: "participants" }
    : { values: t.counts, nilValue: t.nil, total: n, unit: "regions" };

  document.getElementById("bandModeSwitch").innerHTML =
    [["weighted", "By participants"], ["regions", "By regions"]].map(([mode, label]) =>
      `<button type="button" data-band="${mode}" aria-pressed="`
      + `${(mode === "weighted") === bandWeighted}">${label}</button>`).join("");

  document.getElementById("bandTitle").textContent = bandWeighted
    ? "How much of the need sits where supply is short, and where it is long"
    : `How many of those ${n} regions are short, and how many are long`;
  document.getElementById("bandSub").textContent =
    (bandWeighted
      ? "Each region weighted by the participants it holds in that category"
      : `Each of the ${n} regions counted once, whatever its size`)
    + " · the same readings and cuts as the grid above";

  document.getElementById("bandHead").innerHTML =
    '<th scope="col">Design category</th>'
    + RATIO_BANDS.map(b =>
        `<th scope="col"><i class="bsw ${b.swatch}" aria-hidden="true"></i>${b.short}</th>`).join("")
    + (anyNil ? '<th scope="col">No ratio</th>' : "")
    + '<th scope="col" class="bdist">Distribution</th>';

  /* The share alone: it is what carries the comparison between rows, and the
     absolute beside it was a second number of its own varying width, which left
     every share sitting at a different place in its column. The counts are not
     lost -- each bar's segments carry them on hover, under the row's own
     denominator in the caption.

     Nothing at all reads as an em dash rather than 0%, which keeps the No ratio
     column -- all zeroes under the weighted reading, since no participant sits
     in a cell without a ratio -- from looking like a column of measurements. A
     share that rounds down to 0% is a different thing and keeps its figure. */
  const bandCell = (v, total) => v
    ? `<td><b>${(v / total * 100).toFixed(0)}%</b></td>`
    : '<td><span class="nil">&mdash;</span></td>';

  const bandBar = ({ values, nilValue, total, unit }) => {
    const seg = (v, cls, label) => v
      ? `<span class="bseg ${cls}" style="width:${(v / total * 100).toFixed(2)}%"`
        + ` title="${fmt(v)} of ${fmt(total)} ${unit} — ${label}"></span>` : "";
    return '<span class="bbar">'
      + values.map((v, i) => seg(v, RATIO_BANDS[i].swatch, RATIO_BANDS[i].label)).join("")
      + seg(nilValue, "m-nil", NO_RATIO)
      + `</span><span class="bcap">${fmt(total)} ${unit}</span>`;
  };

  document.getElementById("bandBody").innerHTML = tally.map(t => {
    const r = reading(t);
    const cells = r.values.map(v => bandCell(v, r.total)).join("");
    // The pooled row is a second reading of the two rows above it rather than a
    // category in its own right, so it is marked as derived from them.
    const pooled = t.cat === POOL_NAME;
    return `<tr${pooled ? ' class="pooled"' : ""}>`
      + `<td>${pooled ? "HPS + Fully Accessible" : of(t)}`
      + (pooled ? '<div class="bnote">the two rows above, read as one body of stock '
        + 'against one body of demand</div>' : "")
      + "</td>" + cells
      + (anyNil ? bandCell(r.nilValue, r.total) : "")
      + `<td class="bdist">${bandBar(r)}</td></tr>`;
  }).join("");

  /* Read off the tally rather than written down, so a rebuilt data file cannot
     leave the prose asserting something the table no longer shows. */
  const row = c => tally.find(t => t.cat === c);
  const byRegion = (c, i) => (row(c).counts[i] / n * 100).toFixed(0) + "%";
  const byPerson = (c, i) => (row(c).weights[i] / row(c).need * 100).toFixed(0) + "%";

  document.getElementById("bandNote").innerHTML =
    "<b>Weighted by participants, because a region is not a person.</b> Counting each "
    + "region once, whatever its size, answers how widespread a shortfall is; weighting "
    + "each by the participants it holds in that category answers how many people it "
    + "reaches. The switch above moves between the two, and weighted is the default "
    + "because it is the honest one rather than the softer one &mdash; the two agree "
    + "closely on the shortfalls that carry the story. Improved Liveability is short in "
    + `${byRegion("Improved Liveability", 0)} of regions and for `
    + `${byPerson("Improved Liveability", 0)} of its participants; Fully Accessible in `
    + `${byRegion("Fully Accessible", 0)} and ${byPerson("Fully Accessible", 0)}. So no `
    + "crowd of small regions is manufacturing them. Where the readings diverge it is the "
    + "oversupply that grows: High Physical Support is short in "
    + `${byRegion("High Physical Support", 0)} of regions but for only `
    + `${byPerson("High Physical Support", 0)} of its participants, and far above the need `
    + `recorded against it in ${byRegion("High Physical Support", 3)} of regions holding `
    + `${byPerson("High Physical Support", 3)} of them &mdash; counting regions understates `
    + "it. Weighted, each row is a share of <em>its own</em> category's participants, so "
    + "the totals under the bars differ down the column. "
    + "<b>General population is deliberately not the weight</b> &mdash; SDA need follows "
    + "disability prevalence and where services were historically built, not headcount, "
    + "and participants with an identified need is already the denominator of the ratio "
    + "being banded.";
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

/* ---------- surplus view ---------- */

function renderSurplus(g) {
  renderSurplusTiles(g);
  renderSurplusMap(g);
  renderSurplusGrid(g);
  renderSurplusNotes(g);
}

/* The surplus one geography holds. An SA4 answers for itself; Australia and a
   state are summed from their own regions. Note this is not sa4Groups(), which
   for an SA4 returns that region's PEERS -- right for the grid and the map,
   which put a region among the others in its state, and quite wrong for a tile
   that names the region itself. */
function surplusOf(g) {
  if (!g.has_places) return null;
  if (g.level === "SA4") return surplusFor(g);
  const kids = sa4Groups(g).flatMap(gr => gr.kids);
  return kids.length ? surplusAgg(kids.map(k => surplusFor(k))) : null;
}

const threshLabel = () => SURPLUS_THRESHOLDS.find(t => t[0] === surplusThreshold)[1];

function threshButtons() {
  return SURPLUS_THRESHOLDS.map(([t, label]) =>
    `<button type="button" data-thresh="${t}" aria-pressed="${t === surplusThreshold}">`
    + `${label}</button>`).join("");
}

function renderSurplusTiles(g) {
  const rec = surplusOf(g);
  const cats = surplusCats();
  const tiles = rec
    ? [["Surplus dwellings", cell(rec.total.dwellings),
        `past ${surplusThreshold.toFixed(2)} × recorded need`
        + (rec.total.excess_places != null
            ? ` · ${fmt(rec.total.excess_places)} places` : "")],
       ...cats.map(c => {
         const x = rec[c];
         const lent = (c === POOL_OF[0] && substitution && x.lent)
           ? `after covering ${fmt(x.lent)} Fully Accessible places` : null;
         return [c, cell(x.dwellings),
           lent || (x.excess_places != null ? `${fmt(x.excess_places)} places` : null)];
       })]
    : [["Surplus dwellings", '<span class="nil">&mdash;</span>',
        "places are not published below SA4"]];

  document.getElementById("surTiles").innerHTML = tiles.map(([k, v, note]) =>
    `<div class="tile"><dt>${k}</dt><dd>${v}${note ? `<div class="tile-note">${note}</div>` : ""}</dd></div>`
  ).join("");
}

/* One legend for the surplus scale, shared by the map and the grid, for the
   same reason ratioLegend() is shared: two copies are only a way for the two
   panels to drift apart. */
function surplusLegend(showNil) {
  const sw = c => '<span class="' + c + '"></span>';
  return '<div class="mrow"><i></i><span class="msw">' + sw("s0")
    + "</span><span>nothing spare at this threshold</span>"
    + '<span class="mticks">0 dwellings</span></div>'
    + '<div class="mrow"><i class="g-surp">▲</i><span class="msw">'
    + sw("s1") + sw("s2") + "</span><span>some stock past the recorded need</span>"
    + '<span class="mticks">1 – 10, then 10 – 25</span></div>'
    + '<div class="mrow"><i class="g-surp">▲</i><span class="msw">'
    + sw("s3") + sw("s4") + sw("s5")
    + "</span><span>substantial stock past the recorded need</span>"
    + '<span class="mticks">25 – 50, 50 – 100, then 100 and over</span></div>'
    + (showNil
        ? '<div class="mrow"><i></i><span class="msw">' + sw("m-nil")
          + "</span><span>not calculable — a suppressed count on one side</span></div>"
        : "");
}

/* Surplus dwellings for one region under the current category selection. */
function surplusValue(rec, cat) {
  if (!rec) return null;
  const x = cat === SURPLUS_ALL ? rec.total : rec[cat];
  return x ? x.dwellings : null;
}

function renderSurplusMap(g) {
  const panel = document.getElementById("surMapPanel");
  if (!GEO || !GEO.views || g.level === "SA3") { panel.hidden = true; return; }
  panel.hidden = false;

  const cats = surplusCats();
  if (surplusCategory !== SURPLUS_ALL && cats.indexOf(surplusCategory) < 0) {
    surplusCategory = SURPLUS_ALL;
  }
  const cat = surplusCategory;
  const catLabel = cat === SURPLUS_ALL ? "All design categories" : cat;
  const scope = g.level === "National" ? null : g.state;
  const nat = GEO.views.national;
  const inScope = id => !scope || (BY_ID.get(id) || {}).state === scope;

  const recs = new Map();
  const valueOf = id => {
    if (!recs.has(id)) {
      const r = BY_ID.get(id);
      recs.set(id, r ? surplusFor(r) : null);
    }
    return surplusValue(recs.get(id), cat);
  };

  const region = (id, d) => {
    if (!inScope(id)) return '<path class="m-out" d="' + d + '"/>';
    const r = BY_ID.get(id);
    const v = valueOf(id);
    const rec = recs.get(id);
    const detail = v === null
      ? "not calculable — a suppressed count on one side"
      : v === 0
        ? "nothing past " + surplusThreshold.toFixed(2) + " × recorded need"
        : fmt(v) + " surplus " + (v === 1 ? "dwelling" : "dwellings")
          + " · " + fmt(Math.round((cat === SURPLUS_ALL ? rec.total : rec[cat]).excess_places))
          + " places";
    return '<a class="m-a' + (id === g.id ? " m-here" : "") + '"'
      + ' href="' + hashFor("surplus", id) + '">'
      + "<title>" + r.name + " — " + detail + " · " + catLabel + "</title>"
      + '<path class="' + surplusClass(v) + '" d="' + d + '"/></a>';
  };

  const draw = (v, box, label) => {
    const out = ['<svg viewBox="' + box + '" role="img" aria-label="' + label + '">'];
    for (const id in v.regions) out.push(region(id, v.regions[id]));
    out.push('<path class="m-mesh" d="' + v.mesh + '"/></svg>');
    return out.join("");
  };

  const ids = Object.keys(nat.regions).filter(inScope);
  const vals = ids.map(valueOf);
  const holding = vals.filter(v => v !== null && v > 0).length;
  const total = vals.reduce((t, v) => t + (v || 0), 0);
  const where = scope || "Australia";
  const label = catLabel + ", surplus dwellings by SA4 region. " + holding + " of the "
    + ids.length + " regions in " + where + " hold stock past "
    + surplusThreshold.toFixed(2) + " times the need recorded against them, "
    + fmt(total) + " dwellings in all.";

  document.getElementById("surMapMain").innerHTML = MAP_DEFS + draw(
    nat, scope ? pathBox(scope, ids.map(i => nat.regions[i]))
               : "0 0 " + nat.width + " " + nat.height, label);

  const insets = scope
    ? (STATE_INSET[scope] ? [STATE_INSET[scope]] : [])
    : Object.keys(STATE_INSET).map(k => STATE_INSET[k]);
  document.getElementById("surMapInsets").innerHTML = insets.map(name => {
    const v = GEO.views["gccsa:" + name];
    if (!v) return "";
    return '<figure class="map-inset">'
      + draw(v, "0 0 " + v.width + " " + v.height, name + ", " + catLabel)
      + "<figcaption>" + name.replace("Greater ", "") + "</figcaption></figure>";
  }).join("");

  document.getElementById("surMapSwitch").innerHTML =
    [[SURPLUS_ALL, "All categories"]].concat(cats.map(c =>
      [c, c === POOL_OF[0] ? "HPS" : c === POOL_OF[1] ? "Fully Accessible" : c]))
    .map(([key, label2]) =>
      '<button type="button" data-cat="' + key + '" aria-pressed="'
      + (key === cat) + '">' + label2 + "</button>").join("");
  document.getElementById("surThreshSwitch").innerHTML = threshButtons();
  document.getElementById("surModeSwitch").innerHTML = modeButtons();

  document.getElementById("surMapSub").textContent =
    fmt(total) + " surplus dwellings across " + holding + " of "
    + (scope ? ids.length + " " + where + " regions" : "all " + ids.length + " SA4 regions")
    + " · " + (substitution ? "allowing substitution" : "as enrolled")
    + " · click a region to open it";

  document.getElementById("surMapLegend").innerHTML =
    surplusLegend(vals.some(v => v === null));

  document.getElementById("surMapNote").innerHTML =
    "<b>Colour shows how much stock is standing past the need recorded against it</b>, in "
    + "dwellings &mdash; so unlike the ratio map, a blank region and a coloured one differ in "
    + "size of surplus, not in how tight the market is. A blank region is not necessarily "
    + "well supplied: it may be badly short. Dwellings are approximated by dividing surplus "
    + "places by the region&rsquo;s own average places per dwelling in that category, and "
    + "rounded down."
    + (substitution
        ? " High Physical Support is shown after covering the Fully Accessible shortfall in "
          + "the same region: those places are subtracted from it, not counted twice."
        : " Read as enrolled, so High Physical Support surplus here has not been asked to "
          + "cover the Fully Accessible shortfall beside it.");
}

/* The same figures as the map, as counts rather than colour, every category at
   once. The map answers "where"; this answers "how much, and in what". */
function renderSurplusGrid(g) {
  const panel = document.getElementById("surGridPanel");
  const scope = g.level === "National" ? null : g.state;
  const groups = sa4Groups(g);
  if (!groups.length) { panel.hidden = true; return; }
  panel.hidden = false;

  const cats = surplusCats();
  /* Rows are plain objects rather than geographies: a state row's surplus is
     summed from its regions, not read from a subtotal, so it is not a figure
     any geography in the file carries. */
  const rowOf = (node, kids) => {
    const parts = kids || [node];
    return {
      id: node.id, name: node.name, node,
      sur: kids ? surplusAgg(kids.map(k => surplusFor(k))) : surplusFor(node),
      places: parts.reduce((t, k) => t + (totalPlaces(k) || 0), 0),
      dwellings: parts.reduce((t, k) => t + (k.totals.enrolled_dwellings || 0), 0),
    };
  };
  const rows = groups.map(gr => ({
    head: rowOf(gr.state, gr.kids),
    kids: gr.kids.map(k => rowOf(k)),
  }));

  const cols = [
    { key: "name", label: "Region" },
    { key: "places", label: "Enrolled<br>places", get: r => r.places },
    { key: "dwellings", label: "Enrolled<br>dwellings", get: r => r.dwellings },
    ...cats.map(c => ({
      key: c, surplus: true,
      label: c === POOL_OF[0] ? abbrLabel("HPS", c)
           : c === POOL_OF[1] ? abbrLabel("FA", c)
           : c === "Improved Liveability" ? "Improved<br>Liveability" : c,
      get: r => surplusValue(r.sur, c),
      rec: r => r.sur && r.sur[c],
    })),
    { key: "total", surplus: true, total: true, label: "All<br>categories",
      get: r => surplusValue(r.sur, SURPLUS_ALL), rec: r => r.sur && r.sur.total },
  ];

  if (surplusSort.key && !cols.some(c => c.key === surplusSort.key)) {
    surplusSort = { key: null, dir: -1 };
  }
  const cmp = surplusSort.key
    ? rowCompare(cols.find(c => c.key === surplusSort.key), surplusSort.dir)
    : (a, b) => (surplusValue(b.sur, SURPLUS_ALL) || 0) - (surplusValue(a.sur, SURPLUS_ALL) || 0);
  rows.forEach(r => r.kids.sort(cmp));
  rows.sort((a, b) => cmp(a.head, b.head));

  const regions = rows.reduce((n, r) => n + r.kids.length, 0);
  document.getElementById("surGridTitle").textContent =
    `Surplus dwellings in ${regions} SA4 regions by design category`
    + (scope ? ` in ${rows[0].head.node.name}` : " across Australia");
  const one = rows.length === 1;
  document.getElementById("surGridSub").textContent =
    `Stock past ${surplusThreshold.toFixed(2)} × the need recorded against it · `
    + (substitution ? "allowing substitution · " : "as enrolled · ")
    + (one ? "" : "click ▸ to open a state's regions, ")
    + "click a column to sort, a row to open";

  document.getElementById("surGridThreshSwitch").innerHTML = threshButtons();
  // The total column is ruled off from the four it sums; headCells() is shared
  // with the supply grid, so the class is added here rather than given to it.
  document.getElementById("surGridHead").innerHTML = headCells(cols, surplusSort)
    .replace('class="sortable" data-key="total"', 'class="sortable stot" data-key="total"');

  const surplusCell = (col, r) => {
    const v = col.get(r);
    const x = col.rec(r);
    if (v === null || v === undefined) {
      return '<td class="hc m-nil' + (col.total ? " stot" : "")
        + '" title="Not calculable — a count on one side is suppressed">'
        + '<span class="sr-only">not calculable</span></td>';
    }
    const bits = [fmt(v) + " surplus " + (v === 1 ? "dwelling" : "dwellings")];
    if (x.excess_places != null) bits.push(fmt(Math.round(x.excess_places)) + " places");
    if (x.places_per_dwelling) bits.push(x.places_per_dwelling.toFixed(2) + " places per dwelling");
    if (x.lent) bits.push("after covering " + fmt(Math.round(x.lent)) + " Fully Accessible places");
    if (x.partial) bits.push(x.partial + " suppressed cell" + (x.partial === 1 ? "" : "s") + " left out");
    return '<td class="hc ' + surplusClass(v) + (col.total ? " stot" : "")
      + '" title="' + bits.join(" · ") + '">' + fmt(v)
      + (x.partial ? '<span class="sr-only"> — partial, suppressed cells left out</span>' : "")
      + "</td>";
  };

  const dataCells = r => cols.slice(1).map(c =>
    c.surplus ? surplusCell(c, r) : `<td>${cell(c.get(r))}</td>`).join("");

  const body = document.getElementById("surGridBody");
  let anyOpen = false;
  body.innerHTML = rows.map(gr => {
    const id = encodeURIComponent(gr.head.id);
    const open = one || surplusExpanded.has(gr.head.id);
    if (open) anyOpen = true;
    const head =
      `<tr class="grouprow linked" data-id="${id}">`
      + `<td class="region">`
      + (one ? "" : `<button type="button" class="gtoggle" data-state="${id}"`
        + ` aria-expanded="${open}"><span class="sr-only">${open ? "Collapse" : "Expand"} `
        + `${gr.head.name}</span><span aria-hidden="true">${open ? "▾" : "▸"}</span></button>`)
      + `<a href="${hashFor("surplus", gr.head.id)}">${gr.head.name}</a>`
      + `<span class="gcount">${gr.kids.length} regions</span></td>`
      + dataCells(gr.head) + "</tr>";
    if (!open) return head;
    return head + gr.kids.map(r =>
      `<tr class="linked${r.id === g.id ? " here" : ""}" data-id="${encodeURIComponent(r.id)}">`
      + `<td class="region sa4"><a href="${hashFor("surplus", r.id)}">${r.name}</a></td>`
      + dataCells(r) + "</tr>").join("");
  }).join("");

  document.getElementById("surGridTable").classList.toggle("tight", !anyOpen);
  document.getElementById("surGridLegend").innerHTML =
    surplusLegend(!!body.querySelector("td.m-nil"));

  document.getElementById("surGridNote").innerHTML =
    "<b>State rows are summed from their regions, not read from the NDIA&rsquo;s subtotals.</b> "
    + "Surplus is regional: a state subtotal would net a shortfall in one region against a "
    + "surplus in another and report the difference, as though nowhere were short. Every other "
    + "panel on this site uses the published subtotals, so these rows will not match them. "
    + "Dwellings are <b>approximated</b> &mdash; surplus places divided by the region&rsquo;s own "
    + "average places per dwelling in that category, rounded down &mdash; because the supplement "
    + "publishes places against participants and dwellings against nothing. "
    + "<b>HPS</b> is High Physical Support and <b>FA</b> is Fully Accessible."
    + (substitution
        ? " Allowing substitution, HPS answers for the Fully Accessible shortfall in its own "
          + "region first, and only what is left over is counted here; the places it lends are "
          + "subtracted from it, so no place is spare and in use at once. Nothing substitutes "
          + "for Improved Liveability or Robust, and Fully Accessible cannot substitute upwards, "
          + "so those three columns are unchanged by the toggle."
        : " Read as enrolled, every category answers for its own need alone.");

  const again = () => {
    const wrap = document.getElementById("surGridWrap");
    const top = wrap.scrollTop, left = wrap.scrollLeft;
    renderSurplusGrid(g);
    wrap.scrollTop = top;
    wrap.scrollLeft = left;
  };

  document.getElementById("surGridHead").onclick = e => {
    const th = e.target.closest("th[data-key]");
    if (!th) return;
    const key = th.dataset.key;
    surplusSort = (surplusSort.key === key) ? { key, dir: -surplusSort.dir }
                                            : { key, dir: key === "name" ? 1 : -1 };
    again();
  };
  document.getElementById("surGridBody").onclick = e => {
    const tog = e.target.closest("button.gtoggle");
    if (tog) {
      const sid = decodeURIComponent(tog.dataset.state);
      if (surplusExpanded.has(sid)) surplusExpanded.delete(sid);
      else surplusExpanded.add(sid);
      again();
      return;
    }
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr[data-id]");
    if (tr) go(decodeURIComponent(tr.dataset.id));
  };
}

function renderSurplusNotes(g) {
  const notes = [
    ["t-block", "A surplus dwelling here is not an empty dwelling.",
     "Enrolled places include places that are <b>already occupied</b>. What this panel measures is a "
     + "mismatch of <b>mix</b> &mdash; stock enrolled in a category beyond the need recorded against "
     + "that category in that region &mdash; not vacancy. A participant assessed for one category but "
     + "living in another appears on both sides of it. The <b>Vacancy</b> view is the one that reads "
     + "listed availability."],
    ["t-info", "Dwellings are approximated from places.",
     "The supplement publishes places against participants and dwellings against nothing, so surplus "
     + "is calculated in places and converted using the region&rsquo;s own average places per dwelling "
     + "in that category &mdash; its enrolled places over its enrolled dwellings &mdash; then rounded "
     + "<b>down</b>. A region whose surplus sits in its larger dwellings will be overstated by this and "
     + "one whose surplus sits in its singles understated. Hover a cell for the average used."],
    ["t-care", `The threshold is a tolerance, not a target.`,
     `Stock is only counted once a region is past <b>${surplusThreshold.toFixed(2)} ×</b> the need `
     + "recorded against it, so a region carrying a little headroom is not reported as holding "
     + "surplus. Neither cut is a policy position on how much headroom a market should carry: they "
     + "are two readings, offered so the finding can be tested against the weaker one."],
    ...(substitution ? [["t-info", "High Physical Support is counted after it covers Fully Accessible.",
     "HPS is defined cumulatively on top of Fully Accessible, so HPS stock can house someone assessed "
     + "for FA. Allowing substitution, each region&rsquo;s HPS stock is made to cover its own FA "
     + "shortfall first and those places are <b>subtracted</b> from it &mdash; the surplus shown is what "
     + "survives that. FA cannot substitute upwards and nothing substitutes for Improved Liveability or "
     + "Robust. Every dwelling is still <b>enrolled</b> in one category, and SDA payment follows the "
     + "participant&rsquo;s funded category, so this is physical suitability rather than what a provider "
     + "would be paid."]] : [["t-care", "Read as enrolled, nothing is allowed to substitute.",
     "Each category answers for its own need alone, so High Physical Support surplus here has not been "
     + "asked to cover the Fully Accessible shortfall standing beside it. Switch to <b>allowing "
     + "substitution</b> for the reading that has."]]),
    ["t-care", "The pipeline is excluded.",
     "This is the standing enrolled stock only. Pipeline dwellings &mdash; which the NDIA states may "
     + "never be enrolled, or may be enrolled in a different category &mdash; would add to every surplus "
     + "shown here, and add most where the surplus is already largest."],
    ["t-care", "Small counts are suppressed, not zero.",
     "Where the NDIA publishes a count below its threshold, no surplus can be formed and the cell reads "
     + "&mdash; rather than 0. Those cells are left out of the totals beside them rather than counted as "
     + "nothing, and a total missing one says so when hovered."],
  ];

  document.getElementById("surNotes").innerHTML = notes.map(([tag, head, body]) =>
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
