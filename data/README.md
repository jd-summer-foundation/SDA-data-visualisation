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
| `sda.json` | Built by `scripts/extract_sda.py` from NDIA Supplement P | 30 June 2026 |
| `vacancies.json` | Built by `scripts/extract_vacancies.py` from the two CSVs | 24 August 2026 |

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

The NDIA Supplement P workbook is not kept here; it is published quarterly and
passed to `scripts/extract_sda.py` directly.

## `List_SDA_20260824.csv`

2,321 rows, one per vacancy listing. `Vacancy` counts vacant places and
`Building Type` names the dwelling's resident capacity — comparing the two is
what separates a wholly empty dwelling from a spare room, which is the measure
the vacancy view is built around.

Two postcodes are wrong in the export and are corrected in the extractor's
`SUBURB_OVERRIDES`: Doreen is 3754 (not 3794) and Oxenford is 4210 (not 4201).
Worth reporting upstream.

## `australian_postcodes.csv`

One row per postcode/locality pair, used to place each listing in an SA4 and SA3.

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
