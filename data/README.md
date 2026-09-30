# Data

Inputs to the extractors, and the JSON they produce.

**Everything here is published.** GitHub Pages serves the repository root, so
this directory is part of the site — `data/sda.json` and `data/vacancies.json`
are fetched by `app.js` at exactly these paths, and the CSVs beside them are
reachable too. `.nojekyll` disables Jekyll, so there is no underscore-prefixed
escape hatch either. Nothing can be committed here on the assumption that it is
private.

| File | Source | As at |
| --- | --- | --- |
| `List_SDA_20260824.csv` | Housing Hub SDA vacancy export | 24 August 2026 |
| `australian_postcodes.csv` | Postcode / locality to statistical-area concordance | — |
| `asgs_2021_sa2.csv` | ABS ASGS Edition 3 allocation file, Statistical Areas Level 2 – 2021 (`SA2_2021_AUST.xlsx`) | July 2021 |
| `supplements/` | NDIA Supplement P, one workbook per quarter | June 2023 – June 2026 |
| `sda.json` | Built by `scripts/extract_sda.py` from `supplements/Supplement_P_SDA_2025-26_Q4.xlsx` | 30 June 2026 |
| `vacancies.json` | Built by `scripts/extract_vacancies.py` from the two CSVs | 24 August 2026 |
| `panel/` | Built by `scripts/extract_panel.py` (SA4) and `scripts/extract_panel_sa3.py` (SA3, placed by `asgs_2021_sa2.csv`) from every workbook in `supplements/` | June 2023 – June 2026 |
| `pricing/` | NDIA Pricing Arrangements for SDA, every version 2021-22 v1.0 to 2026-27 v1.0, the 2026-27 Pricing Schedule, and the location factors and base amounts `scripts/extract_pricing.py` extracts from them | 1 July 2021 – 2026-27 |
| `abs/` | Reduced ABS files: building approvals by SA2, 2021 Census medians by SA3 and SA2, SA3 adjacency. Rebuilt from the git-ignored `raw/` (see `raw/MANIFEST.md`) | see below |

## Both CSVs are reduced before committing

Each is cut to the columns its extractor actually reads. This is what makes them
safe to publish, and it also takes the concordance from 8.8 MB to 1.0 MB.

`List_SDA_20260824.csv` keeps `Location`, `Building Type`, `Max Price Per Room`,
`SDA Design Category`, `Vacancy`, `Has Fire Sprinklers`, `Has Breakout Room` and
`Onsite Overnight Assistance`. It **drops `Name`, `Email`, `Phone` and
`Website 1`–`5`** — provider contact details that must not be published — and
`Status`, which reads `Enrolled` on all 2,321 rows and carries no information.

`australian_postcodes.csv` keeps `postcode`, `locality`, `state`, `sa3name` and
`sa4name` of its 41 columns.

To redo it after a fresh export:

```python
import csv, io
KEEP = ["Location", "Building Type", "Max Price Per Room", "SDA Design Category",
        "Vacancy", "Has Fire Sprinklers", "Has Breakout Room", "Onsite Overnight Assistance"]
rows = list(csv.DictReader(io.open(src, encoding="utf-8-sig")))
with open(dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=KEEP); w.writeheader()
    for r in rows: w.writerow({k: r[k] for k in KEEP})
```

Reducing changes nothing downstream: rebuilding from the cut files reproduces
`vacancies.json` byte for byte.

## `supplements/`

Past quarterly editions of NDIA Supplement P, committed so the longitudinal
analysis can be rebuilt end to end — they are public NDIA publications, so
serving them from the site is no concern. One file per quarter, named as the
NDIA publishes them (`Supplement_P_SDA_<financial year>_Q<n>`).

Editions up to 2024-25 Q3 carry an `.xlsb` extension and later ones `.xlsx`,
but none is Excel Binary: every one is an XML workbook, and all but 2025-26 Q2
are **Strict OOXML**. That one is ordinary transitional OOXML, which the
extractor's namespace rewrite passes through unchanged. Their
table layouts are not identical: worksheet counts run from 19 (2024-25 Q1) to
25 (2022-23 Q4), so each edition's tables need mapping rather than assuming the
current `SA4_SHEETS`.

2024-25 Q3 is 14 MB where the others are about 1 MB: one worksheet expands to
85 MB of XML, most likely formatting applied across a very large empty range.
Expect it to read slowly row by row, and stop at the last populated row rather
than trusting the sheet's reported dimensions.

The thirteen editions run from 2022-23 Q4 (June 2023) to 2025-26 Q4 (June 2026),
all published after the NDIA changed its SA boundary definitions in March 2023
(see the main README). The last is the edition `sda.json` is built from:

```sh
python3 scripts/extract_sda.py data/supplements/Supplement_P_SDA_2025-26_Q4.xlsx
```

and the tests rebuild it from there and compare byte for byte.

`scripts/extract_panel.py` reads all thirteen into `panel/`, identifying each
table by its caption and header rather than its number. `panel/VALIDATION.md`
records, edition by edition, which sheet holds which table, what reconciles and
where the series breaks. Worth knowing before reading any one edition by hand:

- **Participant tables change three times.** Need by design category is
  published only in 2022-23 Q4 and 2023-24 Q1 (as legacy-CRM "seeking SDA", a
  different concept) and from 2024-25 Q2. The status table has three schemes,
  and only the last two split SDA in use from eligible-not-using.
- **2023-24 Q2 and Q3 mis-caption their SA3 Table P.18** as the old "seeking
  SDA" table; the header shows it is the not-using table.
- **Five editions (2022-23 Q4 – 2023-24 Q4) repeat a region row** in the
  cross-tabs: Wide Bay, Newcastle and Lake Macquarie, Toowoomba. The repeats are
  identical.
- **2024-25 Q2's Figure P.1 prose** labels the eligible-not-using series "active
  participants with SDA supports" and omits SDA in use; its chart has both.
- **Figure P.1 in 2023-24 Q2 and Q4** ends a quarter before the edition's own
  date.
- **2025-26 Q1–Q3 P.7** publishes zero new-build places for Wheat Belt, where
  P.11 lists six new-build dwellings.

## `List_SDA_20260824.csv`

2,321 rows, one per vacancy listing. `Vacancy` counts vacant places and
`Building Type` names the dwelling's resident capacity — comparing the two is
what separates a wholly empty dwelling from a spare room, which is the measure
the vacancy view is built around.

Two postcodes are wrong in the export and are corrected in the extractor's
`SUBURB_OVERRIDES`: Doreen is 3754 (not 3794) and Oxenford is 4210 (not 4201).
Worth reporting upstream.

## `asgs_2021_sa2.csv`

The ABS allocation of every ASGS 2021 SA2 to its SA3, SA4 and state, 2,473
rows. `extract_panel_sa3.py` reads the SA3 and SA4 columns to place Supplement
P's SA3s (which it names without codes or parent); the SA2 rows and areas are
kept for joining SA2-level ABS data (Census, building approvals) later. Public
ABS data under CC BY 4.0.

Reduced from the workbook to eight of its sixteen columns, dropping the GCCSA,
Australia and change-flag columns and the linked-data URI:

```python
import csv, openpyxl
KEEP = ["SA2_CODE_2021", "SA2_NAME_2021", "SA3_CODE_2021", "SA3_NAME_2021",
        "SA4_CODE_2021", "SA4_NAME_2021", "STATE_NAME_2021", "AREA_ALBERS_SQKM"]
rows = openpyxl.load_workbook(src, read_only=True).worksheets[0].iter_rows(values_only=True)
header = next(rows)
with open(dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh, lineterminator="\n"); w.writerow(KEEP)
    for r in rows:
        d = dict(zip(header, r)); w.writerow(["" if d[k] is None else d[k] for k in KEEP])
```

## `australian_postcodes.csv`

One row per postcode/locality pair, used to place each listing in an SA4 and SA3.

**Its SA3 names predate ASGS 2021**, which Supplement P uses: 31 of Supplement
P's 336 SA3s are not in it (Molonglo, Camden, Hervey Bay, …). Vacancy listings
in those SA3s get the older SA3 name, or none. The SA3 panel does not use it;
it places SA3s from `asgs_2021_sa2.csv`.

**The `*_2021` columns are corrupt — which is why they are not among the columns
kept.** `SA4_NAME_2021`, `SA3_NAME_2021` and `SA4_CODE_2021` held only 21
distinct SA4 names across 17,546 populated rows in the original file, and
misassigned badly: postcode 2000 BARANGAROO came out as `Sydney - Sutherland`.
The older `sa4name`/`sa3name` columns are correct for the same rows
(`Sydney - City and Inner South` / `Sydney Inner City`) and are what the join
reads.

Three further quirks, all handled in `build_concordance`:

- Three SA4s carry pre-2016 names. `Fitzroy` and `Mackay` are plain renames;
  `Western Australia - Outback` was genuinely split in 2016 and is resolved from
  the SA3 — Kimberley and Pilbara north, the rest south.
- One row is simply wrong: GILBERTON 4871, labelled `North Queensland` with a
  Gold Coast SA3. It is dropped along with the external territories, because its
  SA4 name is unknown to Supplement P.
- Border postcodes carry the *neighbouring* state, so 60 NSW-flagged rows sit in
  `Gold Coast` and 49 in Victoria's `Hume`. The join is therefore on SA4 name
  alone — unique in Supplement P except for the `Other` bucket, which no listing
  reaches — and each listing's state is taken from its matched SA4 rather than
  its address.

## `pricing/`

The NDIA's SDA pricing documents, committed whole: they are public NDIA
publications. Both are Word files, read with `zipfile` and `xml.etree`.

| File | Source |
| --- | --- |
| `*.docx` (14) | NDIS Pricing Arrangements for Specialist Disability Accommodation, every version from 2021-22 v1.0 to 2026-27 v1.0, under the NDIA's own filenames (ndis.gov.au; fetched by browser, since ndis.gov.au refuses scripted requests). `DOCUMENTS` in the extractor lists each with its version. |
| `ndis-pricing-schedule-for-sda-2026-27.docx` | NDIS Pricing Schedule for SDA 2026-27 (ndis.gov.au) |
| `location_factors.csv` | edition, version, valid-from and release dates (read from each title page), SA4, stock type (All / New build / Existing / Legacy), building type, factor to two decimals |
| `base_amounts.csv` | edition, stock type, building type, design category, breakout room, sprinklers, OOA, GST treatment, annual base amount per participant |

`python3 scripts/extract_pricing.py` rebuilds both CSVs. The Arrangements are
the source; the Schedule is read the same way and must agree on every factor
and amount. Tables are found by caption, since the two number them differently
(location factors: Tables 23–24 in the Arrangements, 35–36 in the Schedule).
The existing-and-legacy factor table names two SA4s by their pre-2016 names,
`QLD - Fitzroy` and `QLD - Mackay`; `SA4_RENAMES` maps them, and any other
unmatched name fails the build. Building types are named as Supplement P's
Table P.11 names them, so the two join on the label.

Before 1 July 2023 one factor table served every stock type (stock type
`All`); from then new builds, whenever first enrolled, have their own table
and existing and legacy stock keep the other. Four things are corrected
explicitly, and anything else unmatched fails the build:

- `SA4_RENAMES`: the retired names above, and "Hunter Valley excluding
  Newcastle" (2021-22, 2022-23).
- `SA4_SPLITS`: 2021-22 and 2022-23 still publish one factor for
  `WA - Western Australia - Outback`, the pre-2016 SA4 since split into
  Outback (North) and (South); it applies to both.
- `LABEL_FIXES`: in 2023-24 v3.0's new-build table the words "Hunter Valley
  exc Newcastle" slipped from their row into the Murray row; the figures stayed
  put, and each row equals v1.4's.
- Some existing-stock tables drop trailing zeros (`0.9`, `1`); factors are
  written to two decimals.

Two copies of 2023-24 v1.0 were published; they differ only in page numbers,
and the extractor checks that their tables agree. The file published as
"v1.3 (1)" is version 1.4 by its title page. Base amounts are extracted for
2026-27 only: earlier editions lay the base-price tables out differently.

## `abs/`

Small files reduced from ABS downloads kept in the git-ignored `raw/`.
`raw/MANIFEST.md` records the URL, release, geography edition, licence and
checksum of each download. All ABS data is CC BY 4.0.

| File | From | Rebuilt by |
| --- | --- | --- |
| `building_approvals_sa2.csv` | Building Approvals, Australia: small-area CSVs by SA2, ASGS 2021, FY 2021-22 to 2026-27 FYTD (July releases 2022–2026) | `scripts/reduce_abs.py` |
| `census_2021_sa3.csv`, `census_2021_sa2.csv` | 2021 Census GCP DataPacks (SA3 and SA2, all of Australia), tables G02 and G01 | `scripts/reduce_abs.py` |
| `sa3_adjacency.csv` | ASGS Edition 3 SA3 boundaries, `SA3_2021_AUST_SHP_GDA2020.zip` | `scripts/build_sa3_adjacency.py` |
| `sal_sa3_dwellings.csv` | ASGS 2021 allocation files `MB_2021_AUST.xlsx` and `SAL_2021_AUST.xlsx`, and 2021 Census Mesh Block Counts | `scripts/reduce_abs.py` |

`building_approvals_sa2.csv` keeps dwelling units approved in **new**
residential buildings, all sectors (`type_work` 1, `own_sector` 9), as houses
(`type_bld` 110) and other residential (150), summed to quarters; the partial
latest quarter is dropped. SA2s with nothing approved in a quarter are omitted,
so absence means zero. The ABS's own state (`1`–`8`) and national (`0`) rows
are kept beside the SA2s, and both the reducer (monthly) and the tests
(quarterly) check that SA2s sum to their state and states to the nation.

The Census files keep `Median_mortgage_repay_monthly`, `Median_rent_weekly`,
`Median_tot_hhd_inc_weekly` (G02) and `Tot_P_P` (G01), by ASGS 2021 code. A
median of 0 means not published (NSW - Blue Mountains - South, 8 residents).

`sa3_adjacency.csv` lists every pair of the 336 Supplement P SA3s that share
at least one boundary edge (a corner alone does not count), each side's SA4,
whether the pair crosses an SA4 boundary, and the shared border length in km.

`sal_sa3_dwellings.csv` has one row per Suburb and Locality (SAL 2021) × SA3
intersection, with its 2021 Census dwellings and persons summed from Mesh
Blocks. It is the weighting for carrying locality data to SA3.

## `vgv/`

`vacant_land_by_locality.csv`: Valuer-General Victoria's annual median sale
price of vacant residential land, by locality, 2015–2025, from the Victorian
Property Sales Report time series `land-by-suburb-2015-2025.xlsx`
(land.vic.gov.au; listed on data.vic.gov.au under CC BY 4.0; fetched by
browser, kept in `raw/vgv/`). Rebuilt by `scripts/reduce_vgv.py`. Localities
are joined to SAL 2021 by name within Victoria; five VGV names that are not ABS
localities (estates such as Sanctuary Lakes) are left out by name, and any
other unmatched name fails the build. Only the latest vintage is read, because
VGV revises earlier years between releases. VGV marks some medians `^` or `*`,
kept in `flag`. The workbooks do not define them; *A Guide to Property Values
2025* (explanatory notes, printed p. 10) does: "^ Fewer than 10 sales in that
year. * Value was carried forward from the previous year due to zero sales in
the represented year." The analysis never uses `*` medians. Years are calendar
years, and vacant land is VGV's Vacant Residential Land: home sites or surveyed
lots under 4,000 m² (Guide, pp. 3, 11–12).
`scripts/analyse_land_value.py` uses it in `panel/LAND_VALUE_VIC.md`.

## `panel/newbuild_types_sa4.csv` and the location-factor report

`scripts/extract_newbuild_types.py` writes Table P.11's new-build dwellings by
building type, design category and SA4, every quarter, which `panel.csv` sums
over building types. Zero cells are omitted. `scripts/feasibility_location_factor.py`
writes `LOCATION_FACTOR_FEASIBILITY.md`, `location_factor_feasibility.json` and
`location_factor_pairs.csv` (each cross-SA4 adjacent pair with the factor on
each side) from committed files alone.
