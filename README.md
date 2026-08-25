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

`docs/` is a static site — one HTML page, one stylesheet, one script, one JSON
file. It renders the same profile at every level:

- **Australia** — all 88 SA4 regions combined
- **Each state and territory** — the NDIA's own published subtotals
- **Each of the 88 SA4 regions**
- **Each of the 336 SA3 regions** — dwellings and need only, see below

Every profile shows enrolled dwellings, enrolled places, participants with an
identified need, places per participant, and the pipeline, broken down by design
category — plus build-type and resident-count breakdowns, and a sortable table
of the child regions that doubles as an undersupply ranking.

Deep links work: `#national`, `#state:VIC`, `#sa4:ACT - Australian Capital Territory`.

## The vacancy view

A toggle in the masthead switches the same page between two views of the same
region. **Supply & demand** is the profile above. **Vacancy** answers a question
Supplement P cannot: what is actually sitting empty right now, and is it whole
dwellings or single rooms?

The distinction is the point. A spare room in an occupied five-resident group
home is a matching problem. A wholly empty two-bedroom house is stranded
capital. Nationally the split is close to even — 2,161 vacant places in
dwellings standing completely empty against 1,432 single rooms — and which one a
region has is almost entirely a function of dwelling size, not design category.

Vacancy deep links carry the view in front of the geography:
`#vacancy!national`, `#vacancy!sa4:VIC - Melbourne - West`. Bare geography links
are unchanged and still open the supply view, so nothing already published
breaks.

The two datasets are independent — one is the NDIA's enrolment and eligibility
record, the other a listings platform — which makes the vacancy view a check on
the supply one. Across the 127 SA4-and-design-category combinations with enough
enrolled places to form a rate, the two agree in direction: rank correlation
**&rho; = 0.40**, and **0.39** with Victoria excluded. The third of the market
with the most places per participant runs **19.3%** vacant against **10.5%** for
the third with the fewest.

Which comparison that correlation is made *across* matters more than the
coefficient, and it cuts both ways:

- **Within a region it is stronger: &rho; = 0.50** (70 points across the 20 SA4s
  carrying three or more categories, permutation p = 0.0005). This is the
  load-bearing version. Listing propensity — the caveat stamped across the whole
  view — is a property of the *region*: a provider base that advertises more
  inflates every category it holds alike, so it cancels when the comparison
  stays inside one SA4. The relationship surviving that control is much better
  evidence than the pooled figure.
- **Within a design category it largely disappears.** Comparing regions inside
  one category, only High Physical Support (&rho; = 0.30) and Robust
  (&rho; = 0.46) show it; Improved Liveability and Fully Accessible are
  indistinguishable from zero.

So it supports reading a high `places_per_participant` as genuine slack in a
market. It does not support predicting any single region's vacancy from it.

The extractor recomputes all of this on every build and asserts that at least 15
regions carry three or more categories, so a thinner future export fails rather
than publishing a coefficient derived from a handful of regions.

## Usage

The supplement extractor:

```sh
pip install openpyxl
python3 scripts/extract_sda.py <Supplement_P_*.xlsx>
```

Writes `docs/data/sda.json` (~1 MB) containing:

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

To preview locally:

```sh
cd docs && python3 -m http.server 8000
```

## Vacancy data

```sh
python3 scripts/extract_vacancies.py data/List_SDA_20260824.csv \
        --postcodes data/australian_postcodes.csv
```

Reads the Housing Hub export, the postcode concordance and `docs/data/sda.json`,
and writes `docs/data/vacancies.json` (~680 KB), fetched lazily so the supply
view still loads one file:

| Key | Contents |
| --- | --- |
| `meta` | as-at dates, listing and place totals, how each listing matched, price-band cut-points, the bridge correlation |
| `regions` | one profile per geography id — `national`, `state:*`, `sa4:*`, `sa3:*` — keyed to match `sda.json` |
| `bridge` | SA4 &times; design category: vacancy rate against `places_per_participant` |

Each profile carries `depth` (the whole/rooms/multi-dwelling split), plus
`by_capacity`, `by_category`, `by_form`, `by_feature`, `price_bands` and
`top_suburbs`. Zero-valued keys are dropped to keep the file small; read an
absent key as 0. The last four are emitted only where a region has at least 20
listings — the median SA3 has five, where a price-band or with/without split is
noise.

**The whole-versus-rooms derivation.** `Building Type` names the dwelling's
resident capacity and `Vacancy` counts vacant places. Where the count reaches
capacity, the dwelling is counted as wholly empty; below it, the difference is
rooms in a dwelling someone already lives in. 112 listings report *more*
vacancies than the dwelling can hold — nine in a "1 residents" villa — which can
only mean one listing covering several dwellings; that surplus is held in a
third bucket rather than assigned to either. The three sum to 3,753, asserted on
every build.

**Region assignment.** The export carries no statistical geography, so each
listing is placed by postcode and suburb. All 2,321 resolve: 2,247 on an exact
postcode and suburb, 31 on the postcode alone, and 43 on a hand-checked
correction. Vacancy appears in 86 of the 88 SA4 regions. See `data/README.md`
for the concordance's quirks — in particular that its `*_2021` columns are
corrupt and must not be used.

Sources live in `data/`, outside `docs/`, because the export carries provider
contact details and Pages serves `docs/` publicly. Only aggregates are written
to `docs/`; no per-listing row and no contact detail ever reaches it.

## Publishing on GitHub Pages

The site needs no build step, so Pages can serve `docs/` directly:

1. Merge this branch into `main` (Pages serves from a branch, so the files must
   be on the branch you select).
2. In the repository, open **Settings → Pages**.
3. Under **Build and deployment**, set **Source** to `Deploy from a branch`.
4. Set **Branch** to `main` and the folder to `/docs`, then **Save**.
5. Wait a minute or two for the first deploy, then open
   `https://jd-summer-foundation.github.io/SDA-data-visualisation/`.

Re-running the extractor and pushing the updated `docs/data/sda.json` is all a
new quarter needs — the site picks it up with no other change. If a refresh
appears to show stale numbers, it is browser cache; a hard reload clears it.

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

### And for the vacancy view

- **Housing Hub is a listings platform, not a vacancy census.** Only vacancies a
  provider chose to advertise appear, and providers advertise at very different
  rates. Victoria shows 17.3% of its enrolled places as vacant against New South
  Wales' 6.0% — a gap far too large to be real, and better read as a difference
  in how much of each market lists here. Compare categories and dwelling types
  within a region freely; compare regions against each other only with this in
  mind.
- **Every rate straddles two dates.** Vacancies are as at 24 August 2026, the
  enrolled places they are divided by as at 30 June 2026. A rate is suppressed
  where fewer than 50 enrolled places sit under it.
- **No rate below SA4.** The dwelling cross-tabs the places derivation needs are
  published at SA4 and above only, so SA3 pages show counts and the
  whole-versus-rooms split but no rate. 30 listings sit in a locality with no SA3
  counterpart in the supplement and are counted at SA4 and above only.
- **Design category and dwelling features do not predict whole-dwelling
  vacancy.** Fitting a logistic model to the 1,910 shared dwellings in the
  export, once dwelling size and form are held constant, design category, onsite
  overnight assistance, a breakout room and price all lose any independent
  association with whether a vacancy is the whole dwelling (|z| &le; 1.6).
  Dwelling size is doing nearly all the work. The category and feature charts are
  description, not explanation.
- **A region with no listings is not a region with no vacancy.** Two SA4s and
  108 SA3s have nothing listed; the vacancy view says so explicitly rather than
  showing a zero.
- **The bridge correlation is not an artefact of its shared term.** Enrolled
  places appears on both axes — numerator of `places_per_participant`,
  denominator of the vacancy rate — which can manufacture correlation out of
  noise. Simulating a world where vacancy is a constant 15.2% independent of the
  ratio puts the measured &rho; at **+0.007** (sd 0.091), so the shared term
  introduces no material bias in either direction and the observed 0.40 sits
  4.3 standard deviations above that null.
