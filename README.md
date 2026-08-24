# SDA Data Visualisation

Tooling to make the NDIA's quarterly **Supplement P: Specialist Disability
Accommodation** readable — and in particular to answer the question the
published workbook cannot: *is a given SDA design category undersupplied in a
given region?*

The proposal this supports is written up as a separate document; this repository
holds the extraction and derivation step it depends on.

## Why the workbook needs a script

Supplement P is internally consistent and complete, but four structural features
make it hard to use directly:

1. **Supply and demand live in different tables.** Dwellings by design category
   are in Table P.5; participants needing each design category are in Table P.10.
2. **They are counted in different units.** Supply is dwellings, demand is
   participants. A five-resident group home is one dwelling but five places.
3. **The cross-tabs are flattened.** Tables P.11, P.12 and P.16 squash two
   dimensions into a single header row of up to 74 columns, e.g.
   `House, 3 residents - Robust`.
4. **The only trend data is not in any cell.** Figure P.1's thirteen quarters of
   national history exist solely inside embedded chart XML and the figure's
   accessibility description.

Two file-format quirks also need handling: the NDIA publishes in **Strict
OOXML**, which `openpyxl` refuses until the namespace URIs are rewritten, and
Excel parks filtered-out chart series in the `c15` extension namespace, where a
naive parse silently merges several series into one.

## The derivation

Because each column header in P.11/P.12/P.16 names its own resident capacity,
multiplying the dwelling count by that capacity and summing by design category
yields **places** — resident capacity — which is directly comparable with a
participant count.

This is measurable rather than assumed. The NDIA publishes places for new builds
only, in Table P.7, which lets the same arithmetic be calibrated: run over P.11
it lands exactly on **94.0% of 485 values**, with a largest single gap of 7
places and a net bias of **+0.08%** across SA4 totals. It is not an identity,
because a dwelling's enrolled maximum residents can be lower than its dwelling
type implies.

That margin is tight enough to trust the same arithmetic on existing and legacy
stock (P.12) and on the pipeline (P.16), where no published places figure exists.
Where P.7 does exist, the extractor uses the NDIA's own figure rather than the
derived one. `calibrate_derivation` recomputes this on every build, so a change
in the workbook's shape shows up immediately.

Sanity checks that hold for the 2025-26 Q4 file: summing the 88 SA4 regions gives
14,235 enrolled dwellings and 25,658 participants with an SDA need, both matching
Figure P.1's national totals exactly.

## The explorer

The repository root is a static site — one HTML page, one stylesheet, one
script, one JSON file. It renders the same profile at every level:

- **Australia** — all 88 SA4 regions combined
- **Each state and territory** — the NDIA's own published subtotals
- **Each of the 88 SA4 regions**
- **Each of the 336 SA3 regions** — dwellings and need only, see below

Every profile shows enrolled dwellings, enrolled places, participants with an
identified need, places per participant, and the pipeline, broken down by design
category — plus build-type and resident-count breakdowns, and a sortable table
of the child regions that doubles as an undersupply ranking.

### As enrolled, or allowing substitution

The category table and chart carry a toggle between two readings of supply.

**As enrolled** (the default) counts each dwelling under the single design
category it is enrolled and certified against. This is the factual view, and it
is what every raw figure in Supplement P describes.

**Allowing substitution** asks a different question: who could physically live
here? High Physical Support is defined cumulatively on top of Fully Accessible —
an HPS dwelling must meet every Fully Accessible requirement plus ceiling-hoist
provision, 950mm door openings and backup power — so HPS stock can house someone
assessed for Fully Accessible. The reverse does not hold, and Improved
Liveability (sensory and cognitive) and Robust (resilience) sit on different
axes, so nothing substitutes for them.

Donor stock passes down as a **waterfall, not a sum**: HPS keeps enough places to
cover its own need, and only the surplus counts towards Fully Accessible. Adding
the two outright would count the same places against two different demands.
Nationally that takes Fully Accessible from 0.53 to 1.78, and cuts the SA4
regions below 1.0 from 68 to 26 — those 26 are where the shortfall is real
rather than an artefact of how stock is categorised.

Two caveats the interface states on screen: a dwelling is still *enrolled* in one
category, and SDA payment follows the participant's funded category — so this
models physical suitability, not what a provider would be paid.

Deep links work: `#national`, `#state:VIC`, `#sa4:ACT - Australian Capital Territory`.

## Usage

```sh
pip install openpyxl
python3 scripts/extract_sda.py <Supplement_P_*.xlsx>
```

Writes `data/sda.json` (~1 MB) containing:

| Key | Contents |
| --- | --- |
| `meta` | as-at date, category lists, source notes, derivation calibration |
| `national_trend` | 13 quarters × 6 series recovered from Figure P.1 |
| `national_summary` | places, need, pipeline and ratio per design category |
| `geographies` | one record per geography, all four levels, identical shape |

Each geography carries `categories` (per design category: `enrolled_dwellings`,
`enrolled_places`, `pipeline_dwellings`, `pipeline_places`,
`participants_with_need`, `places_per_participant`), `totals`, `build_types` and
`max_residents`, plus `parent` for the hierarchy.

To preview locally, from the repository root:

```sh
python3 -m http.server 8000
```

## Publishing on GitHub Pages

The site lives at the repository root and needs no build step, so Pages serves
it as-is:

- **Settings → Pages → Source** = `Deploy from a branch`
- **Branch** = `main`, folder = `/ (root)`

`index.html` at the root takes precedence over `README.md`, so Pages serves the
explorer rather than rendering this file. `.nojekyll` stops Pages running the
files through Jekyll on the way.

Live at `https://jd-summer-foundation.github.io/SDA-data-visualisation/`.

Re-running the extractor and pushing the updated `data/sda.json` is all a new
quarter needs — the site picks it up with no other change. If a refresh appears
to show stale numbers, it is browser cache; a hard reload clears it.

Note that a Pages site on a public repository is public, whether or not the
repository itself is. If the data should stay internal for now, keep the
repository private and preview locally until you decide to publish.

## Reading the numbers honestly

- **`places_per_participant` is not unmet demand.** Enrolled places include
  places already occupied, and participants with an SDA need include people
  already living in SDA. The measure shows mismatch of *mix* — a participant
  assessed as needing Fully Accessible but housed in a Basic dwelling appears on
  both sides, in different categories. Never label it "shortfall".
- **A fifth of demand has no design category.** 4,991 of 25,658 participants
  (19.5%) sit in P.10's "Missing" column. Large enough to move any ratio.
- **Suppressed cells are not zeros.** Small counts publish as `<11`, `<5`, `n/a`
  (54 cells in this file). `parse_value` returns `None` plus the disclosed
  ceiling so they are never summed as zero.
- **The pipeline is an intention, not a forecast.** The NDIA states pipeline
  dwellings may never be enrolled, may be enrolled in a different category, and
  may already be enrolled but not yet removed from the data.
- **Table P.1 is not joinable.** It keys on NDIA Service Districts, not SA4;
  P.2 and P.3 key on State only. None of them appear in the explorer.
- **SA3 has no places figure.** The dwelling-form cross-tabs the derivation
  depends on are published at SA4 and above only, so no places or ratio can be
  formed at SA3. Dwelling counts and participant need still are.
- **Basic and Multi-Design Category have no demand counterpart.** Neither is
  issued as an eligibility decision, so only the four categories in
  `COMPARABLE_CATEGORIES` support a supply-versus-demand comparison.
- **SA boundaries changed** from 2011 to 2016 definitions in March 2023, which
  limits comparability with earlier supplements.
