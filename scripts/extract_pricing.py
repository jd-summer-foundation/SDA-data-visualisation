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

# One entry per document read into location_factors.csv, in date order. Its
# edition, version and dates are read from its own title page and must match.
# Base amounts are extracted only where `base_amounts` is set: before 2026-27
# the base-price tables use other layouts (OOA as merged columns, sub-rows),
# which this reader does not parse. `checks` are other documents that must
# publish identical figures.
DOCUMENTS = [
    {"file": "NDIS_Pricing_Arrangements_SDA_2021-22 DOCX_0.docx",
     "edition": "2021-22", "version": "1.0"},
    {"file": "PB NDIS Pricing Arrangements for SDA 2021-22 v2.0 DOCX_0.docx",
     "edition": "2021-22", "version": "2.0"},
    {"file": "PB NDIS Pricing Arrangements for SDA 2021-22 v3.0 DOCX.docx",
     "edition": "2021-22", "version": "3.0"},
    {"file": "NDIS Pricing Arrangements for SDA 2022-23 v1.0.docx",
     "edition": "2022-23", "version": "1.0"},
    {"file": "NDIS Pricing Arrangements for SDA 2022-23 v1.1.docx",
     "edition": "2022-23", "version": "1.1"},
    # Two copies of v1.0 were published; they differ only in page numbering.
    {"file": "NDIS Pricing Arrangements for Specialist Disability Accommodation 2023-24 - effective 1 July 2023.docx",
     "edition": "2023-24", "version": "1.0",
     "checks": ["NDIS Pricing Arrangements for SDA 2023-24 _Word.docx"]},
    # Published as "v1.3 (1)"; its title page says version 1.4.
    {"file": "NDIS Pricing Arrangements for Specialist Disability Accommodation 2023-24 v1.3 (1).docx",
     "edition": "2023-24", "version": "1.4"},
    {"file": "NDIS Pricing Arrangements for Specialist Disability Accommodation 2023-24 FINAL.docx",
     "edition": "2023-24", "version": "3.0"},
    {"file": "PB NDIS Pricing Arrangements for Specialist Disability Accommodation 2024-25 v1.0_0.docx",
     "edition": "2024-25", "version": "1.0"},
    {"file": "PB NDIS Pricing Arrangements for Specialist Disability Accommodation 2024-25 v.3.0 DOCX.docx",
     "edition": "2024-25", "version": "3.0"},
    {"file": "NDIS Pricing Arrangements for Specialist Disability Accommodation 2025-26 v.2.0-2_0.docx",
     "edition": "2025-26", "version": "2.0"},
    {"file": "Pricing-Arrangements-for-SDA-2025_26-v3_0.docx",
     "edition": "2025-26", "version": "3.0"},
    {"file": "Pricing-Arrangements-for-SDA-2026_27-v1_0.docx",
     "edition": "2026-27", "version": "1.0", "base_amounts": True,
     "checks": ["ndis-pricing-schedule-for-sda-2026-27.docx"]},
]
MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october "
    "november december".split(), 1)}

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
    # A spelling variant, 2021-22 and 2022-23.
    "NSW - Hunter Valley excluding Newcastle": "NSW - Hunter Valley exc Newcastle",
}
# The pre-2016 SA4 the ABS split in two; 2021-22 and 2022-23 still publish
# one factor for the whole region, which applies to both of its successors.
SA4_SPLITS = {
    "WA - Western Australia - Outback": ["WA - Western Australia - Outback (North)",
                                         "WA - Western Australia - Outback (South)"],
}
# Labels garbled in one document, by file and label as published. In 2023-24
# v3.0's new-build table the words "Hunter Valley exc Newcastle" moved from
# its own row (8th, where it sorts, left reading "NSW -") into the Murray row
# (11th). The figures stayed put: each row equals v1.4's row for that region.
LABEL_FIXES = {
    "NDIS Pricing Arrangements for Specialist Disability Accommodation 2023-24 FINAL.docx": {
        "NSW -": "NSW - Hunter Valley exc Newcastle",
        "NSW - Murray Hunter Valley exc Newcastle": "NSW - Murray",
    },
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
    # 2021-22 captions its one factor table by its appendix heading alone.
    if re.match(r"(table \d+:|appendix [a-z] -) location factors", c):
        if "new builds" in c:
            return "location", {"stock": "new_build"}
        if "existing and legacy" in c:
            return "location", {"stock": "existing_legacy"}
        if re.fullmatch(r"(table \d+:|appendix [a-z] -) location factors", c):
            # Before 2023-24 one table served every stock type.
            return "location", {"stock": "all"}
        raise ValueError(f"unrecognised location-factor table: {caption!r}")
    if not re.match(r"table \d+:", c):
        return None
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

def title_page(path: Path):
    """Edition, version and dates from 'Valid from: 1 July 2021 Version 1.0
    (Released 1 July 2021)' on the title page."""
    text = document_text(path)
    m = re.search(r"Accommodation\s*(\d{4}-\d{2})\s*Valid from:\s*(\d{1,2}) (\w+) (\d{4})\s*"
                  r"Version (\d+\.\d+)\s*\(Released (\d{1,2}) (\w+) (\d{4})\)", text)
    if not m:
        raise ValueError(f"{path.name}: no title page with edition, version and dates")
    ed, d1, m1, y1, version, d2, m2, y2 = m.groups()

    def iso(d, mon, y):
        return f"{y}-{MONTHS[mon.lower()]:02d}-{int(d):02d}"
    return {"edition": ed, "version": version, "valid_from": iso(d1, m1, y1),
            "released": iso(d2, m2, y2)}


def factor(text: str) -> str:
    """A factor as two decimals. Some tables drop trailing zeros ('0.9', '1')."""
    if not re.fullmatch(r"\d(\.\d{1,2})?", text):
        raise ValueError(f"unreadable location factor {text!r}")
    return f"{float(text):.2f}"


def extract(path: Path, sa4_ids: set[str], base_amounts: bool = True):
    """Location factors and base amounts from one document.

    Returns (factors, amounts): factors keyed (stock, SA4, building type) to
    the published two-decimal text, amounts keyed (stock, building type,
    category, breakout, sprinklers, OOA, GST) to whole dollars.
    """
    factors, amounts, seen = {}, {}, []
    fixes, fixed = LABEL_FIXES.get(path.name, {}), set()
    for caption, rows in read_tables(path):
        # Older base-price tables are not read, so their captions are not classified.
        if not base_amounts and "location factors" not in _norm(caption):
            continue
        found = classify(caption)
        if not found:
            continue
        kind, attrs = found
        seen.append((kind, attrs.get("stock")))
        header, body = rows[0], rows[1:]
        if kind == "location":
            types = [building_type(h) for h in header[1:]]
            expected = BUILDING_TYPES + ([LEGACY] if attrs["stock"] != "new_build" else [])
            if types != expected:
                raise ValueError(f"{path.name}: {caption!r} columns {types}")
            regions = set()
            for row in body:
                label = " ".join(row[0].split())
                cells = row[1:]
                if len(cells) != len(types):
                    raise ValueError(f"{path.name}: bad location-factor row {row!r}")
                cells = [factor(c) for c in cells]
                if _norm(label) == REFERENCE_ROW:
                    if set(cells) != {"1.00"}:
                        raise ValueError(f"{path.name}: reference row is not 1.00 throughout")
                    continue
                if label in fixes:
                    fixed.add(label)
                    label = fixes[label]
                label = SA4_RENAMES.get(label, label)
                for name in SA4_SPLITS.get(label, [label]):
                    geo = "sa4:" + name
                    if geo not in sa4_ids:
                        raise ValueError(f"{path.name}: location {label!r} is not a Supplement P SA4")
                    if geo in regions:
                        raise ValueError(f"{path.name}: {label!r} listed twice in {caption!r}")
                    regions.add(geo)
                    for btype, value in zip(types, cells):
                        stock = ("New build" if attrs["stock"] == "new_build"
                                 else "Legacy" if btype == LEGACY
                                 else "All" if attrs["stock"] == "all" else "Existing")
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
    if fixed != set(fixes):
        raise ValueError(f"{path.name}: label fixes not used: {sorted(set(fixes) - fixed)}")
    locations = sorted(s for k, s in seen if k == "location")
    if locations not in (["existing_legacy", "new_build"], ["all"]):
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

STOCK_ORDER = {"All": 0, "New build": 0, "Existing": 1, "Legacy": 2,
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
        w.writerow(["edition", "version", "valid_from", "released", "sa4", "stock_type",
                    "building_type", "factor"])
        for ed, factors, _ in results:
            for (stock, geo, btype), value in sorted(
                    factors.items(), key=lambda kv: (STOCK_ORDER[kv[0][0]], kv[0][1],
                                                     type_order(kv[0][2]))):
                w.writerow([ed["edition"], ed["version"], ed["valid_from"], ed["released"], geo,
                            stock, btype, value])
    with open(out_dir / "base_amounts.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["edition", "version", "valid_from", "stock_type", "building_type",
                    "design_category", "breakout_room", "fire_sprinklers", "ooa", "gst",
                    "amount"])
        for ed, _, amounts in results:
            for key, value in sorted(
                    amounts.items(), key=lambda kv: (STOCK_ORDER[kv[0][0]], type_order(kv[0][1]),
                                                     CATEGORY_ORDER[kv[0][2]], kv[0][3:])):
                w.writerow([ed["edition"], ed["version"], ed["valid_from"], *key, value])


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
    for doc in DOCUMENTS:
        path = src / doc["file"]
        ed = title_page(path)
        if (ed["edition"], ed["version"]) != (doc["edition"], doc["version"]):
            raise ValueError(f"{path.name}: title page says {ed['edition']} v{ed['version']}")
        base = doc.get("base_amounts", False)
        factors, amounts = extract(path, sa4_ids, base)
        for name in doc.get("checks", []):
            f2, a2 = extract(src / name, sa4_ids, base)
            compare(name, factors, f2, "location factors")
            if base:
                compare(name, amounts, a2, "base amounts")
        results.append((ed, factors, amounts))
        print(f"{ed['edition']} v{ed['version']} (valid from {ed['valid_from']}): "
              f"{len(factors)} location factors, {len(amounts)} base amounts; "
              f"{len(doc.get('checks', []))} cross-check(s) agree", file=sys.stderr)
    dates = [ed["valid_from"] for ed, _, _ in results]
    if dates != sorted(dates):
        raise ValueError("DOCUMENTS are not in date order")
    write(out, results)


if __name__ == "__main__":
    main()
