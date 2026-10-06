#!/usr/bin/env python3
"""Reduce NSW Valuer General bulk land values to locality medians.

The NSW Valuer General supplies, on request, one CSV per council area with a
record per property: its address, zone, area and land value at each of five
1 July base dates. Those records are property-level and stay in the
git-ignored raw/nsw_vg/ (see raw/MANIFEST.md). This writes only locality
aggregates, data/nsw_vg/land_value_by_locality.csv: for each ABS Suburb and
Locality (SAL 2021) and base date, parcel counts and median land values.

Measures, each over parcels with a land value at that base date:

  urban        land value per m2, parcels zoned R1-R4 of 100 to 3,999 m2,
               strata schemes included (one record per scheme, carrying the
               whole site's area and value)
  urban_plain  the same, counting only values on basis 6A(1), the ordinary
               land value; other bases (14C, 14E, 14G, ...) are left out
  urban_lot    land value per parcel, R1-R4, 100 to 3,999 m2, strata schemes
               excluded (a scheme's value covers many dwellings)
  wider        land value per m2, parcels zoned R1-R5 or RU5 of 100 m2 or more,
               no upper limit on area

A median is written only where at least MIN_PARCELS parcels carry it; the
count is always written. Zones are those in force at the snapshot, not at
each base date.

Localities are joined to SAL 2021 by name within NSW. A VG locality whose name
is shared by several NSW SALs (the ABS adds the council area, e.g. "Dural
(Hornsby - NSW)") is matched on its council area. Every other name must be
listed below with a reason, in PLACED (matched by hand) or NOT_LOCALITIES
(left out); any other unmatched name fails the build, and so does a listed
name that no longer needs listing.

Usage:  python3 scripts/reduce_nsw_vg.py [raw/nsw_vg] [-o data/nsw_vg]
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = "LV_20260901"
BASE_DATES = ["01/07/2025", "01/07/2024", "01/07/2023", "01/07/2022", "01/07/2021"]
URBAN = {"R1", "R2", "R3", "R4"}
WIDER = URBAN | {"R5", "RU5"}
MIN_AREA, MAX_AREA = 100.0, 4000.0   # m2; the upper limit matches VGV's vacant-land class
MIN_PARCELS = 10
PLAIN_BASIS = "6A(1)"

# Matched by hand: (district, VG locality) -> SAL 2021 name, with the evidence.
SPELLING = "VG spelling of the SAL; same postcode in the ABS postcode concordance"


def _same_postcode(part):
    return f"locality spans council areas; same postcode as the {part} part"


PLACED = {
    ("BATHURST REGIONAL", "KINGS PLAINS"): ("Kings Plains (Blayney - NSW)", _same_postcode("Blayney")),
    ("BEGA VALLEY", "GREENLANDS"): ("Greenlands (Snowy Monaro Regional - NSW)", _same_postcode("Snowy Monaro")),
    ("CABONNE", "SPRING HILL"): ("Spring Hill (Orange - NSW)", _same_postcode("Orange")),
    ("COWRA", "LYNDHURST"): ("Lyndhurst (Blayney - NSW)", _same_postcode("Blayney")),
    ("GOULBURN MULWAREE", "MAYFIELD"): ("Mayfield (Queanbeyan-Palerang Regional - NSW)",
                                        _same_postcode("Queanbeyan-Palerang")),
    ("GREATER HUME", "ROSEWOOD"): ("Rosewood (Snowy Valleys - NSW)", _same_postcode("Snowy Valleys")),
    ("LISMORE", "BROADWATER"): ("Broadwater (Richmond Valley - NSW)", _same_postcode("Richmond Valley")),
    ("LIVERPOOL PLAINS", "GOWRIE"): ("Gowrie (Singleton - NSW)", _same_postcode("Singleton")),
    ("MAITLAND", "LAMBS VALLEY"): ("Lambs Valley (Singleton - NSW)", _same_postcode("Singleton")),
    ("MOREE PLAINS", "ROCKY CREEK"): ("Rocky Creek (Gwydir - NSW)", _same_postcode("Gwydir")),
    ("SNOWY MONARO REGIONAL", "BURRA"): ("Burra (Queanbeyan-Palerang Regional - NSW)",
                                        _same_postcode("Queanbeyan-Palerang")),
    ("THE HILLS SHIRE", "DURAL"): ("Dural (Hornsby - NSW)", _same_postcode("Hornsby")),
    ("UPPER HUNTER", "BARRY"): ("Barry (Tamworth Regional - NSW)", _same_postcode("Tamworth")),
    ("WINGECARRIBEE", "BALMORAL VILLAGE"): ("Balmoral (Wingecarribee - NSW)",
                                            "renamed: the SAL's Wingecarribee Balmoral"),
    ("CARRATHOOL", "CURRATHOOL"): ("Carrathool", SPELLING),
    ("DUNGOG", "MT RIVERS"): ("Mount Rivers", SPELLING),
    ("LITHGOW", "OAKY PARK"): ("Oakey Park", SPELLING),
    ("PORT STEPHENS", "DUNNS CREEK"): ("Duns Creek", SPELLING),
    ("SINGLETON", "WATTLEPONDS"): ("Wattle Ponds", SPELLING),
    ("SNOWY MONARO REGIONAL", "YAUOK"): ("Yaouk", SPELLING),
    ("UPPER LACHLAN", "GURRUNDA"): ("Gurrundah", SPELLING),
    ("YASS VALLEY", "NARANGULLEN"): ("Narrangullen", SPELLING),
}

# Left out: no SAL 2021 of this name to place them in without guessing. Most
# are reserves, waterways, parishes or named places inside a SAL, with no
# residentially zoned parcel; the few with residential parcels are localities
# named since SAL 2021 was drawn, or estates.
NOT_SAL = "not a SAL 2021 name"
NEWER = "not a SAL 2021 name; residential parcels, but no SAL to place them in without guessing"
NOT_LOCALITIES = {
    ("BATHURST REGIONAL", "STEWARTS MOUNT"): NOT_SAL,
    ("BEGA VALLEY", "WONBOYN LAKE"): NOT_SAL,
    ("BLAND", "GUBBATA"): NOT_SAL,
    ("BOURKE", "BARRINGUN"): NOT_SAL,
    ("BOURKE", "BERAWINNIA"): NOT_SAL,
    ("CABONNE", "BUMBERRY"): NOT_SAL,
    ("CAMDEN", "BARKER"): NEWER,
    ("CAMDEN", "BICKLEY VALE"): NOT_SAL,
    ("CENTRAL COAST", "ETTALONG"): NOT_SAL,
    ("CENTRAL COAST", "HAWKESBURY RIVER"): NOT_SAL,
    ("CENTRAL COAST", "MARLOW CREEK"): NOT_SAL,
    ("CENTRAL COAST", "SOUTH TACOMA"): NOT_SAL,
    ("CESSNOCK", "BIG YENGO"): NOT_SAL,
    ("CESSNOCK", "BLACKHILL"): NOT_SAL,
    ("CITY OF PARRAMATTA", "HOMEBUSH BAY"): NOT_SAL,
    ("CITY OF SYDNEY", "DARLING HARBOUR"): NOT_SAL,
    ("CITY OF SYDNEY", "KINGS CROSS"): NOT_SAL,
    ("CITY OF SYDNEY", "WALSH BAY"): NOT_SAL,
    ("CLARENCE VALLEY", "HARWOOD ISLAND"): NOT_SAL,
    ("CLARENCE VALLEY", "WANGAINAN ISLAND"): NOT_SAL,
    ("COOTAMUNDRA-GUNDAGAI REGIONAL", "JONES CREEK"): NOT_SAL,
    ("DUBBO REGIONAL", "BENI"): NEWER,
    ("DUBBO REGIONAL", "WESTELLA"): NOT_SAL,
    ("HILLTOPS", "COONEYS CREEK"): NOT_SAL,
    ("HORNSBY", "BEROWRA CREEK"): NOT_SAL,
    ("HORNSBY", "HAWKESBURY RIVER"): NOT_SAL,
    ("KIAMA", "YELLOW ROCK RIDGE"): NOT_SAL,
    ("LIVERPOOL", "BRADFIELD"): NOT_SAL,
    ("LIVERPOOL PLAINS", "BORAMBIL"): NOT_SAL,
    ("MID WESTERN REGIONAL", "KELGOOLA"): NOT_SAL,
    ("MID WESTERN REGIONAL", "ULLAMALLA"): NOT_SAL,
    ("MID-COAST", "MISCELLANEOUS AREAS"): NOT_SAL,
    ("MID-COAST", "PH STROUD"): NOT_SAL,
    ("MURRAY RIVER", "ECHUCA"): "a Victorian town; not a NSW SAL",
    ("MURRAY RIVER", "MOIRA"): NOT_SAL,
    ("NAMBUCCA", "DONNELLYVILLE"): NEWER,
    ("NORTHERN BEACHES", "BILGOLA"): "not a SAL 2021 name (the ABS has Bilgola Beach and Bilgola Plateau)",
    ("NORTHERN BEACHES", "CURRAWONG BEACH"): NOT_SAL,
    ("NORTHERN BEACHES", "MCCARRS CREEK"): NOT_SAL,
    ("PARKES", "SOUTH TICHBORNE"): NOT_SAL,
    ("PENRITH", "NORTH PENRITH"): NEWER,
    ("PORT STEPHENS", "KINGS HILL"): NEWER,
    ("QUEANBEYAN-PALERANG REGIONAL", "DODSWORTH"): NEWER,
    ("RICHMOND VALLEY", "CLOVASS"): NOT_SAL,
    ("RICHMOND VALLEY", "TRUSTUMS HILL"): NOT_SAL,
    ("SHELLHARBOUR", "YELLOW ROCK RIDGE"): NEWER,
    ("SHOALHAVEN", "BADAGARANG"): NEWER,
    ("SINGLETON", "COMBO"): NOT_SAL,
    ("SNOWY MONARO REGIONAL", "CHARLOTTE PASS"): NOT_SAL,
    ("SNOWY MONARO REGIONAL", "JINDABYNE EAST"): NOT_SAL,
    ("SNOWY MONARO REGIONAL", "KIANDRA"): NOT_SAL,
    ("SNOWY MONARO REGIONAL", "KOSCIUSZKO NATIONAL PARK"): NOT_SAL,
    ("SNOWY MONARO REGIONAL", "THREDBO VILLAGE"): NOT_SAL,
    ("SUTHERLAND", "AUDLEY"): NOT_SAL,
    ("SUTHERLAND", "BONNIE VALE"): NOT_SAL,
    ("SUTHERLAND", "WARUMBUL"): NOT_SAL,
    ("SUTHERLAND", "YENABILLI"): NOT_SAL,
    ("TEMORA", "BLAND COUNTY"): NOT_SAL,
    ("TENTERFIELD", "BUNGULLA"): NOT_SAL,
    ("TENTERFIELD", "CARROLLS CREEK"): NOT_SAL,
    ("TENTERFIELD", "MOUNT MACKENZIE"): NOT_SAL,
    ("TENTERFIELD", "STEINBROOK"): NOT_SAL,
    ("UPPER HUNTER", "SATUR"): NOT_SAL,
    ("UPPER LACHLAN", "UPPER LACHLAN SHIRE"): NOT_SAL,
    ("WALGETT", "GRAWIN"): NOT_SAL,
    ("WARRUMBUNGLE", "BOMERA"): NOT_SAL,
    ("WARRUMBUNGLE", "BOX RIDGE"): NOT_SAL,
    ("WARRUMBUNGLE", "NAPIER LANE"): NOT_SAL,
    ("WARRUMBUNGLE", "ROPERS ROAD"): NOT_SAL,
    ("WARRUMBUNGLE", "TANNABAR"): NOT_SAL,
    ("WARRUMBUNGLE", "WATTLE SPRINGS"): NOT_SAL,
    ("WINGECARRIBEE", "LAKE AVON"): NOT_SAL,
    ("WINGECARRIBEE", "WINGECARRIBEE"): NOT_SAL,
    ("WOLLONDILLY", "BELOON"): NOT_SAL,
    ("WOLLONDILLY", "JOORILAND"): NOT_SAL,
    ("WOLLONDILLY", "WARRAGAMBA DAM CATCHMENT"): NOT_SAL,
    ("WOLLONDILLY", "WOLLONDILLY"): NOT_SAL,
    ("WOLLONGONG", "AVON DAM"): NOT_SAL,
    ("WOLLONGONG", "STREAM HILL"): NEWER,
    ("YASS VALLEY", "TANGMANGAROO"): NOT_SAL,
}

COLUMNS = ["DISTRICT NAME", "PROPERTY TYPE", "SUBURB NAME", "ZONE CODE", "AREA", "AREA TYPE"]
MEASURES = ["urban", "urban_plain", "urban_lot", "wider"]


def letters(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s.upper().replace("CITY OF", ""))


def sal_index(path: Path):
    """(plain names -> SAL, name -> {council letters: SAL}, SAL name -> code)."""
    plain, qualified, code = {}, defaultdict(dict), {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["state"] != "NSW":
                continue
            name = r["sal_name"]
            code[name] = r["sal_code"]
            m = re.fullmatch(r"(.*) \((.*) - NSW\)", name)
            if m:
                qualified[m.group(1).upper()][letters(m.group(2))] = name
            else:
                plain[re.sub(r" \(NSW\)$", "", name).upper()] = name
    return plain, qualified, code


def resolve(district, suburb, plain, qualified):
    """The SAL a VG locality matches by rule, or None."""
    if suburb in plain:
        return plain[suburb]
    if suburb in qualified:
        d = letters(district)
        hits = [n for council, n in qualified[suburb].items()
                if council.startswith(d) or d.startswith(council)]
        if len(hits) == 1:
            return hits[0]
    return None


def read_parcels(folder: Path):
    """Yield (district, suburb, zone, strata, area m2, [(value, basis)] by base date)."""
    files = sorted(folder.glob(f"*_LAND_VALUE_DATA_{SNAPSHOT[3:]}.csv"))
    if len(files) != 128:
        raise ValueError(f"expected 128 district files in {folder}, found {len(files)}")
    for path in files:
        with open(path, newline="", encoding="latin-1") as fh:
            rows = csv.reader(fh)
            header = next(rows)
            at = {k: header.index(k) for k in COLUMNS}
            dates = [header.index(f"BASE DATE {i}") for i in range(1, 6)]
            for r in rows:
                if [r[i] for i in dates] != BASE_DATES:
                    raise ValueError(f"{path.name}: unexpected base dates {[r[i] for i in dates]}")
                unit = r[at["AREA TYPE"]]
                area = float(r[at["AREA"]] or 0) * {"M": 1.0, "H": 10000.0}.get(unit, 0.0)
                values = [(r[i + 1], r[i + 3]) for i in dates]
                yield (r[at["DISTRICT NAME"]], r[at["SUBURB NAME"]], r[at["ZONE CODE"]],
                       r[at["PROPERTY TYPE"]] == "UNDERSP", area, values)


def reduce(folder: Path, sal_path: Path):
    plain, qualified, sal_code = sal_index(sal_path)
    values = defaultdict(list)       # (SAL, year, measure) -> values
    seen, matched = defaultdict(int), {}
    for district, suburb, zone, strata, area, vals in read_parcels(folder):
        key = (district, suburb)
        seen[key] += 1
        if key not in matched:
            matched[key] = resolve(district, suburb, plain, qualified)
        sal = matched[key] or (PLACED[key][0] if key in PLACED else None)
        if sal is None or zone not in WIDER or area < MIN_AREA:
            continue
        urban = zone in URBAN and area < MAX_AREA
        for date, (value, basis) in zip(BASE_DATES, vals):
            if not value or float(value) <= 0:
                continue
            v, year = float(value), int(date[-4:])
            values[(sal, year, "wider")].append(v / area)
            if urban:
                values[(sal, year, "urban")].append(v / area)
                if basis == PLAIN_BASIS:
                    values[(sal, year, "urban_plain")].append(v / area)
                if not strata:
                    values[(sal, year, "urban_lot")].append(v)
    unmatched = sorted(k for k, v in matched.items() if v is None)
    unknown = [k for k in unmatched if k not in PLACED and k not in NOT_LOCALITIES]
    if unknown:
        raise ValueError(f"VG localities matching no NSW SAL: {unknown}")
    listed = set(PLACED) | set(NOT_LOCALITIES)
    stale = sorted(k for k in listed if k not in seen or matched.get(k) is not None)
    if stale:
        raise ValueError(f"listed localities no longer needing a fix: {stale}")
    bad = sorted(n for n, _ in PLACED.values() if n not in sal_code)
    if bad:
        raise ValueError(f"PLACED names that are not NSW SALs: {bad}")
    return values, sal_code, seen, unmatched


def write(out: Path, values, sal_code):
    cells = sorted({(sal_code[s], s, y) for s, y, _ in values})
    with open(out / "land_value_by_locality.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        header = ["sal_code_2021", "sal_name_2021", "base_date"]
        for m in MEASURES:
            header += [f"{m}_parcels", f"{m}_median"]
        w.writerow(header)
        written = 0
        for code, sal, year in cells:
            row = [code, sal, f"{year}-07-01"]
            any_median = False
            for m in MEASURES:
                v = values.get((sal, year, m), [])
                med = ""
                if len(v) >= MIN_PARCELS:
                    med = f"{statistics.median(v):.0f}" if m == "urban_lot" else f"{statistics.median(v):.2f}"
                    any_median = True
                row += [len(v), med]
            if any_median:
                w.writerow(row)
                written += 1
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("raw", nargs="?", default=str(ROOT / "raw" / "nsw_vg"))
    ap.add_argument("-o", "--out", default=str(ROOT / "data" / "nsw_vg"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    values, sal_code, seen, unmatched = reduce(Path(args.raw) / SNAPSHOT,
                                               ROOT / "data" / "abs" / "sal_sa3_dwellings.csv")
    rows = write(out, values, sal_code)
    left_out = sum(seen[k] for k in NOT_LOCALITIES)
    print(f"{len(seen)} VG localities, {len(unmatched)} needing a listed fix "
          f"({len(PLACED)} placed, {len(NOT_LOCALITIES)} left out: {left_out:,} of "
          f"{sum(seen.values()):,} records); {rows} locality-dates written", file=sys.stderr)


if __name__ == "__main__":
    main()
