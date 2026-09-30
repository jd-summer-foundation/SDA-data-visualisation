#!/usr/bin/env python3
"""New-build SDA dwellings by building type, design category and SA4, every quarter.

panel.csv sums Supplement P's Table P.11 cross-tab over building types; the
location-factor analysis needs the building types themselves, because the
factor is set per building type. This reads P.11 from every edition in
data/supplements/ with extract_panel's table reader (identified by caption,
not number) and writes it long.

Usage:  python3 scripts/extract_newbuild_types.py [data/supplements] [-o data/panel]

Writes newbuild_types_sa4.csv: as_at, sa4, building_type, design_category,
dwellings. Region rows only (states and the national row are dropped);
zero cells are omitted, so absence means zero; suppressed cells are written
empty with their flag. Building types are named
as P.11 names them, which is also how data/pricing/location_factors.csv
names them.
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_panel import STATES, read_edition  # noqa: E402
from extract_sda import DWELLING_LABEL  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def rows_from(edition, sa4_ids):
    table = edition["tables"]["newbuild_detail"]
    out = []
    for label, row in table["rows"].items():
        if label in STATES or label.lower().startswith(("national", "total", "other")):
            continue
        geo = "sa4:" + label
        if geo not in sa4_ids:
            raise ValueError(f"{edition['edition']}: P.11 region {label!r} is not a panel SA4")
        for column, value in row["values"].items():
            if column.strip().lower() == "total":
                continue
            m = DWELLING_LABEL.match(column)
            if not m:
                raise ValueError(f"unparsed P.11 heading {column!r}")
            btype = column[:column.rindex(" - ")].strip()
            btype = " ".join(btype.split())
            out.append((edition["as_at"], geo, btype, m.group("category").strip(), value,
                        row["flags"].get(column, "")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("supplements", nargs="?", default=str(ROOT / "data" / "supplements"))
    ap.add_argument("-o", "--out", default=str(ROOT / "data" / "panel"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    with open(ROOT / "data" / "panel" / "sa3_sa4.csv", newline="") as fh:
        sa4_ids = {r["sa4"] for r in csv.DictReader(fh)}
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for path in sorted(Path(args.supplements).glob("Supplement_P_SDA_*")):
            edition = read_edition(path, Path(tmp), level="SA4")
            got = rows_from(edition, sa4_ids)
            regions = {r[1] for r in got}
            if regions != sa4_ids:
                raise ValueError(f"{edition['edition']}: P.11 lacks {sorted(sa4_ids - regions)}")
            rows.extend(got)
            print(f"{edition['edition']}: {len(got)} cells", file=sys.stderr)
    with open(out / "newbuild_types_sa4.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["as_at", "sa4", "building_type", "design_category", "dwellings", "flag"])
        for as_at, geo, btype, cat, value, flag in sorted(rows):
            if value == 0 and not flag:
                continue  # absence means zero
            w.writerow([as_at, geo, btype, cat, "" if value is None else f"{value:g}", flag])


if __name__ == "__main__":
    main()
