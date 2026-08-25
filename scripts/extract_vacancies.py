#!/usr/bin/env python3
"""Extract the Housing Hub SDA vacancy export into tidy JSON, by region.

The export is one row per vacancy listing, carrying a suburb and postcode but no
statistical geography, and a `Vacancy` count with no denominator. This module
supplies both:

1. **Region.** A postcode/locality concordance resolves every listing to the
   SA4 and SA3 used by `extract_sda.py`, so vacancy sits on the same geography
   as supply and demand.
2. **Denominator.** `docs/data/sda.json` carries enrolled places by design
   category and enrolled dwellings by maximum residents, which turns a raw
   vacancy count into a rate.

It also derives the measure the export does not state: whether a vacancy is the
*whole dwelling* or a *room in an otherwise occupied one*. `Building Type` names
the dwelling's resident capacity, so comparing it with `Vacancy` separates a
wholly empty two-bedroom house from one spare room in a five-resident group home.

Usage:  python3 scripts/extract_vacancies.py <vacancies.csv> \
                --postcodes <australian_postcodes.csv> [-o docs/data/]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# "House, 3 residents", "Apartment, 2 bedroom, 1 resident", "Legacy Stock, 6+
# residents". The trailing resident count is the dwelling's capacity; where a
# label carries a bedroom count too, residents is always last.
BUILDING_TYPE = re.compile(r"^(?P<form>[^,]+),.*?(?P<residents>\d+)\+?\s*residents?$")

# "Clyde VIC 3978". Every row in the 2026-08 export matches.
LOCATION = re.compile(r"^(?P<suburb>.+?)\s+(?P<state>NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s+(?P<postcode>\d{4})$")

# The export writes "Multi Design Category"; Supplement P writes it hyphenated.
# The other five design categories match exactly.
CATEGORY_ALIASES = {"Multi Design Category": "Multi-Design Category"}

# The concordance carries pre-2016 SA4 names for three regions. Two are plain
# renames; Western Australia - Outback was genuinely split in 2016 and has to be
# resolved from the SA3, which the concordance does carry.
SA4_RENAMES = {
    "Fitzroy": "Central Queensland",
    "Mackay": "Mackay - Isaac - Whitsunday",
}
WA_OUTBACK = "Western Australia - Outback"
WA_OUTBACK_NORTH_SA3 = {"Kimberley", "Pilbara"}

# Suburbs the concordance cannot resolve. The first three are new growth-area
# suburbs present in the file but with the SA columns left blank; the last two
# are postcode errors in the Housing Hub export (Doreen is 3754, Oxenford 4210).
SUBURB_OVERRIDES = {
    ("3358", "WINTER VALLEY"): ("Ballarat", "Ballarat"),
    ("3336", "DEANSIDE"): ("Melbourne - West", "Melton - Bacchus Marsh"),
    ("3336", "FRASER RISE"): ("Melbourne - West", "Melton - Bacchus Marsh"),
    ("3794", "DOREEN"): ("Melbourne - North East", "Whittlesea - Wallan"),
    ("4201", "OXENFORD"): ("Gold Coast", "Ormeau - Oxenford"),
}

# Yes/no columns worth crossing against vacancy. Each is a dwelling attribute
# rather than a listing attribute, so they can be read as supply characteristics.
FEATURES = [
    ("Onsite Overnight Assistance", "Onsite overnight assistance"),
    ("Has Fire Sprinklers", "Fire sprinklers"),
    ("Has Breakout Room", "Breakout room"),
]

# Supplement P labels its maximum-residents breakdown this way. "6+" is counted
# as exactly 6 places, which understates a handful of large legacy dwellings.
RESIDENT_LABELS = {1: "1 Resident", 2: "2 Residents", 3: "3 Residents",
                   4: "4 Residents", 5: "5 Residents", 6: "6+ Residents"}

# Panels that compare one group of listings against another need enough of them
# to mean anything. The median SA3 carries five listings, where a price-band or
# a with/without-sprinklers split is noise, and a suburb ranking is barely more
# than a list of the listings themselves.
DETAIL_MIN_LISTINGS = 20


def parse_building_type(raw):
    """Return (dwelling form, resident capacity) for a Housing Hub building type."""
    match = BUILDING_TYPE.match(raw.strip())
    if not match:
        raise ValueError(f"unrecognised building type: {raw!r}")
    return match.group("form").strip(), int(match.group("residents"))


def parse_location(raw):
    """Return (suburb, state, postcode) for a Housing Hub location string."""
    match = LOCATION.match(raw.strip())
    if not match:
        raise ValueError(f"unrecognised location: {raw!r}")
    return (match.group("suburb").strip().upper(),
            match.group("state").upper(),
            match.group("postcode"))


def canonical_sa4(sa4, sa3):
    """Map a concordance SA4 name onto the name Supplement P uses."""
    if sa4 == WA_OUTBACK:
        suffix = "(North)" if sa3 in WA_OUTBACK_NORTH_SA3 else "(South)"
        return f"{WA_OUTBACK} {suffix}"
    return SA4_RENAMES.get(sa4, sa4)


def build_concordance(path, sa4_names):
    """Build postcode+suburb and postcode-only lookups from the correspondence.

    Reads the `sa4name`/`sa3name` columns only. The file's `SA3_NAME_2021`,
    `SA4_NAME_2021` and `SA4_CODE_2021` columns are corrupt — they hold 21
    distinct SA4 names across 17,546 populated rows and misassign badly
    (postcode 2000 BARANGAROO is labelled "Sydney - Sutherland") — so they are
    ignored entirely. The older columns are correct for the same rows.

    Rows whose SA4 is unknown to Supplement P are dropped. That discards the
    external territories, which have no SDA, and one corrupt row (GILBERTON
    4871, labelled "North Queensland" with a Gold Coast SA3).
    """
    by_suburb, by_postcode = {}, defaultdict(Counter)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sa4 = canonical_sa4(row["sa4name"].strip(), row["sa3name"].strip())
            if sa4 not in sa4_names:
                continue
            region = (sa4, row["sa3name"].strip())
            postcode, suburb = row["postcode"].strip(), row["locality"].strip().upper()
            # First locality row wins; duplicates within a locality agree.
            by_suburb.setdefault((postcode, suburb), region)
            by_postcode[postcode][region] += 1
    return by_suburb, by_postcode


def resolve_region(postcode, suburb, by_suburb, by_postcode):
    """Return ((sa4, sa3), how) for a listing, most specific match first."""
    key = (postcode, suburb)
    if key in SUBURB_OVERRIDES:
        return SUBURB_OVERRIDES[key], "override"
    if key in by_suburb:
        return by_suburb[key], "suburb"
    if postcode in by_postcode:
        # A handful of postcodes straddle an SA4 boundary; take the modal one.
        return by_postcode[postcode].most_common(1)[0][0], "postcode"
    raise ValueError(f"no region for {suburb} {postcode}")


def split_depth(capacity, vacancy):
    """Split a listing's vacant places into whole-dwelling, rooms and surplus.

    A listing reporting at least as many vacancies as its dwelling type holds is
    a wholly empty dwelling. 112 listings report *more* — nine vacancies in a
    "1 residents" villa — which can only mean one listing covering several
    identical dwellings. The surplus is held apart rather than folded into
    either bucket, because it is the one figure the export does not let us
    attribute to a dwelling.
    """
    if vacancy < capacity:
        return 0, vacancy, 0
    return capacity, 0, vacancy - capacity


def read_listings(path, by_suburb, by_postcode):
    """Read the export into flat listing records, one per row."""
    listings, how = [], Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            form, capacity = parse_building_type(row["Building Type"])
            suburb, _, postcode = parse_location(row["Location"])
            vacancy = int(row["Vacancy"])
            (sa4, sa3), matched = resolve_region(postcode, suburb, by_suburb, by_postcode)
            how[matched] += 1
            whole, rooms, surplus = split_depth(capacity, vacancy)
            listings.append({
                "sa4": sa4,
                "sa3": sa3,
                "suburb": suburb.title(),
                "form": form,
                "capacity": capacity,
                "category": CATEGORY_ALIASES.get(row["SDA Design Category"].strip(),
                                                 row["SDA Design Category"].strip()),
                "vacancy": vacancy,
                "whole_places": whole,
                "room_places": rooms,
                "surplus_places": surplus,
                "is_whole": vacancy >= capacity,
                "price": float(row["Max Price Per Room"] or 0) or None,
                "features": {name: row[column] == "1" for column, name in FEATURES},
            })
    return listings, how


def quartile_bands(prices):
    """Three cut-points over the priced listings, as inclusive-low bands."""
    ordered = sorted(prices)
    cuts = [ordered[int(len(ordered) * q)] for q in (0.25, 0.5, 0.75)]
    return [
        ("Lowest quarter", None, cuts[0]),
        ("Lower middle", cuts[0], cuts[1]),
        ("Upper middle", cuts[1], cuts[2]),
        ("Highest quarter", cuts[2], None),
    ]


def band_of(price, bands):
    for label, low, high in bands:
        if (low is None or price >= low) and (high is None or price < high):
            return label
    return bands[-1][0]


def tally(listings):
    """Listings and places for a group, split by how deep the vacancy runs.

    Zero-valued keys are dropped. Most groups in a small region are empty on
    most measures, and at 323 regions the repeated key names cost more than the
    figures do; the front end reads every field as "0 if absent".
    """
    counts = {
        "listings": len(listings),
        "vacant_places": sum(x["vacancy"] for x in listings),
        "whole_places": sum(x["whole_places"] for x in listings),
        "room_places": sum(x["room_places"] for x in listings),
        "surplus_places": sum(x["surplus_places"] for x in listings),
        "whole_listings": sum(1 for x in listings if x["is_whole"]),
    }
    return {key: value for key, value in counts.items() if value}


def rate(vacant, enrolled, floor=50):
    """Vacant places as a share of enrolled places, suppressed on thin bases."""
    if not enrolled or enrolled < floor:
        return None
    return round(vacant / enrolled, 4)


def build_profile(listings, geography, categories, bands):
    """One region's vacancy profile. Identical shape at every level."""
    has_places = bool(geography.get("has_places"))
    cats = geography.get("categories") or {}
    residents = geography.get("max_residents") or {}

    def group(key):
        buckets = defaultdict(list)
        for listing in listings:
            buckets[key(listing)].append(listing)
        return buckets

    by_category = []
    for name in categories:
        rows = group(lambda x: x["category"]).get(name, [])
        cell = cats.get(name) or {}
        enrolled = cell.get("enrolled_places") if has_places else None
        if not rows and not enrolled:
            continue
        by_category.append({
            "category": name,
            **tally(rows),
            "enrolled_dwellings": cell.get("enrolled_dwellings"),
            "enrolled_places": enrolled,
            "rate": rate(sum(x["vacancy"] for x in rows), enrolled),
        })

    by_capacity = []
    capacity_groups = group(lambda x: min(x["capacity"], 6))
    for capacity, label in RESIDENT_LABELS.items():
        rows = capacity_groups.get(capacity, [])
        dwellings = residents.get(label) if has_places else None
        # Supplement P publishes dwellings on this axis, not places; capacity
        # times dwellings is an approximation, and labelled as one in the UI.
        enrolled = dwellings * capacity if dwellings else None
        if not rows and not enrolled:
            continue
        by_capacity.append({
            "capacity": capacity,
            "label": label,
            **tally(rows),
            "enrolled_dwellings": dwellings,
            "enrolled_places": enrolled,
            "rate": rate(sum(x["vacancy"] for x in rows), enrolled),
        })

    by_form = sorted(
        ({"form": form, **tally(rows)} for form, rows in group(lambda x: x["form"]).items()),
        key=lambda row: -row["vacant_places"])

    detailed = len(listings) >= DETAIL_MIN_LISTINGS

    by_feature = []
    for _, name in FEATURES:
        with_it = [x for x in listings if x["features"][name]]
        without = [x for x in listings if not x["features"][name]]
        # Only worth showing where both sides exist to compare.
        if detailed and with_it and without:
            by_feature.append({"feature": name, "with": tally(with_it),
                               "without": tally(without)})

    priced = [x for x in listings if x["price"]] if detailed else []
    price_bands = []
    for label, _, _ in bands:
        rows = [x for x in priced if band_of(x["price"], bands) == label]
        if rows:
            price_bands.append({"label": label, **tally(rows)})

    suburbs = defaultdict(list)
    for listing in listings if detailed else []:
        suburbs[listing["suburb"]].append(listing)
    top_suburbs = sorted(
        ({"suburb": name, **tally(rows)} for name, rows in suburbs.items()),
        key=lambda row: -row["vacant_places"])[:15]

    enrolled_places = (sum(cell.get("enrolled_places") or 0 for cell in cats.values())
                       if has_places else None)
    vacant_places = sum(x["vacancy"] for x in listings)

    return {
        "listings": len(listings),
        "vacant_places": vacant_places,
        "enrolled_places": enrolled_places,
        "rate": rate(vacant_places, enrolled_places, floor=1) if has_places else None,
        "depth": {
            "whole": {"listings": sum(1 for x in listings if x["is_whole"]),
                      "places": sum(x["whole_places"] for x in listings)},
            "rooms": {"listings": sum(1 for x in listings if not x["is_whole"]),
                      "places": sum(x["room_places"] for x in listings)},
            "multi_dwelling": {"listings": sum(1 for x in listings if x["surplus_places"]),
                               "places": sum(x["surplus_places"] for x in listings)},
        },
        "by_category": by_category,
        "by_capacity": by_capacity,
        "by_form": by_form,
        "by_feature": by_feature,
        "price_bands": price_bands,
        "top_suburbs": top_suburbs,
    }


def assign_regions(listings, sda):
    """Group listings by every geography id they belong to, from SA3 up.

    State comes from the matched SA4 rather than the listing's address: a
    handful of border postcodes carry the neighbouring state, and only the SA4's
    own state keeps region totals summing to their parent.
    """
    sa4_by_name = {g["name"]: g for g in sda["geographies"]
                   if g["level"] == "SA4" and g["name"] != "Other"}
    sa3_by_name = {g["name"]: g for g in sda["geographies"]
                   if g["level"] == "SA3" and g["name"] != "Other"}

    grouped = defaultdict(list)
    unresolved_sa3 = 0
    for listing in listings:
        sa4 = sa4_by_name[listing["sa4"]]
        grouped["national"].append(listing)
        grouped[f"state:{sa4['state']}"].append(listing)
        grouped[sa4["id"]].append(listing)
        sa3 = sa3_by_name.get(listing["sa3"])
        if sa3 and sa3["state"] == sa4["state"]:
            grouped[sa3["id"]].append(listing)
        else:
            unresolved_sa3 += 1
    return grouped, unresolved_sa3


def build_bridge(grouped, sda, categories):
    """SA4 x design category: vacancy rate against the supply/demand ratio.

    This is the one place the two datasets can be checked against each other.
    Where Supplement P reports more enrolled places per participant than a
    region needs, more of those places turn up listed as vacant.
    """
    by_id = {g["id"]: g for g in sda["geographies"]}
    points = []
    for region_id, listings in grouped.items():
        if not region_id.startswith("sa4:"):
            continue
        geography = by_id[region_id]
        for name in categories:
            cell = geography["categories"].get(name) or {}
            enrolled = cell.get("enrolled_places")
            ratio = cell.get("places_per_participant")
            if not enrolled or enrolled < 50 or ratio is None:
                continue
            vacant = sum(x["vacancy"] for x in listings if x["category"] == name)
            points.append({
                "region_id": region_id,
                "region": geography["name"],
                "state": geography["state"],
                "category": name,
                "vacant_places": vacant,
                "enrolled_places": enrolled,
                "rate": round(vacant / enrolled, 4),
                "places_per_participant": ratio,
            })
    return sorted(points, key=lambda p: (p["state"], p["region"], p["category"]))


def spearman(pairs):
    """Rank correlation, with midranks for ties. Pure stdlib, n is small."""
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = shared
            i = j + 1
        return out

    xs, ys = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return round(num / den, 3) if den else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vacancies", type=Path)
    parser.add_argument("-p", "--postcodes", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, default=Path("docs/data"))
    args = parser.parse_args()

    sda = json.loads((args.out / "sda.json").read_text())
    categories = sda["meta"]["design_categories"]
    comparable = sda["meta"]["comparable_categories"]
    sa4_names = {g["name"] for g in sda["geographies"]
                 if g["level"] == "SA4" and g["name"] != "Other"}

    by_suburb, by_postcode = build_concordance(args.postcodes, sa4_names)
    listings, how = read_listings(args.vacancies, by_suburb, by_postcode)

    total_places = sum(x["vacancy"] for x in listings)
    depth_total = sum(x["whole_places"] + x["room_places"] + x["surplus_places"]
                      for x in listings)
    assert depth_total == total_places, f"depth split lost places: {depth_total} != {total_places}"

    grouped, unresolved_sa3 = assign_regions(listings, sda)
    assert sum(x["vacancy"] for x in grouped["national"]) == total_places

    by_id = {g["id"]: g for g in sda["geographies"]}
    bands = quartile_bands([x["price"] for x in listings if x["price"]])
    regions = {region_id: build_profile(rows, by_id[region_id], categories, bands)
               for region_id, rows in grouped.items()}

    states = sum(profile["vacant_places"] for region_id, profile in regions.items()
                 if region_id.startswith("state:"))
    assert states == total_places, f"states sum to {states}, not {total_places}"
    sa4_sum = sum(profile["vacant_places"] for region_id, profile in regions.items()
                  if region_id.startswith("sa4:"))
    assert sa4_sum == total_places, f"SA4s sum to {sa4_sum}, not {total_places}"

    bridge = build_bridge(grouped, sda, comparable)
    correlation = spearman([(p["places_per_participant"], p["rate"]) for p in bridge])
    without_vic = spearman([(p["places_per_participant"], p["rate"])
                            for p in bridge if p["state"] != "VIC"])

    as_at = re.search(r"(\d{4})(\d{2})(\d{2})", args.vacancies.stem)
    bundle = {
        "meta": {
            "source": args.vacancies.name,
            "as_at": f"{as_at.group(3)}/{as_at.group(2)}/{as_at.group(1)}" if as_at else None,
            "sda_as_at": sda["meta"]["as_at"],
            "listings": len(listings),
            "vacant_places": total_places,
            "match": dict(how),
            "regions_with_vacancy": {
                "SA4": sum(1 for k in regions if k.startswith("sa4:")),
                "SA3": sum(1 for k in regions if k.startswith("sa3:")),
            },
            "sa3_unresolved_listings": unresolved_sa3,
            "price_bands": [{"label": label, "from": low, "to": high}
                            for label, low, high in bands],
            "bridge_correlation": {
                "spearman": correlation,
                "spearman_excluding_vic": without_vic,
                "points": len(bridge),
            },
        },
        "regions": regions,
        "bridge": bridge,
    }

    target = args.out / "vacancies.json"
    target.write_text(json.dumps(bundle, separators=(",", ":")))

    national = regions["national"]
    print(f"wrote {target}  ({target.stat().st_size / 1024:.0f} KB)")
    print(f"  as at: {bundle['meta']['as_at']}  (Supplement P as at {sda['meta']['as_at']})")
    print(f"  listings: {len(listings)}  matched " +
          "  ".join(f"{k}={v}" for k, v in sorted(how.items())))
    print(f"  vacant places: {total_places}  of {national['enrolled_places']:.0f} "
          f"enrolled ({national['rate']:.2%})")
    print(f"  whole dwellings: {national['depth']['whole']['places']} places "
          f"({national['depth']['whole']['listings']} listings)  "
          f"rooms: {national['depth']['rooms']['places']} places "
          f"({national['depth']['rooms']['listings']})  "
          f"multi-dwelling surplus: {national['depth']['multi_dwelling']['places']}")
    print(f"  regions: SA4={bundle['meta']['regions_with_vacancy']['SA4']}  "
          f"SA3={bundle['meta']['regions_with_vacancy']['SA3']}  "
          f"({unresolved_sa3} listings had no matching SA3)")
    print(f"  bridge: rho={correlation} over {len(bridge)} SA4-category points "
          f"({without_vic} excluding VIC)")
    for row in national["by_category"]:
        share = f"{row['rate']:.2%}" if row["rate"] is not None else "n/a"
        print(f"  {row['category']:<24} vacant={row['vacant_places']:>5}"
              f"  enrolled={row['enrolled_places'] or 0:>7.0f}  rate={share:>7}")


if __name__ == "__main__":
    main()
