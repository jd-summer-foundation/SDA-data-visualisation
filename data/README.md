# Source data

Inputs to `scripts/extract_vacancies.py`. **Nothing in this directory is
served.** GitHub Pages publishes `docs/` only, and the vacancy export carries
provider email addresses and phone numbers, so it must stay outside it. The
extractor reads from here and writes aggregates — never per-listing rows, never
a contact detail — to `docs/data/vacancies.json`.

| File | Source | As at |
| --- | --- | --- |
| `List_SDA_20260824.csv` | Housing Hub SDA vacancy export | 24 August 2026 |
| `australian_postcodes.csv` | Postcode / locality to statistical-area concordance | see below |

The NDIA Supplement P workbook that `scripts/extract_sda.py` reads is not kept
here; it is published quarterly and passed to the script directly.

## `List_SDA_20260824.csv`

2,321 rows, one per vacancy listing. `Status` is `Enrolled` on every row, so it
carries no information. `Vacancy` is a count of vacant places, and `Building
Type` names the dwelling's resident capacity — comparing the two is what
separates a wholly empty dwelling from a spare room, which is the measure the
vacancy view is built around.

Two postcodes are wrong in the export and are corrected in the extractor's
`SUBURB_OVERRIDES`: Doreen is 3754 (not 3794) and Oxenford is 4210 (not 4201).
Worth reporting upstream.

## `australian_postcodes.csv`

18,559 rows, one per postcode/locality pair, used to place each listing in an
SA4 and SA3.

**Read `sa4name` and `sa3name`. Do not use the `*_2021` columns.**
`SA4_NAME_2021`, `SA3_NAME_2021` and `SA4_CODE_2021` are corrupt in this file:
they hold only 21 distinct SA4 names across 17,546 populated rows, and they
misassign badly — postcode 2000 BARANGAROO comes out as `Sydney - Sutherland`.
The older `sa4name`/`sa3name` columns are correct for the same rows
(`Sydney - City and Inner South` / `Sydney Inner City`).

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
