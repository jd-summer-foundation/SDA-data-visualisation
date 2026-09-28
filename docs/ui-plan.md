# Phase 3: a time-based interface — proposal

Status: **proposal for discussion**. Nothing here is built yet. It follows the
analysis in `data/panel/ANALYSIS.md`, and every number quoted below comes from
there.

## What the new interface is for

The current explorer answers *what does this region look like this quarter?* It
does that thoroughly, with 14 panels per page and five toggles. The analysis
changes the question to *which way is this going, and is it lasting?* The
answers that matter are few and strong:

- **The surplus is lasting.** A new place brings about 0.24 participants into use,
  within three quarters. Spare capacity roughly doubled in 30 months, and it does
  not drain where building stops.
- **The pipeline overstates what is coming.** About a third of it enrols in a
  year, and the March 2026 cull removed 20–31% of it.
- **Waiting falls where stock is added**, but the location mismatch is
  turning into an overhang.
- **Category positions are persistent.** Improved Liveability and Fully
  Accessible are short almost everywhere, and High Physical Support is long and
  getting longer.

So the new interface should show a few time series well, say in words what each
one shows, and rank regions by what persists. It is three views, not fourteen
panels.

## The three views

All three share a masthead: the title, a region search, and three tabs
(**Australia · Regions · League table**). All three read one file,
`data/timeseries.json`.

### 1. Australia: the national story

A single scrolling page of five short sections. Each section has one headline
sentence written from the data, one chart and one line of caveat. Read top to
bottom, it is the analysis in brief.

| # | Headline (written from data) | Chart | Caveat line |
| --- | --- | --- | --- |
| 1 | "Places grew by 9,503 since Dec 2023; people using SDA by 2,547." | Three lines on one axis, all in people and places: enrolled places, participants using SDA, and using plus waiting. The gap between the first two is shaded and labelled "spare". | Places not in SDA use is an upper bound on vacancy. |
| 2 | "Each new place brings about 0.24 people into use, almost all within three quarters." | Bars for the lag profile, quarter 0 to 4, with the range across specifications as a band. | Region-level, not dwelling-level. |
| 3 | "High Physical Support has 2.58 places per participant with need, up from 1.81." | Four small lines, places per participant by category, with the 1.0 and 1.5 bands shaded. A dashed line shows the uncategorised need spread pro-rata. | A fifth of need has no category. |
| 4 | "About a third of the pipeline enrols each year; the March 2026 rule removed at least 1,723 dwellings." | Pipeline places as an area, with new-build enrolments per quarter as bars. The break is a vertical rule labelled "36-month rule". | Pipeline before and after March 2026 is not comparable. |
| 5 | "31 regions have more people waiting than spare places, down from 60; 6,497 spare places sit where everyone waiting could already be housed." | Two lines: regions short, and spare beyond local waiting. | Waiting is counted where the participant lives. |

The x-axis always runs over the quarters a series actually exists. Participants
start in December 2023, need by category in December 2024. The chart says so
rather than drawing a gap as zero.

### 2. Region page, one per SA4

Laid out top to bottom for a phone:

```
┌──────────────────────────────────────┐
│ VIC · Melbourne - West               │
│ "1,039 places not in SDA use (62%),  │
│  up 227 in a year. At last year's    │
│  take-up, 61 quarters to fill."      │  ← written from data
├──────────┬──────────┬────────────────┤
│ Spare    │ Waiting  │ Pipeline       │  ← three tiles, each with a
│ 1,039    │ 187      │ 943 places     │    sparkline of its own series
├──────────┴──────────┴────────────────┤
│ Places · using SDA · using + waiting │  ← main chart, 13 quarters
│ ────────────────────────────────     │
├──────────────────────────────────────┤
│ By design category   (need as        │
│ recorded ▾ / spread pro-rata)        │  ← the one toggle kept
│ ┌────────┐┌────────┐                 │
│ │ IL  ▼  ││ HPS ▲  │   small multiples: places vs need,
│ └────────┘└────────┘   7 quarters, with a status chip:
│ ┌────────┐┌────────┐   short / balanced / long /
│ │ Robust ││ FA  ▼  │   drifting up / drifting down /
│ └────────┘└────────┘   reverses / too few
├──────────────────────────────────────┤
│ Where it sits nationally: rank 1 of  │
│ 88 on spare places; links to league  │
└──────────────────────────────────────┘
```

- Each chart has a **"Show the numbers"** disclosure that expands to a data table.
  That is the accessible source, and it is also where anyone checking a figure
  will look.
- **Two columns from 720px**, one below. The small multiples go 2 × 2 on a phone
  and 4 × 1 on a desktop.
- **State pages become a filter, not a page.** The league table filters by
  state, and the region search lists regions grouped by state. The NDIA's
  state subtotals stay available on Australia's page as a small table.

### 3. League table: persistent against temporary

One row per SA4. Sorting by any column gives a straight ranking. It is filterable
by state, and on a phone it stacks as cards.

| Column | Source | Why |
| --- | --- | --- |
| Region | — | Links to the region page |
| Spare places, and share of places | latest quarter | Scale |
| Change in spare over a year, with a sparkline | 11 quarters | Direction |
| Quarters to fill at recent take-up | analysis Q1 | The lease-up question in one number |
| Waiting beyond local spare | latest quarter | Where the shortage still is |
| Waiting vs spare over 11 quarters | analysis Q4 | *always short / short → covered / covered → short / always covered / reverses* |
| IL · HPS · Robust · FA | analysis Q4 | Four status chips per row, over 7 quarters |

Two presets above the table answer the questions directly. Each is a sort plus
a filter, not a separate view:

- **Persistently long**: sorted by spare, where it is growing.
- **Persistently short**: rows marked "always short", sorted by waiting beyond spare.

The status chips use the explorer's band colours plus a glyph (▼ ◆ ▲ ↗ ↘ ↔), so
colour is never the only channel.

## What I'd drop, and why

| Current feature | Proposal | Reason |
| --- | --- | --- |
| **Housing Hub vacancy view** | **Drop.** Keep `vacancies.json` and its README section as a record. | A single snapshot, from a listings platform whose coverage varies about tenfold between states (4% of spare capacity in the ACT, 39% in Victoria). It cannot be put on a time axis. The panel's places-not-in-use series now does its job over time. |
| **SA3 pages** | **Drop.** | No places can be formed at SA3, so there is no spare, ratio or absorption, which is everything the new interface is about. The median SA3 also has too few participants to trend. |
| **Substitution toggle** | **Drop the toggle, keep the fact.** HPS and FA sit side by side in the small multiples, and a one-line note under them gives the pooled HPS + FA ratio. | It doubles every category view for one relationship. Pooled, the pattern does not change: HPS is long and FA short in the same places. |
| **Dwelling conversion in the surplus view** | **Drop.** Everything is in places and people. | It is an approximation (the average places per dwelling, rounded down) layered on the derived places. The time views never need dwellings. |
| **Region heat grid** | **Drop.** The league table's four category chips replace it. | The grid shows one quarter's ratio for 88 × 6 cells. The chips show seven quarters' persistence per cell, which is the question now asked. |
| Choropleth map *(not on your list)* | **Defer.** Not in v1. | A map of one quarter's ratio adds little once the league table ranks and filters. If wanted later, it could map one time measure, such as change in spare. |
| Surplus threshold (1.05 / 1.20), "Basic places first" reading, band tally, build-type and resident-count bars | **Drop.** | Each answered a single-quarter question. The pro-rata vs as-recorded toggle is the only sensitivity the time analysis needs, because it is the only one that moves a category result (HPS). |

What stays: search, deep links, the ▼ ◆ ▲ band language, the 1.0 / 1.5 bands,
text written from data, light and dark themes, phone-width layout and the smoke
test.

## How it would be built

- **Where.** A subfolder, `time/`, containing `index.html`, `app.js` and
  `styles.css`. It is served at `…/SDA-data-visualisation/time/` alongside the
  current explorer, which stays at the root untouched until we agree to swap.
- **Data.** `scripts/build_timeseries.py` reads `panel.csv` and
  `analysis.json` and writes `data/timeseries.json`. It holds, for national,
  state and 88 SA4s, 13 quarters of: places, in use, waiting, spare, pipeline
  places, and places and need by category. It also carries the per-region
  analysis results (quarters to fill, statuses, ranks). Roughly 150 KB, one
  fetch, pure standard library, rebuilt byte for byte in the tests like
  everything else.
- **Charts.** Hand-written SVG, as the explorer's are, with no chart library.
  Every chart has a text headline written from the data and a data table behind
  a disclosure. Line ends are labelled directly, instead of a legend where there
  are three lines or fewer.
- **Styling.** The explorer's tokens (`--ground`, `--ink`, the band colours) are
  copied into `time/styles.css`. Theming works the same way: system preference,
  with a `data-theme` override. Fonts are unchanged.
- **Routes.**
  - `#/` is Australia.
  - `#/region/VIC - Geelong` is a region page.
  - `#/league` and `#/league?state=VIC&preset=short` are the league table.
- **Tests.** `tests/smoke.js` gains the three routes at 390px and desktop, both
  themes, and the toggle, failing on page errors and horizontal scroll as now.
  A Python test checks that each headline's numbers match `analysis.json`.

### Milestones, each a reviewable PR

1. **Data file and the Australia page.**
2. **Region pages.**
3. **League table and presets.**
4. **Accessibility and phone polish.** Then a decision on replacing the root
   site. If we replace it, the old explorer moves to `classic/` so existing links
   keep working, or bare links redirect.

## Decisions I need from you

1. **The drop list.** Are you happy to lose all five of your candidates, plus the
   map (deferred) and the single-quarter sensitivities?
2. **The one toggle.** Keep "need as recorded / spread pro-rata" as a visible
   toggle, or show pro-rata only as a dashed line and note?
3. **State pages.** Is a filter plus a small subtotal table enough, or do you
   want state pages?
4. **Audience and tone.** Should headlines be neutral, as drafted ("places grew by
   9,503; people using SDA by 2,547"), or state the conclusion ("the surplus is
   lasting")? Neutral is safer for a public site. The conclusion is clearer
   for policy readers.
