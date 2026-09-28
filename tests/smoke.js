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
    const file = path.join(ROOT, url === "/" ? "index.html" : url);
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

  async function page(width) {
    const p = await browser.newPage({ viewport: { width, height: 900 } });
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
