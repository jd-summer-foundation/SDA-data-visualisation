#!/usr/bin/env node
/* Browser smoke test for the explorer.

   Serves the repository root, opens every view at desktop and phone width,
   drives the main toggles, and fails on any page error, on horizontal
   overflow at 390px, or on the specific regressions listed at the bottom.

   Needs Playwright and a Chromium it can find:
     npm install --no-save playwright && npx playwright install chromium
     node tests/smoke.js
   If Playwright is installed globally instead:
     NODE_PATH="$(npm root -g)" node tests/smoke.js
*/
"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                ".json": "application/json", ".csv": "text/csv" };

function serve() {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const file = path.join(ROOT, url.endsWith("/") ? url + "index.html" : url);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404); res.end(); return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(resolve => server.listen(0, "127.0.0.1", () => resolve(server)));
}

const PAGES = [
  "#national", "#state:VIC", "#sa4:VIC - Geelong", "#sa3:VIC - Ballarat",
  "#surplus!national", "#surplus!state:NSW", "#surplus!sa4:VIC - Melbourne - West",
  "#vacancy!national", "#vacancy!state:QLD", "#vacancy!sa4:VIC - Melbourne - West",
];

/* Clicks that re-render. Each is tried only where its control is on screen. */
const TOGGLES = [
  "#modeSwitch button[data-mode=substitution]", "#modeSwitch button[data-mode=enrolled]",
  "#bandModeSwitch button[data-band=regions]", "#heatGroupSwitch button[data-group=ranked]",
  "#heatBody button.gtoggle", "#mapSwitch button[data-cat='Robust']",
  "#surUncatSwitch button[data-uncat=basic]", "#surUncatSwitch button[data-uncat=prorata]",
  "#surThreshSwitch button[data-thresh='1.2']", "#surPipeSwitch button[data-pipe=pipeline]",
  "#surGridGroupSwitch button[data-group=ranked]", "#surMapSwitch button[data-cat='Robust']",
];

(async () => {
  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch(
    process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const failures = [];
  const fail = msg => { failures.push(msg); console.log("  FAIL " + msg); };

  async function page(width, colorScheme = "light") {
    const p = await browser.newPage({ viewport: { width, height: 900 }, colorScheme });
    // Fonts are the one external request; blocking them keeps the test offline.
    await p.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort());
    p.errors = [];
    p.on("pageerror", e => p.errors.push(e.message));
    p.on("console", m => {
      if (m.type() === "error" && !/ERR_FAILED/.test(m.text())) p.errors.push(m.text());
    });
    return p;
  }

  async function open(p, hash) {
    await p.goto(base + hash);
    await p.waitForFunction(() => !document.getElementById("view").hidden);
    // The vacancy view fetches its own file after first paint.
    if (hash.startsWith("#vacancy")) await p.waitForSelector("#vacTiles .tile");
    await p.waitForTimeout(100);
  }

  for (const width of [1280, 390]) {
    console.log(`at ${width}px`);
    const p = await page(width);
    for (const hash of PAGES) {
      await open(p, hash);
      if (width === 1280) {
        for (const sel of TOGGLES) {
          const el = await p.$(sel);
          if (el && await el.isVisible()) await el.click();
        }
      }
      const over = await p.evaluate(() => document.scrollingElement.scrollWidth - innerWidth);
      if (over > 0) fail(`${hash} overflows by ${over}px at ${width}px`);
      if (p.errors.length) fail(`${hash} at ${width}px: ${p.errors.join(" / ")}`);
      p.errors = [];
      console.log(`  ok   ${hash}`);
    }
    await p.close();
  }

  // The time-based interface in time/ (docs/ui-plan.md), both themes, both
  // readings of supply, desktop and phone.
  for (const width of [1280, 390]) {
    for (const scheme of ["light", "dark"]) {
      const p = await page(width, scheme);
      for (const hash of ["#/", "#/?sub=1"]) {
        const label = `time/${hash} ${scheme} ${width}px`;
        await p.goto(base + "time/" + hash);
        // A hash-only change re-renders in place, so wait for the page to show
        // the reading asked for, not just for a chart to exist.
        const sub = hash.includes("sub=1");
        await p.waitForFunction(want => {
          const b = document.querySelector("#subSwitch button[data-sub=substitution]");
          return b && b.getAttribute("aria-pressed") === String(want)
            && document.querySelectorAll("#categories .multiples figure svg").length === (want ? 3 : 4);
        }, sub);
        await p.waitForTimeout(150);
        const sections = await p.$$eval("#page .section", s => s.length);
        if (sections !== 6) fail(`${label}: ${sections} sections, expected 6`);
        const charts = await p.$$eval("#page .chart svg", s => s.length);
        const tables = await p.$$eval("#page details.numbers table", t => t.length);
        if (charts < 8) fail(`${label}: only ${charts} charts drew`);
        if (tables < 5) fail(`${label}: only ${tables} tables behind the charts`);
        const multiples = await p.$$eval("#categories .multiples figure", f => f.length);
        if (multiples !== (sub ? 3 : 4)) fail(`${label}: ${multiples} category charts`);
        // Hover and keyboard both reach the tooltip.
        const supply = await p.$("#supply svg");
        await supply.scrollIntoViewIfNeeded();
        const box = await supply.boundingBox();
        await p.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
        if (await p.$eval("#tip", t => t.hidden)) fail(`${label}: hovering a chart shows no tooltip`);
        await p.mouse.move(0, 0);
        await p.focus("#pipeline svg");
        await p.keyboard.press("ArrowLeft");
        if (await p.$eval("#tip", t => t.hidden)) fail(`${label}: arrow keys on a chart show no tooltip`);
        const over = await p.evaluate(() => document.scrollingElement.scrollWidth - innerWidth);
        if (over > 0) fail(`${label} overflows by ${over}px`);
        if (p.errors.length) fail(`${label}: ${p.errors.join(" / ")}`);
        p.errors = [];
        console.log(`  ok   ${label}`);
      }
      // The toggle re-renders in place and carries into the link.
      await p.goto(base + "time/#/");
      await p.waitForSelector("#supply svg");
      await p.click("#subSwitch button[data-sub=substitution]");
      if (!(await p.evaluate(() => location.hash)).includes("sub=1")) fail("the substitution toggle is not in the link");
      if (!/HPS \+ FA/.test(await p.textContent("#categories h2"))) fail("substitution does not change the category headline");
      await p.close();
    }
  }

  // Region pages and the region index.
  for (const width of [1280, 390]) {
    for (const scheme of ["light", "dark"]) {
      const p = await page(width, scheme);
      for (const hash of ["#/regions", "#/regions?state=NSW", "#/region/VIC - Melbourne - West",
                          "#/region/NSW - Richmond - Tweed?sub=1", "#/region/QLD - Queensland - Outback"]) {
        const label = `time/${hash} ${scheme} ${width}px`;
        await p.goto(base + "time/" + hash);
        await p.waitForFunction(() => document.querySelector("#page h1"));
        await p.waitForTimeout(150);
        if (hash.startsWith("#/region/")) {
          const figs = await p.$$eval("#categories .multiples figure svg", f => f.length);
          if (figs !== (hash.includes("sub=1") ? 3 : 4)) fail(`${label}: ${figs} category charts`);
          if (!(await p.$$eval(".tiles .tile", t => t.length) === 3)) fail(`${label}: tiles missing`);
          if (!(await p.textContent(".intro .lead")).trim()) fail(`${label}: no headline`);
        }
        const over = await p.evaluate(() => document.scrollingElement.scrollWidth - innerWidth);
        if (over > 0) fail(`${label} overflows by ${over}px`);
        if (p.errors.length) fail(`${label}: ${p.errors.join(" / ")}`);
        p.errors = [];
        console.log(`  ok   ${label}`);
      }
      await p.close();
    }
  }
  {
    const p = await page(1280);
    // The filter, the search and the link all agree.
    await p.goto(base + "time/#/regions");
    await p.waitForSelector("table.regions tbody tr");
    await p.click("#regionList button[data-state=TAS]");
    let rows = await p.$$eval("table.regions tbody tr:not(.group)", r => r.length);
    if (rows !== 4) fail(`TAS filter shows ${rows} regions, expected 4`);
    if (!(await p.evaluate(() => location.hash)).includes("state=TAS")) fail("state filter is not in the link");
    await p.click("#regionList button[data-state='']");
    await p.fill("#regionSearch", "geelong");
    rows = await p.$$eval("table.regions tbody tr:not(.group)", r => r.length);
    if (rows !== 1) fail(`searching "geelong" shows ${rows} regions`);
    // A region link keeps the substitution reading.
    await p.goto(base + "time/#/regions?sub=1");
    await p.waitForSelector("table.regions tbody a");
    await p.click("table.regions tbody a >> nth=0");
    await p.waitForSelector("#categories .multiples figure svg");
    if (!(await p.evaluate(() => location.hash)).includes("sub=1")) fail("region link drops the substitution reading");
    // An unknown region says so rather than failing.
    await p.goto(base + "time/#/region/Nowhere");
    await p.waitForFunction(() => document.querySelector("#page h1"));
    if (!/No such region/.test(await p.textContent("#page h1"))) fail("unknown region does not say so");
    // Every SA4 page renders cleanly.
    const ids = await p.evaluate(() => Object.keys(DATA.geographies).filter(g => g.startsWith("sa4:")));
    for (const id of ids) {
      await p.goto(base + "time/#/region/" + encodeURIComponent(id.slice(4)));
      await p.waitForFunction(() => document.querySelector("#page h1"));
      await p.waitForTimeout(40);
      const over = await p.evaluate(() => document.scrollingElement.scrollWidth - innerWidth);
      if (over > 0 || p.errors.length) fail(`${id}: overflow ${over}px ${p.errors.join(" / ")}`);
      p.errors = [];
    }
    console.log(`  ok   all ${ids.length} region pages`);
    await p.close();
  }

  // Regressions fixed once and worth keeping fixed.
  const p = await page(1280);

  await open(p, "#%E0%A4%A");
  if ((await p.textContent("#placeName")) !== "Australia") fail("a malformed hash did not land on Australia");
  if (p.errors.length) fail("a malformed hash raised: " + p.errors.join(" / "));

  await open(p, "#surplus!sa4:VIC - Geelong");
  const crumb = await p.getAttribute("#crumbs a:last-of-type", "href");
  if (!crumb || !crumb.startsWith("#surplus!")) fail(`surplus breadcrumb leaves the view: ${crumb}`);
  if (/published subtotals/.test(await p.textContent("#footNote"))) {
    fail("surplus view shows the supply view's footnote");
  }

  // The two sites link to each other.
  await open(p, "#national");
  await p.click("a.viewlink");
  await p.waitForSelector("#supply svg");
  if (!p.url().endsWith("/time/")) fail(`"Over time" link lands on ${p.url()}`);
  await p.click("a.tab-out");
  await p.waitForFunction(() => !document.getElementById("view").hidden);

  await open(p, "#vacancy!national");
  const bar = await p.$eval("#vacFormBars .stackbar", el => el.getBoundingClientRect().width);
  if (bar < 50) fail(`dwelling-form bars have collapsed to ${bar}px`);

  await p.close();
  await browser.close();
  server.close();

  if (failures.length) {
    console.log(`\n${failures.length} failure(s)`);
    process.exit(1);
  }
  console.log("\nall smoke checks passed");
})().catch(err => { console.error(err); process.exit(1); });
