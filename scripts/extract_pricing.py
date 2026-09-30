#!/usr/bin/env python3
"""Extract SDA location factors and base amounts from the NDIA pricing documents.

The NDIA publishes each financial year's SDA prices twice: the Pricing
Arrangements for SDA (the guide, with the rules) and the Pricing Schedule for
SDA (the amounts alone). Both are Word documents. A .docx is a zip of XML, so
the tables are read from word/document.xml with the standard library.

Every table is identified by the caption paragraph above it, never by its
number: the two documents number the same tables differently (the location
factors are Tables 23 and 24 in the Arrangements and Tables 35 and 36 in the
Schedule). The Arrangements are the source; the Schedule is read the same way
and must agree cell for cell, or the build fails.

Usage:  python3 scripts/extract_pricing.py [data/pricing] [-o data/pricing]

Writes, into the output directory:
  location_factors.csv   edition x SA4 x stock type x building type -> factor
  base_amounts.csv       edition x stock type x building type x design
                         category x features -> annual base amount per participant

The SDA amount for a dwelling is its base amount times its SA4's location
factor for that stock and building type.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# One entry per edition. The Arrangements are read into the CSVs; every other
# document listed for the edition is read the same way and must agree.
EDITIONS = [
    {
        "edition": "2026-27",
        "version": "1.0",
        "effective_from": "2026-07-01",
        "source": "Pricing-Arrangements-for-SDA-2026_27-v1_0.docx",
        "checks": ["ndis-pricing-schedule-for-sda-2026-27.docx"],
    },
]

# Building types as Supplement P's Table P.11 names them, so the two join on
# the label. Location factors and base amounts are keyed to these.
BUILDING_TYPES = [
    "Apartment, 1 bedroom, 1 resident",
    "Apartment, 2 bedrooms, 1 resident",
    "Apartment, 2 bedrooms, 2 residents",
    "Apartment, 3 bedrooms, 2 residents",
    "Villa/Duplex/Townhouse, 1 resident",
    "Villa/Duplex/Townhouse, 2 residents",
    "Villa/Duplex/Townhouse, 3 residents",
    "House, 2 residents",
    "House, 3 residents",
    "Group home, 4 residents",
    "Group home, 5 residents",
]
LEGACY = "Legacy"
CATEGORIES = ["Basic", "Improved Liveability", "Fully Accessible", "Robust",
              "High Physical Support"]
REFERENCE_ROW = "median capital city"
# The existing and legacy table still uses two SA4 names the ABS retired in
# 2016, when it renamed these regions without changing them. Anything else
# that fails to match stops the build.
SA4_RENAMES = {
    "QLD - Fitzroy": "QLD - Central Queensland",
    "QLD - Mackay": "QLD - Mackay - Isaac - Whitsunday",
}

STOCK = {  # caption phrase -> stock type
    "post-2023 new build": "New build (post-2023)",
    "pre-2023 new build": "New build (pre-2023)",
    "existing stock": "Existing",
    "legacy stock": "Legacy",
}
GST = {
    "gst was not paid or gst was paid and input tax credits were claimed":
        "Not paid, or paid and credits claimed",
    "gst was paid and input tax credits were not claimed": "Paid, credits not claimed",
}


# --------------------------------------------------------------------------
# Reading the document
# --------------------------------------------------------------------------

def cell_text(cell) -> str:
    """A table cell's text, paragraphs and line breaks joined by spaces."""
    parts = []
    for p in cell.iter(W + "p"):
        s = ""
        for el in p.iter():
            if el.tag == W + "t":
                s += el.text or ""
            elif el.tag in (W + "br", W + "tab"):
                s += " "
        parts.append(s)
    return " ".join(" ".join(parts).split())


def read_tables(path: Path):
    """[(caption, rows)] for every table, captioned by the paragraph above it."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    tables, caption = [], ""
    for el in root.find(W + "body"):
        if el.tag == W + "p":
            text = " ".join("".join(t.text or "" for t in el.iter(W + "t")).split())
            if text:
                caption = text
        elif el.tag == W + "tbl":
            rows = [[cell_text(c) for c in r.findall(W + "tc")] for r in el.findall(W + "tr")]
            tables.append((caption, rows))
    return tables


def document_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    return " ".join("".join(t.text or "" for t in root.iter(W + "t")).split())


# --------------------------------------------------------------------------
# Classifying tables and labels
# --------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.lower().replace("–", "-").split())


def classify(caption: str):
    """(kind, attributes) for a pricing table, or None for any other table.

    kind is "location" or "base". Appendix H's shared-living amounts (per
    SDA-eligible participant sharing with non-eligible residents) and the
    minimum refurbishment costs are not base amounts and are skipped.
    """
    c = _norm(caption)
    if not re.match(r"table \d+:", c):
        return None
    if "location factors" in c:
        if "new builds" in c:
            return "location", {"stock": "new_build"}
        if "existing and legacy" in c:
            return "location", {"stock": "existing_legacy"}
        raise ValueError(f"unrecognised location-factor table: {caption!r}")
    if "appendix h" in c or "sda-eligible participant" in c or "refurbishment" in c:
        return None
    if "base price" not in c and "base amount" not in c:
        return None
    stock = [v for k, v in STOCK.items() if k in c]
    if len(stock) != 1:
        raise ValueError(f"cannot read the stock type of {caption!r}")
    sprinklers = ("No" if re.search(r"\b(no|without) sprinklers", c)
                  else "Yes" if "with sprinklers" in c else None)
    if sprinklers is None:
        raise ValueError(f"cannot read sprinklers from {caption!r}")
    gst = [v for k, v in GST.items() if k in c]
    ooa = ("No" if "without on-site overnight assistance" in c
           else "Yes" if "with on-site overnight assistance" in c else "")
    if stock[0].startswith("New build (post") and len(gst) != 1:
        raise ValueError(f"post-2023 new-build table without a GST treatment: {caption!r}")
    if stock[0] != "Legacy" and not ooa:
        raise ValueError(f"cannot read OOA from {caption!r}")
    return "base", {"stock": stock[0], "sprinklers": sprinklers,
                    "gst": gst[0] if gst else "", "ooa": ooa}


def building_type(label: str) -> str:
    """Map any of the documents' building-type labels to BUILDING_TYPES.

    'Apartment, 2 bedrooms, 1 SDA eligible resident', 'Apartment 2 beds 1
    resident' and 'Villa Duplex Townhouse 3 residents' all have one reading.
    Only apartments are distinguished by bedrooms; for the other forms the
    documents give bedrooms equal to residents, which is asserted.
    """
    s = _norm(label)
    if s == "legacy":
        return LEGACY
    residents = re.search(r"(\d+) (?:sda eligible )?residents?\b", s)
    bedrooms = re.search(r"(\d+) bed(?:room)?s?\b", s)
    if not residents:
        raise ValueError(f"no resident count in building type {label!r}")
    r = int(residents.group(1))
    b = int(bedrooms.group(1)) if bedrooms else None
    plural = "resident" if r == 1 else "residents"
    if s.startswith("apartment"):
        if b is None:
            raise ValueError(f"apartment without bedrooms: {label!r}")
        return f"Apartment, {b} {'bedroom' if b == 1 else 'bedrooms'}, {r} {plural}"
    if b is not None and b != r:
        raise ValueError(f"bedrooms differ from residents in {label!r}")
    for prefix, name in (("villa", "Villa/Duplex/Townhouse"), ("house", "House"),
                         ("group home", "Group home")):
        if s.startswith(prefix):
            out = f"{name}, {r} {plural}"
            if out not in BUILDING_TYPES:
                raise ValueError(f"unknown building type {label!r}")
            return out
    raise ValueError(f"unknown building type {label!r}")


def design_column(header: str, ooa_from_caption: str):
    """(category, breakout room, OOA) for a base-amount column heading.

    Legacy tables put OOA in the columns ('Robust With OOA'). Existing-stock
    tables head a column 'Robust No OOA' even in the table captioned *with*
    OOA; the caption governs there, and the heading's suffix is ignored.
    """
    h = _norm(header)
    ooa = ooa_from_caption
    m = re.search(r"\b(no|with) ooa$", h)
    if m:
        if not ooa_from_caption:
            ooa = "No" if m.group(1) == "no" else "Yes"
        h = h[:m.start()].strip()
    breakout = "No"
    if h.endswith("with breakout room"):
        breakout, h = "Yes", h[:-len("with breakout room")].strip()
    for category in CATEGORIES:
        if h == category.lower():
            return category, breakout, ooa
    raise ValueError(f"unknown design-category column {header!r}")


def money(text: str):
    t = text.strip()
    if _norm(t) == "n/a":
        return None
    m = re.fullmatch(r"\$([\d,]+)", t)
    if not m:
        raise ValueError(f"unreadable amount {text!r}")
    return int(m.group(1).replace(",", ""))


# --------------------------------------------------------------------------
# Extracting one document
# --------------------------------------------------------------------------

def extract(path: Path, sa4_ids: set[str]):
    """Location factors and base amounts from one document.

    Returns (factors, amounts): factors keyed (stock, SA4, building type) to
    the published two-decimal text, amounts keyed (stock, building type,
    category, breakout, sprinklers, OOA, GST) to whole dollars.
    """
    factors, amounts, seen = {}, {}, []
    for caption, rows in read_tables(path):
        found = classify(caption)
        if not found:
            continue
        kind, attrs = found
        seen.append((kind, attrs.get("stock")))
        header, body = rows[0], rows[1:]
        if kind == "location":
            types = [building_type(h) for h in header[1:]]
            expected = BUILDING_TYPES + ([LEGACY] if attrs["stock"] == "existing_legacy" else [])
            if types != expected:
                raise ValueError(f"{path.name}: {caption!r} columns {types}")
            regions = set()
            for row in body:
                label = " ".join(row[0].split())
                cells = row[1:]
                if len(cells) != len(types) or any(not re.fullmatch(r"\d\.\d\d", c) for c in cells):
                    raise ValueError(f"{path.name}: bad location-factor row {row!r}")
                if _norm(label) == REFERENCE_ROW:
                    if set(cells) != {"1.00"}:
                        raise ValueError(f"{path.name}: reference row is not 1.00 throughout")
                    continue
                geo = "sa4:" + SA4_RENAMES.get(label, label)
                if geo not in sa4_ids:
                    raise ValueError(f"{path.name}: location {label!r} is not a Supplement P SA4")
                if geo in regions:
                    raise ValueError(f"{path.name}: {label!r} listed twice in {caption!r}")
                regions.add(geo)
                for btype, value in zip(types, cells):
                    stock = ("New build" if attrs["stock"] == "new_build"
                             else "Legacy" if btype == LEGACY else "Existing")
                    factors[(stock, geo, btype)] = value
            if regions != sa4_ids:
                missing = sorted(sa4_ids - regions)
                raise ValueError(f"{path.name}: {caption!r} lacks {len(missing)} SA4s: {missing}")
        else:
            stock = attrs["stock"]
            if stock == "Legacy":
                # Rows are resident counts; columns carry category and OOA.
                columns = [design_column(h, "") for h in header[1:]]
                for row in body:
                    residents = int(row[0])
                    for (category, breakout, ooa), cell in zip(columns, row[1:]):
                        value = money(cell)
                        if value is None:
                            continue
                        # Basic has one column, for dwellings with or without OOA.
                        for o in ([ooa] if ooa else ["No", "Yes"]):
                            key = (stock, f"Legacy, {residents} residents", category, breakout,
                                   attrs["sprinklers"], o, attrs["gst"])
                            put(amounts, key, value, path, caption)
            else:
                columns = [design_column(h, attrs["ooa"]) for h in header[1:]]
                types = [building_type(row[0]) for row in body]
                if types != BUILDING_TYPES:
                    raise ValueError(f"{path.name}: {caption!r} rows {types}")
                for btype, row in zip(types, body):
                    for (category, breakout, ooa), cell in zip(columns, row[1:]):
                        value = money(cell)
                        if value is None:
                            continue
                        key = (stock, btype, category, breakout, attrs["sprinklers"], ooa,
                               attrs["gst"])
                        put(amounts, key, value, path, caption)
    locations = [s for k, s in seen if k == "location"]
    if sorted(locations) != ["existing_legacy", "new_build"]:
        raise ValueError(f"{path.name}: location-factor tables found: {locations}")
    return factors, amounts


def put(store, key, value, path, caption):
    if key in store and store[key] != value:
        raise ValueError(f"{path.name}: {key} is {store[key]} and {value} ({caption!r})")
    store[key] = value


def compare(name, source, check, what):
    """Fail unless two documents publish identical figures."""
    if source == check:
        return
    only_a = sorted(set(source) - set(check))[:5]
    only_b = sorted(set(check) - set(source))[:5]
    differ = sorted(k for k in set(source) & set(check) if source[k] != check[k])[:5]
    raise ValueError(f"{name} disagrees with the Arrangements on {what}: "
                     f"only in Arrangements {only_a}, only in {name} {only_b}, differ {differ}")


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

STOCK_ORDER = {"New build": 0, "Existing": 1, "Legacy": 2,
               "New build (post-2023)": 0, "New build (pre-2023)": 1}
TYPE_ORDER = {t: i for i, t in enumerate(BUILDING_TYPES + [LEGACY])}
CATEGORY_ORDER = {c: i for i, c in enumerate(CATEGORIES)}


def type_order(btype):
    if btype in TYPE_ORDER:
        return (TYPE_ORDER[btype], 0)
    return (len(TYPE_ORDER), int(re.search(r"\d+", btype).group()))


def write(out_dir: Path, results):
    with open(out_dir / "location_factors.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["edition", "version", "effective_from", "sa4", "stock_type",
                    "building_type", "factor"])
        for ed, factors, _ in results:
            for (stock, geo, btype), value in sorted(
                    factors.items(), key=lambda kv: (STOCK_ORDER[kv[0][0]], kv[0][1],
                                                     type_order(kv[0][2]))):
                w.writerow([ed["edition"], ed["version"], ed["effective_from"], geo, stock,
                            btype, value])
    with open(out_dir / "base_amounts.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["edition", "version", "effective_from", "stock_type", "building_type",
                    "design_category", "breakout_room", "fire_sprinklers", "ooa", "gst",
                    "amount"])
        for ed, _, amounts in results:
            for key, value in sorted(
                    amounts.items(), key=lambda kv: (STOCK_ORDER[kv[0][0]], type_order(kv[0][1]),
                                                     CATEGORY_ORDER[kv[0][2]], kv[0][3:])):
                w.writerow([ed["edition"], ed["version"], ed["effective_from"], *key, value])


def sa4_ids_from(sa3_sa4: Path) -> set[str]:
    with open(sa3_sa4, newline="") as fh:
        return {row["sa4"] for row in csv.DictReader(fh)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pricing_dir", nargs="?", default=str(ROOT / "data" / "pricing"))
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args(argv)
    src = Path(args.pricing_dir)
    out = Path(args.out) if args.out else src
    out.mkdir(parents=True, exist_ok=True)
    sa4_ids = sa4_ids_from(ROOT / "data" / "panel" / "sa3_sa4.csv")
    if len(sa4_ids) != 88:
        raise ValueError(f"expected 88 SA4s in sa3_sa4.csv, found {len(sa4_ids)}")

    results = []
    for ed in EDITIONS:
        path = src / ed["source"]
        text = document_text(path)
        if ed["edition"] not in text:
            raise ValueError(f"{path.name} does not mention edition {ed['edition']}")
        factors, amounts = extract(path, sa4_ids)
        for name in ed["checks"]:
            f2, a2 = extract(src / name, sa4_ids)
            compare(name, factors, f2, "location factors")
            # The Schedule has no pre-2023 or legacy rows the Arrangements lack,
            # and vice versa; every amount must match.
            compare(name, amounts, a2, "base amounts")
        results.append((ed, factors, amounts))
        print(f"{ed['edition']}: {len(factors)} location factors, {len(amounts)} base amounts; "
              f"{len(ed['checks'])} cross-check(s) agree", file=sys.stderr)
    write(out, results)


if __name__ == "__main__":
    main()
