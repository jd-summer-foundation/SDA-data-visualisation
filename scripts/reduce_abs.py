#!/usr/bin/env python3
"""Reduce the ABS downloads in raw/ to the small files committed in data/abs/.

The raw downloads (building-approvals CSV zips, Census DataPacks) are far too
large to publish and are not committed; raw/MANIFEST.md records where each came
from. This keeps only what the location-factor analysis reads:

  building_approvals_sa2.csv  dwelling units approved in new residential
                              buildings, all sectors, by SA2 and quarter:
                              houses and other residential. The ABS's own
                              state and national rows are kept beside the
                              SA2s, so the sums can be re-checked from the
                              committed file.
  census_2021_sa3.csv         2021 Census G02 medians and G01 persons, by SA3.
  census_2021_sa2.csv         the same, by SA2.

Before writing, every month is checked: SA2s must sum to their state's
published total, and states to the national total, for houses and for other
residential. Any mismatch fails the build.

Usage:  python3 scripts/reduce_abs.py [raw/abs] [-o data/abs]
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# One zip per financial year, each from the July release that first
# completes that year (see raw/MANIFEST.md).
APPROVALS = [
    "jul-2022_Statistical_Area_2_Australia_2021-2022.zip",
    "jul-2023_Statistical_Area_2_Australia_2022-2023.zip",
    "jul-2024_Statistical_Area_2_Australia_2023-24.zip",
    "jul-2025_Statistical_Area_2_Australia_2024-25.zip",
    "jul-2026_Statistical_Area_2_Australia_2025-26.zip",
    "jul-2026_Statistical_Area_2_Australia_2026-27_FYTD.zip",
]
NEW_WORK, ALL_SECTORS = "1", "9"
BUILDINGS = {"110": "houses", "150": "other_residential"}
QUARTER_END = {3: "03-31", 6: "06-30", 9: "09-30", 12: "12-31"}

CENSUS = {
    "SA3": "2021_GCP_SA3_for_AUS_short-header.zip",
    "SA2": "2021_GCP_SA2_for_AUS_short-header.zip",
}
G02 = {"Median_mortgage_repay_monthly": "median_mortgage_monthly",
       "Median_rent_weekly": "median_rent_weekly",
       "Median_tot_hhd_inc_weekly": "median_household_income_weekly"}
G01 = {"Tot_P_P": "persons"}


def quarter_of(month: str) -> str:
    """'2023-05' -> '2023-06-30'."""
    year, m = int(month[:4]), int(month[5:7])
    end = ((m - 1) // 3 + 1) * 3
    return f"{year}-{QUARTER_END[end]}"


def read_zip_csv(path: Path, suffix: str):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(suffix)]
        if len(names) != 1:
            raise ValueError(f"{path.name}: expected one *{suffix}, found {names}")
        with z.open(names[0]) as fh:
            yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))


def reduce_approvals(raw: Path, sa2_state: dict[str, str]):
    """{(quarter, code): {houses, other_residential}} and the months read."""
    monthly = defaultdict(lambda: defaultdict(float))
    months_by_file = {}
    for name in APPROVALS:
        months = set()
        for row in read_zip_csv(raw / "building_approvals" / name, ".csv"):
            row = {k.lower(): v for k, v in row.items()}
            if row["type_work"] != NEW_WORK or row["own_sector"] != ALL_SECTORS:
                continue
            measure = BUILDINGS.get(row["type_bld"])
            if not measure:
                continue
            key = (row["app_month"], row["sa2_code"])
            if measure in monthly[key]:
                raise ValueError(f"{name}: duplicate {key} {measure}")
            monthly[key][measure] = float(row["dwl"])
            months.add(row["app_month"])
        overlap = months & {m for ms in months_by_file.values() for m in ms}
        if overlap:
            raise ValueError(f"{name} repeats months {sorted(overlap)}")
        months_by_file[name] = sorted(months)

    # The sum checks, month by month.
    months = sorted({m for m, _ in monthly})
    for month in months:
        states = defaultdict(lambda: defaultdict(float))
        for (m, code), vals in monthly.items():
            if m != month or len(code) != 9:
                continue
            if code not in sa2_state:
                raise ValueError(f"{month}: SA2 {code} is not in asgs_2021_sa2.csv")
            for k, v in vals.items():
                states[sa2_state[code]][k] += v
        for measure in BUILDINGS.values():
            national = monthly[(month, "0")][measure]
            state_sum = 0.0
            for code in "12345678":
                published = monthly[(month, code)][measure]
                state_sum += published
                if states[code][measure] != published:
                    raise ValueError(f"{month} {measure}: SA2s in state {code} sum to "
                                     f"{states[code][measure]}, published {published}")
            if state_sum != national:
                raise ValueError(f"{month} {measure}: states sum to {state_sum}, "
                                 f"national {national}")
    # Keep only complete quarters.
    per_quarter = defaultdict(set)
    for m in months:
        per_quarter[quarter_of(m)].add(m)
    complete = {q for q, ms in per_quarter.items() if len(ms) == 3}
    quarterly = defaultdict(lambda: defaultdict(float))
    for (m, code), vals in monthly.items():
        q = quarter_of(m)
        if q in complete:
            for k, v in vals.items():
                quarterly[(q, code)][k] += v
    dropped = sorted(q for q in per_quarter if q not in complete)
    return quarterly, months, dropped


def write_approvals(out: Path, quarterly):
    def order(key):
        q, code = key
        return (q, len(code), code)
    with open(out / "building_approvals_sa2.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["quarter", "region", "houses", "other_residential"])
        for key in sorted(quarterly, key=order):
            vals = quarterly[key]
            h, o = vals.get("houses", 0.0), vals.get("other_residential", 0.0)
            if len(key[1]) == 9 and h == 0 and o == 0:
                continue  # an SA2 with nothing approved; absence means zero
            w.writerow([key[0], key[1], f"{h:g}", f"{o:g}"])


def reduce_census(raw: Path, level: str, out: Path):
    path = raw / "census" / CENSUS[level]
    code = f"{level}_CODE_2021"
    g02 = {r[code]: r for r in read_zip_csv(path, f"G02_AUST_{level}.csv")}
    g01 = {r[code]: r for r in read_zip_csv(path, f"G01_AUST_{level}.csv")}
    if set(g01) != set(g02):
        raise ValueError(f"{level}: G01 and G02 cover different regions")
    columns = [code.lower()] + list(G02.values()) + list(G01.values())
    with open(out / f"census_2021_{level.lower()}.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for c in sorted(g02):
            w.writerow([c] + [g02[c][k] for k in G02] + [g01[c][k] for k in G01])
    return len(g02)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("raw", nargs="?", default=str(ROOT / "raw" / "abs"))
    ap.add_argument("-o", "--out", default=str(ROOT / "data" / "abs"))
    args = ap.parse_args(argv)
    raw, out = Path(args.raw), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with open(ROOT / "data" / "asgs_2021_sa2.csv", newline="") as fh:
        sa2_state = {r["SA2_CODE_2021"]: r["SA2_CODE_2021"][0] for r in csv.DictReader(fh)}
    quarterly, months, dropped = reduce_approvals(raw, sa2_state)
    write_approvals(out, quarterly)
    print(f"approvals: {months[0]} to {months[-1]}, {len(months)} months, sums check; "
          f"incomplete quarters dropped: {dropped or 'none'}", file=sys.stderr)
    for level in CENSUS:
        n = reduce_census(raw, level, out)
        print(f"census {level}: {n} regions", file=sys.stderr)


if __name__ == "__main__":
    main()
