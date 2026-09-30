#!/usr/bin/env python3
"""Reduce Valuer-General Victoria's vacant-land medians to a small committed file.

VGV's Victorian Property Sales Report publishes, for each locality with enough
sales, the annual median sale price of vacant residential land. This reads the
latest time-series workbook (raw/vgv/annual/land-by-suburb-2015-2025.xlsx,
see raw/MANIFEST.md) and writes data/vgv/vacant_land_by_locality.csv.

Localities are joined to ABS Suburbs and Localities (SAL 2021) by name, within
Victoria (data/abs/sal_sa3_dwellings.csv). A name that matches no SAL fails the
build unless it is listed in NOT_LOCALITIES with the reason.

Only the latest vintage is read: VGV revises earlier years between releases
(Aintree 2021 is $390,000 in the 2013-2023 file and $430,000 in this one).
VGV marks some medians with '^' or '*'. The workbooks do not define either
(both are probably small-sample warnings), so the marker is kept in the
`flag` column for the analysis to include or exclude; the preliminary
current-year column is not read.

Usage:  python3 scripts/reduce_vgv.py [raw/vgv] [-o data/vgv]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "annual/land-by-suburb-2015-2025.xlsx"

# VGV reports these as localities, but none is an ABS locality (SAL 2021):
# each is an estate or part of a gazetted locality. Placing them would mean
# guessing which SAL holds the sales, so they are left out.
NOT_LOCALITIES = {
    "BALCOMBE": "estate name, not an ABS locality",
    "COWES WEST": "not an ABS locality",
    "MERINDA PARK": "estate name, not an ABS locality",
    "SANCTUARY LAKES": "estate name, not an ABS locality",
    "WALLAN EAST": "not an ABS locality",
}


def sal_names(path: Path) -> dict[str, str]:
    """Victorian SAL name (upper case, state suffix dropped) -> SAL code."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["state"] != "VIC":
                continue
            name = re.sub(r"\s*\(Vic\.\)$", "", r["sal_name"]).upper()
            if out.get(name, r["sal_code"]) != r["sal_code"]:
                raise ValueError(f"two Victorian SALs named {name!r}")
            out[name] = r["sal_code"]
    return out


def read_medians(path: Path):
    """[(locality, year, median, flag)] from the 2015-2025 workbook.

    Years head every other column; the column after each year holds VGV's
    marker ('^' or '*') for that year's median.
    """
    import openpyxl
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True)
                .worksheets[0].iter_rows(values_only=True))
    header = next(r for r in rows if r and str(r[0] or "").strip() == "Locality")
    years = [(i, y) for i, y in enumerate(header) if isinstance(y, int)]
    if [y for _, y in years] != list(range(2015, 2026)):
        raise ValueError(f"unexpected year columns {[y for _, y in years]}")
    out = []
    start = rows.index(header) + 1
    for r in rows[start:]:
        label = " ".join(str(r[0] or "").split())
        if not label:
            continue
        if label != label.upper():
            raise ValueError(f"unexpected row {label!r}")
        for i, y in years:
            cell = r[i]
            mark = str(r[i + 1] or "").strip()
            text = str(cell if cell is not None else "").strip()
            if text in ("", "-", "NA"):
                continue
            m = re.fullmatch(r"(\d+)\s*([*^]?)", text)
            if not m:
                raise ValueError(f"{label} {y}: unreadable median {text!r}")
            if mark not in ("", "*", "^"):
                raise ValueError(f"{label} {y}: unknown marker {mark!r}")
            flag = m.group(2) or mark
            out.append((label, y, int(m.group(1)), flag))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("raw", nargs="?", default=str(ROOT / "raw" / "vgv"))
    ap.add_argument("-o", "--out", default=str(ROOT / "data" / "vgv"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sal = sal_names(ROOT / "data" / "abs" / "sal_sa3_dwellings.csv")
    medians = read_medians(Path(args.raw) / SOURCE)
    localities = sorted({m[0] for m in medians})
    unknown = [n for n in localities if n not in sal and n not in NOT_LOCALITIES]
    if unknown:
        raise ValueError(f"VGV localities matching no Victorian SAL: {unknown}")
    stale = sorted(n for n in NOT_LOCALITIES if n not in localities or n in sal)
    if stale:
        raise ValueError(f"NOT_LOCALITIES entries no longer needed: {stale}")
    with open(out / "vacant_land_by_locality.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["locality", "sal_code_2021", "year", "median_price", "flag"])
        for label, year, value, flag in sorted(medians):
            if label in NOT_LOCALITIES:
                continue
            w.writerow([label, sal[label], year, value, flag])
    print(f"{len(localities)} localities, {len(localities) - len(NOT_LOCALITIES)} matched to SAL; "
          f"{len(NOT_LOCALITIES)} left out", file=sys.stderr)


if __name__ == "__main__":
    main()
