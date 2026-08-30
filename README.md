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
category — plus build-type and resident-count breakdowns, a sortable table
of the child regions that doubles as an undersupply ranking, and the region grid
described below.

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

So the two are reported as **one pooled category**, `High Physical Support +
Fully Accessible` — one body of stock against one body of demand. Nationally
that pool holds 16,622 places against 11,587 participants, a ratio of **1.44**,
and 31 of the 88 SA4 regions sit below 1.0. Read separately and as enrolled,
Fully Accessible is below 1.0 in 78 of 87 regions, so most of that gap is an
artefact of how stock is categorised rather than stock that does not exist.

An earlier version passed the surplus down as a waterfall instead — HPS keeping
enough to cover its own need, the remainder counting towards Fully Accessible.
That credited the borrower without debiting the donor, so the same places backed
two comfortable-looking ratios at once, and three of the four categories were
identical in both readings.

Pooling has its own flaw, stated here rather than hidden: it counts Fully
Accessible stock against High Physical Support need, which is not physically
possible, since the substitution only runs one way. In this file it never
flatters a region — no region has High Physical Support below 1.0 while the pool
reads 1.0 or above, because Fully Accessible is short almost everywhere and so
has no surplus to lend upwards. It is also the more conservative of the two
readings: against the waterfall it moves 14 regions down a band and none up.
Worth re-checking when the numbers move.

Two caveats the interface states on screen: a dwelling is still *enrolled* in one
category, and SDA payment follows the participant's funded category — so this
models physical suitability, not what a provider would be paid.

### The map

Australia and each state carry a choropleth of the 88 SA4 regions, coloured by
places per participant for whichever design category you pick, and following the
same enrolled/substitution toggle as the tables. Australia gets insets for the
five capitals whose Greater Capital City area holds more than one SA4 — between
them Sydney, Melbourne, Brisbane, Perth and Adelaide hold 43 of the 88 regions,
and at national scale they are a few pixels each. A state map is a crop of the
same national geometry with its neighbours greyed for context, so no separate
per-state boundaries are stored. SA3 has no map, because it has no ratio.

The scale is **diverging**, because both ends are a problem. Red is below 1.0,
green is the balanced band from 1.0 to 1.5, and two blues sit above it, breaking
at 2.5. A red-to-green scale treats more as always better, which reported High
Physical Support — 77 of 88 regions above 1.0, and 49% of its places in regions
at 3.0 or above, in real markets rather than tiny ones — as uniformly healthy.

1.5 and 2.5 are where the mass actually sits. High Physical Support puts 29
regions between them and 35 above; Robust 15 and 24; Fully Accessible and
Improved Liveability barely reach the band at all. Robust's extremes are mostly
small denominators — its top three regions have 7, 7 and 4 participants — which
is why the two blues stay distinct rather than merging into one. The breaks are
fixed across categories so the maps stay comparable, and the ratio chips in the
tables use the same cuts.

Colour is doing the work here, so it is not the only channel: the legend carries
the same ▼ ◆ ▲ glyphs as the tables, every region states its ratio and both
underlying counts on hover and to a screen reader, each is a real link reachable
by keyboard, and the ranked table below the map remains the accessible source of
the same numbers. A region with no ratio is hatched rather than coloured, so
"not calculable" cannot be misread as "low".

Two things the map cannot show, and says so on screen: colour is the ratio and
not the size of the market, so four participants and nine hundred can read the
same; and a category-specific map has nowhere to put the 4,991 participants
(19.5%) whose need carries no design category.

### The region grid

The map answers one design category at a time and the child-region table one
level at a time, so neither shows a category running short across the country
while another runs long in the same places. The grid at the foot of every supply
profile puts every SA4 against every comparable category at once: regions down
the side, design categories across the top, places per participant in the cell.

The grid carries no supply-mode toggle. Both readings are columns instead:
`HPS`, `FA` and `HPS+FA` sit side by side, so the question the panel exists for
— can High Physical Support stock cover the Fully Accessible shortfall in *this*
region? — is a comparison across a row rather than a switch to flip and
remember. Spelled out those three headers are eleven words over a grid that
already scrolls sideways, so they are acronyms, expanded in each header's title
and in the note under the grid. The category table and the map keep their own
copies of the toggle, which remain one piece of state wired once.

States arrive closed. Eighty-eight SA4 rows is more than a reader can hold at
once, and the state rows carry the NDIA's own subtotals, so the grid arrives as
eight readable rows and the regions are expanded a state at a time — which also
lets the closed grid be sized by its own content, narrower than the panel it
sits in, rather than spending the difference on a region column with nothing in
it. The expand control shares a row with a link that navigates away, so it gets
a 26px target: a miss used to leave the page rather than open the state.

It is scoped to where the reader is — all 88 regions nationally, and below that
the regions of the state they are in, with their own row marked — and each
state's regions sit under a row carrying the NDIA's own published subtotals for
that state, not an average of the regions beneath it. Sorting a column reorders
the regions inside each state and the states against each other, rather than
dissolving the grouping the panel exists for.

Cells are filled with the map's six-class scale, on the map's breaks, so a cell
here and a region there are always the same colour for the same figure; the two
panels share one legend for that reason. The full fill rather than the tables'
tinted chip is what makes a short column or a long region visible without
reading a figure — eighty-eight rows of chips read as a pale wash. Colour is
again not the only channel: every cell keeps the ▼ ◆ ▲ glyph, states its ratio
and its verdict to a screen reader, and a region with no ratio is hatched. The
text colour on each of the six fills is a token of its own, because the scale's
lightness ordering inverts between the light and dark themes.

### The band tally

Beneath the grid, a count of how many regions sit in each band, over the same
regions the grid covers. The grid raises a question it cannot state — how
widespread is this? — and at 30 June 2026 the answer is not close: Improved
Liveability is short in 75 of the 88 regions and Fully Accessible in 78, while
High Physical Support is above the balanced band in 64 and far above it in 35,
largely the same regions.

Its rows are the grid's own columns, in the grid's own order, built from the
same `HEAT_COLS` list, so the two panels cannot come to disagree about what is
counted or drift apart in how it is arranged. That puts the pooled reading
directly beneath the two readings it combines, which is where the comparison
wants it: pooling takes Fully Accessible from short in 89% of regions to short
in 35%, since much of that shortfall is stock that exists and is enrolled as
High Physical Support, while Improved Liveability does not move at all, at 85%
either way. The pooled row is indented and tinted rather than listed as a peer,
because it is a second reading of two of the rows above it and not a category
in its own right.

**It is weighted by participants by default**, because a region is not a person.
Counting each region once, whatever its size, answers how widespread a shortfall
is; weighting each by the participants it holds in that category answers how many
people it reaches. A switch in the panel head moves between the two, and it moves
the whole table — the band columns and the bar together, since region counts
beside a participant-weighted bar would be incoherent. An earlier version showed
both readings at once as two stacked bars per row and was simply too dense to
read; one reading at a time, with the other a click away, is the same information
in a panel a person can take in.

Weighted is the default because it is the honest reading rather than the softer
one. Population is deliberately not the weight: it is not in the file, but the
deeper objection is that SDA need does not track headcount — it follows disability
prevalence and where services were historically built. Participants with need is
already the denominator of the ratio being banded, which makes it the natural
weight, and the supplement publishes it per category. It must be the *category's
own* participants rather than the region's total need: Robust is between 1.6% and
20% of a region's need, so a region-total weight would misstate that row badly.
Coverage costs nothing — no cell of the 352 is suppressed and none carries need
without a ratio, so no participant falls out of the tally.

Under the weighted reading each row is a share of its own category's
participants, so the denominators differ down the column; the caption under each
bar carries that row's total, which is what makes it legible. The percentage
leads each cell and the absolute follows it quietly, because the share is what
carries the comparison between rows. A genuine zero reads as an em dash rather
than 0%, which keeps the No ratio column — all zeroes when weighted, since no
participant sits in a cell without a ratio — from looking like a column of
measurements.

Switching readings is mostly reassurance. The two shortfalls that carry the story
barely move — Improved Liveability short in 85% of regions and for 83% of its
participants, Fully Accessible 89% and 89% — so a crowd of small regions is not
manufacturing them. Where the readings diverge it is the oversupply that grows:
High Physical Support is short in 12% of regions but for only 3% of its
participants, and far above the need recorded against it in 40% of regions
holding 46% of them. Counting regions understates it. Robust is the one row to
treat carefully, and not for the expected reason: its far-over regions hold a
median of 16 participants, but the category is small nationally (1,754), so it is
the category rather than the regions that is thin.

Both region grids — this one and the surplus grid — carry a **By state /
Ranked** switch. Grouped is the default and the organising idea: regions sit
under their state, sorting reorders them inside it, and the state row carries
the NDIA's own subtotal. But sorting inside groups, however it is sorted, can
never put the largest region in one state beside the largest in another, so the
question the grid most obviously raises — *which regions, nationally?* — is the
one it cannot answer. **Ranked** drops the grouping for a flat 1-to-n list on
whichever column is sorted, each row carrying its own position and its own
state. Making it a mode rather than a side-effect of sorting means neither
reading has to compromise, and the sort carries across the switch in both
directions.

Deep links work: `#national`, `#state:VIC`, `#sa4:ACT - Australian Capital Territory`.

## The surplus view

A ratio says whether a region is long or short. It cannot say by how much,
because it has no units: 4.22 places per participant in Geelong High Physical
Support is the same figure whether it stands for four spare places or four
hundred. The **Surplus** view converts the long end of that measure into the
unit the question is actually asked in — dwellings standing past the need
recorded against them — as a map and a region grid, both reading the same
figures.

Three choices define it, and each understates rather than overstates.

**A tolerance, not a target.** Stock is only counted once a region is past
`threshold × need`, so a region carrying a place or two of headroom is not
reported as holding surplus. Two thresholds are offered — **1.05** and **1.20**
— and 1.05 is the default because it is the weaker claim: anything it does not
clear is not worth arguing about. Neither cut is a position on how much headroom
a market should carry; they exist so a finding can be tested against the softer
reading.

**Substitution is directional, and the donor is debited.** High Physical Support
is defined cumulatively on top of Fully Accessible, so HPS stock can house
someone assessed for FA. Allowing substitution, each region's HPS stock is made
to cover its own FA shortfall first, and those places are *subtracted* from it:

```
fa_short   = max(0, T × FA_need − FA_places)
HPS excess = max(0, HPS_places − T × HPS_need − fa_short)
FA excess  = max(0, FA_places  − T × FA_need)
```

This is not the waterfall removed from the supply view. That one credited Fully
Accessible without debiting High Physical Support, so the same places backed two
comfortable-looking ratios at once. Here a place cannot be spare and in use
simultaneously. Across the pooled pair the total is identical to the supply
view's pooling — the waterfall only decides which category it is booked against,
which is the whole point of the panel: *how much HPS is still spare after
covering every FA shortfall in the same region?* Fully Accessible cannot
substitute upwards, and nothing substitutes for Improved Liveability or Robust,
so those three columns do not move with the toggle.

**Dwellings are approximated.** The supplement publishes places against
participants and dwellings against nothing, so the only bridge between them is
the region's own average — its enrolled places over its enrolled dwellings, in
that category. Surplus places are divided by that average and rounded **down**.
A region whose surplus sits in its larger dwellings is overstated by this and
one whose surplus sits in its singles understated; hovering a cell shows the
average used. Where a region records places but no dwellings in a category, the
average falls back to its state and then to Australia.

At 1.05, allowing substitution, that gives **3,671 surplus dwellings** across
the 88 regions: 2,515 High Physical Support, 904 Robust, 142 Improved
Liveability and 110 Fully Accessible. At 1.20 it is 2,951. Read as enrolled —
HPS not asked to cover anything — the 1.05 figure is 5,317. The shape of the
finding does not depend on the cut.

Two things separate this view from the rest of the site.

State and national rows are **summed from their SA4 regions**, not read from the
NDIA's published subtotals as every other panel does. Surplus is regional by
definition: a subtotal nets a shortfall in one region against a surplus in
another and reports the difference, as though nowhere were short. Those rows
therefore will not reconcile with the same rows elsewhere on the site, and the
grid says so beneath itself.

The map's scale is **sequential rather than diverging**. Zero is the reference
and everything else runs one way, so a ramp is the honest shape where the ratio
map's red/green/blue would imply the far end is a second kind of problem. Zero
is its own class and reads as near-blank, which is what makes the regions
holding stock findable without reading a figure — and it is why the map is
deliberately nothing like the ratio map in colour: the two must not be
mistakeable for one another. It defaults to all four categories combined and
can be focused on any one of them.

A blank region on this map is not a well-supplied region. It may be badly short;
the surplus map cannot say, and the ratio map is where that question is asked.
Nor is a surplus dwelling an empty one — enrolled places include places already
occupied. What this measures is a mismatch of **mix**, stock enrolled in a
category beyond the need recorded against that category in that region. The
Vacancy view is the one that reads listed availability. The pipeline is excluded
throughout: it would add to every surplus shown, and add most where the surplus
is already largest.

The grid carries the same **By state / Ranked** switch as the supply-view region
grid, described above. Ranked is how the question "which SA4s hold the most
overstock in absolute terms" gets answered: at 1.05 read as enrolled, that is
Melbourne - West on 511 dwellings, then Melbourne - South East on 277, Adelaide
- North on 265, Logan - Beaudesert on 210 and Perth - South East on 208. Rank is
position under the current sort and nothing more — sort by the column you mean,
because a region high on one is often nowhere on another. The "state rows are
summed from their regions" caveat does not apply while ranked, there being no
state rows, and the note under the grid says so.

### Enrolled now, or with the pipeline

The panel's own figures answer *how much stock is standing spare*. The question
they raise and cannot settle is *which way is this going*, so the view carries a
second reading: **With pipeline** adds each category's `pipeline_places` to its
enrolled places and recomputes everything against the same recorded need.

The answer is not close. At 1.05 allowing substitution, national surplus goes
from **3,671 dwellings to 8,778** — and **88% of the national pipeline, 5,782 of
6,549 dwellings, is going into regions that already hold surplus**. High Physical
Support alone is 7,210 pipeline places on 13,173 enrolled, a 55% increase in the
most oversupplied category, against 1,243 Improved Liveability places on a
3,073-place Improved Liveability shortfall. The pipeline does not correct the
mismatch; it compounds it. Melbourne - West goes from 497 surplus dwellings to
967, Melbourne - South East from 228 to 556, Adelaide - North from 225 to 509.

Two details make this reading defensible rather than merely alarming.

Dwellings are converted on the **combined** average — `(enrolled_places +
pipeline_places) / (enrolled_dwellings + pipeline_dwellings)` — because the
supplement publishes both sides of the pipeline and a pipeline dwelling is not
the same size as an enrolled one. Where `pipeline_dwellings` is suppressed the
enrolled average stands in. And a suppressed `pipeline_places` makes the whole
category unknown rather than counting as nothing coming: 8 of the 88 regions are
affected, and reading them as zero would report a thin region as safe on the
strength of a number nobody published.

The grid carries a **Pipeline dwellings** column in both readings — it is the
fact that makes the two worth comparing — and the tiles carry both figures at
once, so the before and after sit together without a click.

It is a scenario, and the page says so at its loudest. It counts every pipeline
dwelling as built and enrolled in the category it is listed against, and holds
demand at what is recorded today. The NDIA states that pipeline dwellings may
never be enrolled, may be enrolled in a different design category, and that some
already-enrolled dwellings remain in the pipeline data, overstating it; from
March 2026 dwellings that have not progressed within 36 months are removed.
Demand will move too, and Supplement P publishes no projection of it, so nothing
here offsets the new stock. Read it as the direction the intended stock points,
and the enrolled reading as the one that is true.

Deep links carry the view: `#surplus!sa4:VIC - Geelong`.

## The vacancy view

A switch in the masthead moves the same page between three views of the same
region. **Supply & demand** is the profile above. **Surplus** is the panel just
described. **Vacancy** answers a question
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

### Boundaries

The map's geometry is built separately, and only needs rebuilding when the ABS
changes the boundaries — not every quarter.

```sh
npm i mapshaper
python3 scripts/build_geometry.py [data/boundaries/SA4_....shp]
```

Writes `data/sa4-geometry.json` (~250 KB): one national view plus five capital
insets, as SVG path strings already projected to Australian Albers (EPSG:3577,
equal-area, so the outback regions do not read as more important for being
large) and keyed by the same region ids as `data/sda.json`.

Boundaries are the ABS **Statistical Area Level 4, ASGS Edition 4 (2026),
GDA2020**, © Commonwealth of Australia, [CC BY 4.0][abs]. The shapefile itself is
a build input and is not committed — put it in `data/boundaries/`, the same way
the Supplement P workbook is passed in.

Supplement P publishes no SA4 code, so the join is by region name. The build
asserts it is exactly one-to-one in both directions and checks the per-state
counts, and fails rather than quietly dropping a region off the map. It holds
for the 2025-26 Q4 file: all 88 regions match, and the edition's own change
flags report no real SA4 altered in 2026.

[abs]: https://creativecommons.org/licenses/by/4.0/

To preview locally, from the repository root:

```sh
python3 -m http.server 8000
```

## Vacancy data

```sh
python3 scripts/extract_vacancies.py data/List_SDA_20260824.csv \
        --postcodes data/australian_postcodes.csv
```

Reads the Housing Hub export, the postcode concordance and `data/sda.json`, and
writes `data/vacancies.json` (~680 KB), fetched lazily so the supply view still
loads one file:

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

**The published site is the repository root, so every committed file is public.**
There is no unserved directory to hide a source file in — `.nojekyll` means even
an underscore-prefixed one would be served. So the two CSVs in `data/` are cut
down to the columns the extractor actually reads before they are committed: the
vacancy export keeps eight columns and loses `Name`, `Status`, `Email`, `Phone`
and `Website 1`–`5`; the concordance keeps five of its 41. Rebuilding from the
reduced files reproduces `data/vacancies.json` byte for byte, and no provider
contact detail exists anywhere in the repository. See `data/README.md`.

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
- **A high ratio is not automatically good.** Above about 1.5 a region holds
  more places than the need recorded against them, which is its own kind of
  market failure. The scale says so rather than running green all the way up.
- **The map shows a ratio, not a volume.** Two regions with wildly different
  numbers of participants can carry the same colour. The counts are in every
  region's tooltip and in the table beneath it.
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
