/* SDA over time: the Australia page (milestone 1 of docs/ui-plan.md).

   Reads ../data/timeseries.json, built by scripts/build_timeseries.py. Every
   headline and sentence comes from that file, where it is chosen from the
   numbers; this script only lays it out. Charts are hand-drawn SVG, as in the
   explorer: one y-axis each, 2px lines, direct end labels plus a legend, a
   crosshair and tooltip on hover and on arrow keys, and a table behind every
   chart so nothing is reachable by hover alone. */
"use strict";

let DATA = null;
let substitution = false;
const renders = [];          // re-run on resize, and when the toggle changes

/* ---------- small helpers ---------- */
const SVG = "http://www.w3.org/2000/svg";
function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "text") node.textContent = v;
    else if (k === "class") node.className = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) node.append(kid);
  return node;
}
function sv(tag, attrs = {}) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  return node;
}
const fmt = (v, dp = 0) => v == null ? "—"
  : v.toLocaleString("en-AU", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = v => v == null ? "—" : `${Math.round(v * 100)}%`;

/* Label every k-th quarter so labels never touch, always keeping the first and
   the last, and dropping any label that would crowd the last. */
function tickEvery(n, plotWidth, labelWidth) {
  return Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotWidth / labelWidth))));
}
function showTick(i, n, every) {
  if (i === n - 1 || i === 0) return true;
  return i % every === 0 && n - 1 - i >= every;
}

function niceMax(v) {
  if (v <= 0) return 1;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}
function ticks(max, n = 4) {
  const raw = max / n;
  const step = Math.pow(10, Math.floor(Math.log10(raw)));
  const nice = [1, 2, 5, 10].map(m => m * step).find(s => s >= raw);
  const out = [];
  for (let t = 0; t <= max + 1e-9; t += nice) out.push(+t.toFixed(6));
  return out;
}

/* ---------- tooltip ---------- */
const tip = () => document.getElementById("tip");
function showTip(x, y, head, rows) {
  const t = tip();
  t.replaceChildren(el("div", { class: "t-head", text: head }),
    ...rows.map(r => el("div", { class: "t-row" },
      el("i", { class: `key${r.dash ? " dash" : ""}`, style: `color:${r.color}` }),
      el("b", { text: r.value }), el("span", { text: r.name }))));
  t.hidden = false;
  const w = t.offsetWidth, h = t.offsetHeight;
  const left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14));
  const top = y - h - 12 < 8 ? y + 16 : y - h - 12;
  t.style.left = `${left}px`;
  t.style.top = `${top}px`;
}
const hideTip = () => { tip().hidden = true; };

/* ---------- charts ---------- */
/* A line chart with one y-axis. series: [{name, values, color, dash, label}].
   Optional: area {upper, lower, color} shaded between two series; bands (the
   1.0 / 1.5 ratio bands); rule {index, label}; yMax; yFmt. */
function lineChart(opts) {
  const box = el("div", { class: "chart" });
  const draw = () => {
    const width = Math.max(260, box.clientWidth || 600);
    const H = opts.height || 220;
    // Room for the end labels, from their length (11px semibold is about 6.6px a
    // character), so a label is never clipped at the right edge.
    const longest = Math.max(0, ...opts.series.map(s => (s.label || "").length));
    const labelRoom = longest ? Math.min(longest * 6.6 + 14, width * 0.4) : 12;
    const M = { t: 12, r: labelRoom, b: 26, l: opts.yWidth || 44 };
    const n = opts.labels.length;
    const all = opts.series.flatMap(s => s.values).filter(v => v != null);
    const yMax = opts.yMax || niceMax(Math.max(...all) * 1.05);
    const X = i => M.l + (n === 1 ? 0 : i * (width - M.l - M.r) / (n - 1));
    // Values above an explicit yMax sit on the top edge; the tooltip and the
    // table still carry the true figure.
    const Y = v => M.t + (H - M.t - M.b) * (1 - Math.min(v, yMax) / yMax);
    const yFmt = opts.yFmt || (v => fmt(v));
    const svg = sv("svg", { viewBox: `0 0 ${width} ${H}`, role: "img", tabindex: 0,
                            "aria-label": opts.aria || opts.title || "" });

    if (opts.bands) {
      const top = Math.min(yMax, 1e9);
      svg.append(sv("rect", { x: M.l, y: Y(1), width: width - M.l - M.r, height: Y(0) - Y(1),
                              style: "fill:var(--band-short)" }));
      if (top > 1.5) svg.append(sv("rect", { x: M.l, y: Y(top), width: width - M.l - M.r,
                                             height: Y(1.5) - Y(top), style: "fill:var(--band-long)" }));
    }
    const grid = sv("g", { class: "grid" }), axis = sv("g", { class: "axis" });
    for (const t of ticks(yMax)) {
      grid.append(sv("line", { x1: M.l, x2: width - M.r, y1: Y(t), y2: Y(t) }));
      const tx = sv("text", { x: M.l - 6, y: Y(t) + 4, "text-anchor": "end" });
      tx.textContent = yFmt(t);
      axis.append(tx);
    }
    axis.append(sv("line", { class: "base", x1: M.l, x2: width - M.r, y1: Y(0), y2: Y(0) }));
    const every = tickEvery(n, width - M.l - M.r, 72);
    opts.labels.forEach((lab, i) => {
      if (!showTick(i, n, every)) return;
      const tx = sv("text", { x: X(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" });
      tx.textContent = lab;
      axis.append(tx);
    });
    svg.append(grid, axis);

    if (opts.rule != null) {
      const x = X(opts.rule.index);
      svg.append(sv("line", { class: "rule-break", x1: x, x2: x, y1: M.t, y2: Y(0) }));
      const tx = sv("text", { class: "lbl", x: x - 4, y: M.t + 10, "text-anchor": "end" });
      tx.textContent = opts.rule.label;
      svg.append(tx);
    }
    if (opts.area) {
      const { upper, lower, color } = opts.area;
      const idx = upper.map((u, i) => i).filter(i => upper[i] != null && lower[i] != null);
      if (idx.length > 1) {
        const d = idx.map((i, k) => `${k ? "L" : "M"}${X(i)},${Y(upper[i])}`).join("")
          + idx.slice().reverse().map(i => `L${X(i)},${Y(lower[i])}`).join("") + "Z";
        svg.append(sv("path", { d, style: `fill:${color};opacity:.1` }));
      }
    }
    const labels = [];
    for (const s of opts.series) {
      let d = "", pen = false;
      s.values.forEach((v, i) => {
        if (v == null) { pen = false; return; }
        d += `${pen ? "L" : "M"}${X(i)},${Y(v)}`;
        pen = true;
      });
      svg.append(sv("path", { d, fill: "none", style: `stroke:${s.color}`, "stroke-width": 2,
                              "stroke-linejoin": "round", "stroke-linecap": "round",
                              "stroke-dasharray": s.dash ? "5 4" : null }));
      const last = s.values.map((v, i) => [v, i]).filter(([v]) => v != null).pop();
      if (last && !s.dash) {
        svg.append(sv("circle", { cx: X(last[1]), cy: Y(last[0]), r: 4, style: `fill:${s.color};stroke:var(--surface)`, "stroke-width": 2 }));
        if (s.label) labels.push({ y: Y(last[0]), x: X(last[1]) + 8, text: s.label });
      }
    }
    // End labels: spread only enough to avoid overlap, never far from the line.
    labels.sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 13);
    for (const lab of labels) {
      const tx = sv("text", { class: "lbl strong", x: lab.x, y: lab.y + 4 });
      tx.textContent = lab.text;
      svg.append(tx);
    }

    // Crosshair and tooltip, by pointer and by arrow keys.
    const cross = sv("line", { class: "cross", y1: M.t, y2: Y(0), visibility: "hidden" });
    svg.append(cross);
    let at = -1;
    const place = (i, cx, cy) => {
      at = i;
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i));
      cross.setAttribute("visibility", "visible");
      const rows = opts.series.filter(s => s.values[i] != null)
        .map(s => ({ name: s.name, value: yFmt(s.values[i], true), color: s.color, dash: s.dash }));
      if (!rows.length) rows.push({ name: "not published this quarter", value: "—", color: "transparent" });
      showTip(cx, cy, opts.labels[i], rows);
    };
    const nearest = evt => {
      const r = svg.getBoundingClientRect();
      const x = (evt.clientX - r.left) * width / r.width;
      return Math.max(0, Math.min(n - 1, Math.round((x - M.l) / ((width - M.l - M.r) / Math.max(1, n - 1)))));
    };
    svg.addEventListener("pointermove", e => place(nearest(e), e.clientX, e.clientY));
    svg.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    svg.addEventListener("keydown", e => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "Escape") { cross.setAttribute("visibility", "hidden"); hideTip(); return; }
      const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1
        : Math.max(0, Math.min(n - 1, (at < 0 ? n - 1 : at) + (e.key === "ArrowRight" ? 1 : -1)));
      const r = svg.getBoundingClientRect();
      place(next, r.left + X(next) * r.width / width, r.top + M.t * r.height / H);
    });
    svg.addEventListener("blur", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    box.replaceChildren(svg);
  };
  renders.push(draw);
  requestAnimationFrame(draw);
  return box;
}

/* Columns from a single baseline: <=24px thick, 4px rounded data-end. */
function columnChart(opts) {
  const box = el("div", { class: "chart" });
  const draw = () => {
    const width = Math.max(260, box.clientWidth || 600);
    const H = opts.height || 200;
    const M = { t: 18, r: 8, b: 26, l: opts.yWidth || 44 };
    const n = opts.values.length;
    const lo = Math.min(0, ...opts.values.filter(v => v != null));
    const hi = niceMax(Math.max(...opts.values.filter(v => v != null)) * 1.1);
    const Y = v => M.t + (H - M.t - M.b) * (hi - v) / (hi - lo);
    const slot = (width - M.l - M.r) / n;
    const bw = Math.min(24, slot * 0.6);
    const yFmt = opts.yFmt || (v => fmt(v));
    const svg = sv("svg", { viewBox: `0 0 ${width} ${H}`, role: "img", tabindex: 0, "aria-label": opts.aria || "" });
    const grid = sv("g", { class: "grid" }), axis = sv("g", { class: "axis" });
    for (const t of ticks(hi)) {
      grid.append(sv("line", { x1: M.l, x2: width - M.r, y1: Y(t), y2: Y(t) }));
      const tx = sv("text", { x: M.l - 6, y: Y(t) + 4, "text-anchor": "end" });
      tx.textContent = yFmt(t);
      axis.append(tx);
    }
    axis.append(sv("line", { class: "base", x1: M.l, x2: width - M.r, y1: Y(0), y2: Y(0) }));
    svg.append(grid, axis);
    const every = tickEvery(n, width - M.l - M.r, 68);
    const bars = [];
    opts.values.forEach((v, i) => {
      const cx = M.l + slot * (i + 0.5);
      if (showTick(i, n, every)) {
        const tx = sv("text", { class: "lbl", x: cx, y: H - 8, "text-anchor": "middle" });
        tx.textContent = opts.labels[i];
        axis.append(tx);
      }
      if (v == null) return;
      const x = cx - bw / 2, y0 = Y(0), y1 = Y(v), r = Math.min(4, Math.abs(y0 - y1));
      const up = v >= 0;
      const d = up
        ? `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + bw - r}Q${x + bw},${y1} ${x + bw},${y1 + r}V${y0}Z`
        : `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + bw - r}Q${x + bw},${y1} ${x + bw},${y1 - r}V${y0}Z`;
      const bar = sv("path", { d, style: `fill:${opts.color}` });
      svg.append(bar);
      bars.push({ bar, cx, y: y1, i });
      if (opts.valueLabels) {
        // A value that rounds to zero sits above the baseline, clear of the axis labels.
        const above = up || Math.abs(v) < 0.005;
        const tx = sv("text", { class: "lbl strong", x: cx, y: above ? Math.min(y1, y0) - 5 : y1 + 13, "text-anchor": "middle" });
        tx.textContent = yFmt(v, true);
        svg.append(tx);
      }
    });
    let at = -1;
    const place = (k, px, py) => {
      at = k;
      bars.forEach((b, j) => b.bar.style.opacity = j === k ? 1 : 0.55);
      const b = bars[k];
      showTip(px, py, opts.labels[b.i], [{ name: opts.name, value: yFmt(opts.values[b.i], true), color: opts.color }]);
    };
    const reset = () => { bars.forEach(b => b.bar.style.opacity = 1); hideTip(); };
    svg.addEventListener("pointermove", e => {
      const r = svg.getBoundingClientRect();
      const x = (e.clientX - r.left) * width / r.width;
      const k = bars.reduce((best, b, j) => Math.abs(b.cx - x) < Math.abs(bars[best].cx - x) ? j : best, 0);
      place(k, e.clientX, e.clientY);
    });
    svg.addEventListener("pointerleave", reset);
    svg.addEventListener("blur", reset);
    svg.addEventListener("keydown", e => {
      if (!["ArrowLeft", "ArrowRight", "Escape"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "Escape") return reset();
      const k = Math.max(0, Math.min(bars.length - 1, (at < 0 ? 0 : at + (e.key === "ArrowRight" ? 1 : -1))));
      const r = svg.getBoundingClientRect();
      place(k, r.left + bars[k].cx * r.width / width, r.top + bars[k].y * r.height / H);
    });
    box.replaceChildren(svg);
  };
  renders.push(draw);
  requestAnimationFrame(draw);
  return box;
}

function legend(items) {
  return el("ul", { class: "legend" }, items.map(it => el("li", {},
    el("i", { class: `key${it.dash ? " dash" : ""}${it.swatch ? " swatch" : ""}`,
              style: it.swatch ? `background:${it.color}` : `color:${it.color}` }),
    el("span", { text: it.name }))));
}

function numbers(headers, rows) {
  return el("details", { class: "numbers" },
    el("summary", { text: "Show the numbers" }),
    el("div", { class: "tablewrap" },
      el("table", {},
        el("thead", {}, el("tr", {}, headers.map(h => el("th", { scope: "col", text: h })))),
        el("tbody", {}, rows.map(r => el("tr", {}, r.map((c, i) =>
          el(i ? "td" : "th", i ? { text: c } : { scope: "row", text: c }))))))));
}

const STATUS = {
  short: "▼ short", balanced: "◆ balanced", long: "▲ long", "drifting up": "↗ drifting up",
  "drifting down": "↘ drifting down", reverses: "↔ reverses", thin: "too few",
};
const statusChip = s => el("span", { class: `status ${s.replace(" ", "-")}`, text: STATUS[s] || s });

/* ---------- routes ---------- */
/* #/                       Australia
   #/regions?state=VIC      the region index, optionally filtered
   #/region/VIC - Geelong   one SA4
   Any of them takes ?sub=1 for the substitution reading, so a link carries it. */
function parseRoute() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  let decoded = path;
  try { decoded = decodeURIComponent(path); } catch (e) { /* keep it raw */ }
  const m = decoded.match(/^\/region\/(.+)$/);
  if (m) return { view: "region", id: `sa4:${m[1]}`, params };
  if (/^\/regions\/?$/.test(decoded)) return { view: "regions", params };
  return { view: "australia", params };
}

function href(path, params = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  if (substitution) q.set("sub", "1");
  const qs = q.toString();
  return `#${path}${qs ? "?" + qs : ""}`;
}
const regionHref = id => href(`/region/${encodeURIComponent(id.replace(/^sa4:/, ""))}`);

const C = { places: "var(--s-places)", use: "var(--s-use)", need: "var(--s-need)" };

/* ---------- blocks shared by the Australia and region pages ---------- */
function section(s, ...body) {
  const pick = v => typeof v === "string" ? v : v[substitution ? "substitution" : "enrolled"];
  return el("section", { class: "section", id: s.id, "aria-labelledby": `${s.id}-h` },
    el("h2", { id: `${s.id}-h`, text: pick(s.headline) }),
    s.evidence ? el("p", { class: "evidence", text: pick(s.evidence) }) : null,
    ...body,
    s.caveat ? el("p", { class: "caveat", text: s.caveat }) : null);
}

function supplyBlock(geo, height = 260) {
  const m = DATA.meta, L = m.labels, S = geo.series;
  const usePlus = S.in_use.map((u, i) => u == null || S.waiting[i] == null ? null : u + S.waiting[i]);
  return [
    legend([{ name: "Enrolled places", color: C.places }, { name: "Using SDA", color: C.use },
            { name: "Using SDA + eligible, not yet using", color: C.need },
            { name: "Spare: places not in SDA use", color: C.places, swatch: true }]),
    lineChart({ labels: L, height, aria: `Enrolled places, people using SDA and people waiting, ${geo.name}`,
      series: [{ name: "Enrolled places", values: S.places, color: C.places, label: "Places" },
               { name: "Using + waiting", values: usePlus, color: C.need, label: "Using + waiting" },
               { name: "Using SDA", values: S.in_use, color: C.use, label: "Using SDA" }],
      area: { upper: S.places, lower: S.in_use, color: C.places } }),
    el("p", { class: "chart-sub", text: `Participant series begin ${L[m.quarters.indexOf(m.in_use_from)]}.` }),
    numbers(["Quarter", "Enrolled places", "Using SDA", "Eligible, not yet using", "Spare places"],
      L.map((q, i) => [q, fmt(S.places[i]), fmt(S.in_use[i]), fmt(S.waiting[i]), fmt(S.spare[i])])),
  ];
}

const shownCategories = () => substitution
  ? ["Improved Liveability", DATA.meta.pooled, "Robust"] : DATA.meta.categories;

function categoryRatios(geo, c) {
  const m = DATA.meta, from = m.quarters.indexOf(m.need_from);
  const block = geo.categories[c];
  const ratio = key => block.places.slice(from).map((p, i) => {
    const n = block[key][from + i];
    return p == null || n == null || n === 0 ? null : p / n;
  });
  return { recorded: ratio("need"), proRata: ratio("need_pro_rata"),
           labels: m.labels.slice(from), status: block.status };
}

/* Small multiples of places per participant, on one shared scale so panels
   compare. Very thin regions can run to 10 or more; the scale stops at 5 and
   says so, with the true figure in the tooltip and the table. */
function categoryBlock(geo) {
  const cats = shownCategories();
  const series = Object.fromEntries(cats.map(c => [c, categoryRatios(geo, c)]));
  const all = cats.flatMap(c => series[c].recorded.concat(series[c].proRata)).filter(v => v != null);
  const peak = all.length ? Math.max(...all) : 2;
  const yMax = Math.max(2, Math.min(5, niceMax(peak * 1.05)));
  const labels = series[cats[0]].labels;
  return [
    legend([{ name: "Need as recorded", color: C.places },
            { name: "Uncategorised need spread pro-rata", color: C.places, dash: true },
            { name: "Short (below 1.0)", color: "var(--band-short)", swatch: true },
            { name: "Long (above 1.5)", color: "var(--band-long)", swatch: true }]),
    el("div", { class: `multiples ${cats.length === 4 ? "four" : "three"}` }, cats.map(c => el("figure", {},
      el("figcaption", {}, `${c} `, statusChip(series[c].status)),
      lineChart({ labels, height: 170, yMax, bands: true, yWidth: 32,
        aria: `${c}, places per participant with need, ${geo.name}`,
        yFmt: (v, exact) => exact ? v.toFixed(2) : v.toFixed(1),
        series: [{ name: "as recorded", values: series[c].recorded, color: C.places },
                 { name: "pro-rata", values: series[c].proRata, color: C.places, dash: true }] })))),
    peak > yMax ? el("p", { class: "chart-sub", text: `The scale stops at ${yMax.toFixed(1)}; higher figures sit on the top edge and are in the table.` }) : null,
    numbers(["Quarter", ...cats.flatMap(c => [c, `${c} (pro-rata)`])],
      labels.map((q, i) => [q, ...cats.flatMap(c => [series[c].recorded[i], series[c].proRata[i]]
        .map(v => v == null ? "—" : v.toFixed(2)))])),
  ];
}

/* A category verdict written from the statuses, for a region page. */
function categorySentence(geo) {
  const cats = shownCategories();
  const by = {};
  for (const c of cats) (by[geo.categories[c].status] ||= []).push(c);
  const list = xs => xs.length === 1 ? xs[0] : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`;
  const parts = [];
  const shortish = [...(by.short || []), ...(by["drifting down"] || [])];
  const longish = [...(by.long || []), ...(by["drifting up"] || [])];
  if (shortish.length) parts.push(`Short in ${list(shortish)}`);
  if (longish.length) parts.push(`${parts.length ? "long" : "Long"} in ${list(longish)}`);
  if (by.balanced) parts.push(`${parts.length ? "balanced" : "Balanced"} in ${list(by.balanced)}`);
  if (by.reverses) parts.push(`${parts.length ? "moving" : "Moving"} back and forth in ${list(by.reverses)}`);
  let sentence = parts.length ? parts.join("; ") + "." : "";
  if (by.thin) sentence += `${sentence ? " " : ""}Too few participants to read ${list(by.thin)}.`;
  return sentence;
}

function spark(values, color) {
  const pts = values.map((v, i) => [v, i]).filter(([v]) => v != null);
  const svg = sv("svg", { viewBox: "0 0 100 28", class: "spark", "aria-hidden": "true", preserveAspectRatio: "none" });
  if (pts.length < 2) return svg;
  const lo = Math.min(0, ...pts.map(p => p[0])), hi = Math.max(...pts.map(p => p[0])) || 1;
  const X = i => 2 + i * 96 / (values.length - 1), Y = v => 25 - (v - lo) / (hi - lo || 1) * 22;
  svg.append(sv("path", { d: pts.map(([v, i], k) => `${k ? "L" : "M"}${X(i)},${Y(v)}`).join(""),
                          fill: "none", style: `stroke:${color}`, "stroke-width": 2,
                          "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round" }));
  return svg;
}

function tile(label, values, color, note) {
  const known = values.filter(v => v != null);
  const now = known.at(-1), before = values.at(-5);
  const delta = now != null && before != null ? now - before : null;
  return el("div", { class: "tile" },
    el("dt", { text: label }),
    el("dd", {},
      el("span", { class: "tile-value", text: fmt(now) }),
      delta == null ? null : el("span", { class: "tile-delta", text: `${delta >= 0 ? "+" : "−"}${fmt(Math.abs(delta))} in a year` }),
      spark(values, color),
      note ? el("span", { class: "tile-note", text: note }) : null));
}

/* ---------- the Australia page ---------- */
function australia() {
  const m = DATA.meta, nat = DATA.geographies.national, S = nat.series;
  const story = Object.fromEntries(DATA.story.map(s => [s.id, s]));
  const L = m.labels, last = L.length - 1;
  const page = [];
  document.title = "SDA over time: Australia";

  page.push(el("div", { class: "intro" },
    el("div", { class: "kicker", text: `Australia · ${L[0]} to ${L[last]}` }),
    el("h1", { text: "Specialist Disability Accommodation, over thirteen quarters" }),
    el("p", { text: "Five things the NDIA's quarterly supplements show when they are read "
      + "together. Each headline is chosen from the figures and would change if they did." })));

  page.push(section(story.supply, ...supplyBlock(nat)));

  const ab = story.absorption;
  const lagLabels = ab.lags.map((_, i) => i ? `+${i} qtr` : "Same qtr");
  page.push(section(ab,
    el("div", { class: "chart-title", text: "People brought into SDA use per new place, by quarters since it was enrolled" }),
    columnChart({ labels: lagLabels, values: ab.lags, color: C.use, name: "per new place", valueLabels: true,
      yFmt: v => (Math.abs(v) < 0.005 ? 0 : v).toFixed(2), aria: ab.headline }),
    el("p", { class: "chart-sub", text: `Sum ${ab.lags.reduce((a, b) => a + b, 0).toFixed(2)} (range ${ab.range[0].toFixed(2)}–${ab.range[1].toFixed(2)} across specifications). At recent take-up the median region needs ${fmt(ab.quarters_to_fill_median)} quarters to fill its spare places.` }),
    numbers(["Quarters after enrolment", "People into use per new place"],
      ab.lags.map((v, i) => [lagLabels[i], (Math.abs(v) < 0.0005 ? 0 : v).toFixed(3)]))));

  page.push(section(story.categories, ...categoryBlock(nat)));

  const pp = story.pipeline, brk = m.quarters.indexOf(pp.break);
  const flowLabels = pp.flows.map(f => L[m.quarters.indexOf(f.quarter)]);
  page.push(section(pp,
    el("div", { class: "pair" },
      el("figure", {}, el("figcaption", { text: "Dwellings in the pipeline" }),
        lineChart({ labels: L, series: [{ name: "pipeline dwellings", values: S.pipeline_dwellings, color: C.need }],
                    rule: { index: brk, label: "36-month rule" }, aria: "Pipeline dwellings by quarter" })),
      el("figure", {}, el("figcaption", { text: "New-build dwellings enrolled each quarter" }),
        columnChart({ labels: flowLabels, values: pp.flows.map(f => f.enrolled), color: C.places,
                      name: "enrolled", aria: "New-build dwellings enrolled each quarter" }))),
    numbers(["Quarter", "Pipeline dwellings", "New-build enrolled", "Net additions to pipeline"],
      pp.flows.map((f, i) => [flowLabels[i], fmt(f.pipeline), fmt(f.enrolled), fmt(f.net_additions)]))));

  const mm = story.mismatch, mmLabels = mm.series.map(r => L[m.quarters.indexOf(r.quarter)]);
  page.push(section(mm,
    el("div", { class: "pair" },
      el("figure", {}, el("figcaption", { text: "Regions with more people waiting than spare places" }),
        lineChart({ labels: mmLabels, series: [{ name: "regions short", values: mm.series.map(r => r.regions_short), color: C.need }],
                    aria: "Regions short by quarter" })),
      el("figure", {}, el("figcaption", { text: "Waiting beyond local spare, and spare beyond local waiting" }),
        lineChart({ labels: mmLabels, aria: "Waiting beyond spare and spare beyond waiting",
          series: [{ name: "spare beyond local waiting", values: mm.series.map(r => r.spare_beyond_local_waiting), color: C.places, label: "Spare" },
                   { name: "waiting beyond local spare", values: mm.series.map(r => r.waiting_beyond_local_spare), color: C.need, label: "Waiting" }] }))),
    numbers(["Quarter", "Regions short", "Waiting beyond local spare", "Spare beyond local waiting"],
      mm.series.map((r, i) => [mmLabels[i], `${r.regions_short} of ${r.regions}`, fmt(r.waiting_beyond_local_spare), fmt(r.spare_beyond_local_waiting)]))));

  const yearAgo = last - 4;
  const states = Object.entries(DATA.geographies).filter(([, g]) => g.level === "State");
  page.push(el("section", { class: "section", id: "states", "aria-labelledby": "states-h" },
    el("h2", { id: "states-h", text: "By state" }),
    el("p", { class: "evidence", text: `Latest quarter, ${L[last]}, with the change in spare places over the year. Each state opens its regions.` }),
    el("div", { class: "tablewrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ["State", "Places", "Spare", "Share", "Spare, change in a year", "Eligible, not yet using", "Pipeline places"]
        .map(h => el("th", { scope: "col", text: h })))),
      el("tbody", {}, states.map(([, g]) => {
        const s = g.series;
        const change = s.spare[last] - s.spare[yearAgo];
        return el("tr", {}, el("th", { scope: "row" }, el("a", { href: href("/regions", { state: g.state }), text: g.name })),
          ...[fmt(s.places[last]), fmt(s.spare[last]), pct(s.spare[last] / s.places[last]),
              `${change >= 0 ? "+" : ""}${fmt(change)}`, fmt(s.waiting[last]), fmt(s.pipeline_places[last])]
            .map(t => el("td", { text: t })));
      })))),
    el("p", { class: "caveat", text: "States are the NDIA's published subtotals." })));
  return page;
}

/* ---------- the region index ---------- */
const STATES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"];

function regionsIndex(route) {
  const L = DATA.meta.labels, last = L.length - 1;
  let state = STATES.includes(route.params.get("state")) ? route.params.get("state") : "";
  let query = route.params.get("q") || "";
  document.title = `SDA over time: Regions${state ? ` in ${state}` : ""}`;
  const regions = Object.entries(DATA.geographies).filter(([, g]) => g.level === "SA4")
    .sort(([a], [b]) => a.localeCompare(b));

  const tbody = el("tbody");
  const count = el("p", { class: "chart-sub", role: "status" });
  const fill = () => {
    const q = query.trim().toLowerCase();
    const rows = [];
    let shown = 0;
    for (const st of STATES) {
      if (state && st !== state) continue;
      const mine = regions.filter(([, g]) => g.state === st && (!q || g.name.toLowerCase().includes(q)));
      if (!mine.length) continue;
      rows.push(el("tr", { class: "group" }, el("th", { colspan: 4, scope: "rowgroup", text: st })));
      for (const [id, g] of mine) {
        shown++;
        const s = g.series, change = s.spare[last] != null && s.spare[last - 4] != null ? s.spare[last] - s.spare[last - 4] : null;
        rows.push(el("tr", {},
          el("th", { scope: "row" }, el("a", { href: regionHref(id), text: g.name }),
            el("span", { class: "row-note", text: g.headline })),
          el("td", { text: s.places[last] ? `${fmt(s.spare[last])} (${pct(s.spare[last] / s.places[last])})` : "—" }),
          el("td", { text: change == null ? "—" : `${change >= 0 ? "+" : "−"}${fmt(Math.abs(change))}` }),
          el("td", { text: fmt(s.waiting[last]) })));
      }
    }
    tbody.replaceChildren(...rows);
    count.textContent = `${shown} of ${regions.length} regions`;
  };
  const keep = () => history.replaceState(null, "", href("/regions", { state, q: query.trim() }));

  const stateSwitch = el("div", { class: "switch wrap", role: "group", "aria-label": "Filter by state" },
    ["", ...STATES].map(st => el("button", { type: "button", "data-state": st, "aria-pressed": String(st === state), text: st || "All" })));
  stateSwitch.addEventListener("click", e => {
    const b = e.target.closest("button[data-state]");
    if (!b) return;
    state = b.dataset.state;
    stateSwitch.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    document.title = `SDA over time: Regions${state ? ` in ${state}` : ""}`;
    keep(); fill();
  });
  const search = el("input", { type: "search", id: "regionSearch", placeholder: "Find a region…",
                               "aria-label": "Find a region by name", value: query, autocomplete: "off" });
  search.addEventListener("input", () => { query = search.value; keep(); fill(); });
  fill();

  return [
    el("div", { class: "intro" },
      el("div", { class: "kicker", text: `${regions.length} SA4 regions · ${L[last]}` }),
      el("h1", { text: "Regions" }),
      el("p", { text: "Each region's page shows how its places, the people using them and the people waiting have moved, and where each design category sits." })),
    el("section", { class: "section", id: "regionList" },
      el("div", { class: "filters" }, stateSwitch, search),
      count,
      el("div", { class: "tablewrap" }, el("table", { class: "regions" },
        el("thead", {}, el("tr", {}, ["Region", "Spare places", "In a year", "Waiting"].map(h => el("th", { scope: "col", text: h })))),
        tbody))),
  ];
}

/* ---------- a region page ---------- */
function regionPage(route) {
  const g = DATA.geographies[route.id];
  if (!g || g.level !== "SA4") {
    document.title = "SDA over time: region not found";
    return [el("div", { class: "intro" }, el("h1", { text: "No such region" }),
      el("p", {}, "That link does not name one of the 88 SA4 regions. ",
        el("a", { href: href("/regions"), text: "See all regions" }), "."))];
  }
  const m = DATA.meta, L = m.labels, S = g.series;
  document.title = `SDA over time: ${g.name}`;
  const rank = g.rank || {};
  const rankLine = [];
  if (rank.spare) rankLine.push(`${ordinal(rank.spare[0])} of ${rank.spare[1]} regions for spare places`);
  if (rank.quarters_to_fill) rankLine.push(`${ordinal(rank.quarters_to_fill[0])} slowest of ${rank.quarters_to_fill[1]} to fill them at recent take-up`);
  const pipeNote = `36-month rule applied ${L[m.quarters.indexOf(m.pipeline_break)]}`;

  return [
    el("nav", { class: "crumbs", "aria-label": "Breadcrumb" },
      el("a", { href: href("/"), text: "Australia" }), " / ",
      el("a", { href: href("/regions", { state: g.state }), text: g.state }), " / ",
      el("span", { "aria-current": "page", text: g.name })),
    el("div", { class: "intro" },
      el("div", { class: "kicker", text: `${g.state} · SA4 region · ${L.at(-1)}` }),
      el("h1", { text: g.name }),
      el("p", { class: "lead", text: g.headline }),
      el("p", { text: g.evidence })),
    el("dl", { class: "tiles" },
      tile("Spare places", S.spare, C.places),
      tile("Eligible, not yet using", S.waiting, C.need),
      tile("Pipeline places", S.pipeline_places, C.need, pipeNote)),
    section({ id: "supply", headline: "Places, people using SDA, and people waiting",
              caveat: "Places not in SDA use is an upper bound on vacancy: a place can be occupied by someone not funded for SDA." },
      ...supplyBlock(g)),
    section({ id: "categories", headline: "By design category", evidence: categorySentence(g) || null,
              caveat: "A fifth of need nationally has no design category. The dashed line spreads it across categories in proportion; the solid line leaves it out. Status covers the seven quarters since need by category was first published." },
      ...categoryBlock(g)),
    el("section", { class: "section", id: "position", "aria-labelledby": "position-h" },
      el("h2", { id: "position-h", text: "Where it sits nationally" }),
      el("p", { class: "evidence", text: rankLine.length ? `${rankLine.join("; ")}.` : "Not ranked: no spare places are measured here." }),
      el("p", {}, el("a", { href: href("/regions", { state: g.state }), text: `Other regions in ${g.state}` }))),
  ];
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/* ---------- wiring ---------- */
let lastPath = null;
function render() {
  renders.length = 0;
  hideTip();
  const route = parseRoute();
  substitution = route.params.get("sub") === "1";
  document.querySelectorAll("#subSwitch button").forEach(b =>
    b.setAttribute("aria-pressed", String((b.dataset.sub === "substitution") === substitution)));
  const tab = route.view === "australia" ? "tabAustralia" : "tabRegions";
  document.querySelectorAll(".tabs a[id]").forEach(a => {
    if (a.id === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  document.getElementById("tabAustralia").href = href("/");
  document.getElementById("tabRegions").href = href("/regions");
  const page = route.view === "region" ? regionPage(route)
    : route.view === "regions" ? regionsIndex(route) : australia();
  document.getElementById("page").replaceChildren(...page);
  // A new page starts at the top; the switch re-renders in place.
  const path = location.hash.split("?")[0];
  if (lastPath !== null && path !== lastPath) window.scrollTo(0, 0);
  lastPath = path;
}

const THEMES = ["system", "light", "dark"];
function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const btn = document.getElementById("themeButton");
  btn.setAttribute("aria-label", `Colour theme: ${t === "system" ? "follows your system" : t}`);
  btn.title = btn.getAttribute("aria-label");
}

async function boot() {
  let theme = "system";
  try { theme = localStorage.getItem("sda-time-theme") || "system"; } catch (e) { /* private mode */ }
  applyTheme(THEMES.includes(theme) ? theme : "system");
  document.getElementById("themeButton").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || "system";
    const next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
    applyTheme(next);
    try { localStorage.setItem("sda-time-theme", next); } catch (e) { /* ignore */ }
  });
  try {
    const res = await fetch("../data/timeseries.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    document.getElementById("loading").textContent = `Could not load the data (${err.message}).`;
    return;
  }
  const L = DATA.meta.labels;
  document.getElementById("brandSub").textContent = `${L.length} quarters · ${L[0]} – ${L[L.length - 1]}`;
  document.getElementById("subSwitch").addEventListener("click", e => {
    const b = e.target.closest("button[data-sub]");
    if (!b) return;
    const [path, query = ""] = (location.hash.replace(/^#/, "") || "/").split("?");
    const params = new URLSearchParams(query);
    if (b.dataset.sub === "substitution") params.set("sub", "1"); else params.delete("sub");
    const qs = params.toString();
    history.replaceState(null, "", `#${path}${qs ? "?" + qs : ""}`);
    render();
  });
  window.addEventListener("hashchange", render);
  let pending = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => renders.forEach(f => f()));
  });
  document.getElementById("loading").hidden = true;
  document.getElementById("page").hidden = false;
  render();
}
boot();
