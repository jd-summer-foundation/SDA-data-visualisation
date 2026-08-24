#!/usr/bin/env python3
"""Extract the NDIA quarterly SDA supplement (Supplement P) into tidy JSON.

The published workbook is Strict OOXML, which openpyxl cannot open, and every
table is a wide human-readable cross-tab. This module normalises both problems
and derives the one measure the NDIA does not publish directly: SDA *places*
(resident capacity) by design category and region, which is the only unit that
is comparable with participant demand.

Usage:  python3 scripts/extract_sda.py <workbook.xlsx> [-o data/]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

import openpyxl

# Strict OOXML uses purl.oclc.org namespaces; openpyxl only understands the
# transitional schemas. Rewriting the namespace URIs is a lossless fix.
STRICT_TO_TRANSITIONAL = [
    (b"http://purl.oclc.org/ooxml/spreadsheetml/main",
     b"http://schemas.openxmlformats.org/spreadsheetml/2006/main"),
    (b"http://purl.oclc.org/ooxml/officeDocument/relationships",
     b"http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
    (b"http://purl.oclc.org/ooxml/drawingml/main",
     b"http://schemas.openxmlformats.org/drawingml/2006/main"),
    (b"http://purl.oclc.org/ooxml/drawingml/chart",
     b"http://schemas.openxmlformats.org/drawingml/2006/chart"),
    (b"http://purl.oclc.org/ooxml/drawingml/spreadsheetDrawing",
     b"http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"),
    (b"http://purl.oclc.org/ooxml/officeDocument/extendedProperties",
     b"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"),
    (b"http://purl.oclc.org/ooxml/officeDocument/docPropsVTypes",
     b"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"),
    (b'conformance="strict"', b""),
]

DESIGN_CATEGORIES = [
    "Basic",
    "Improved Liveability",
    "High Physical Support",
    "Robust",
    "Fully Accessible",
    "Multi-Design Category",
]

# Design categories a participant can actually be found eligible for. "Basic" is
# no longer issued as an eligibility decision (folded into "Missing"), and
# "Multi-Design Category" is a dwelling attribute, not a decision, so neither
# has a demand-side counterpart to compare against.
COMPARABLE_CATEGORIES = [
    "Improved Liveability",
    "High Physical Support",
    "Robust",
    "Fully Accessible",
]

# Cells the NDIA suppresses for privacy, e.g. "<11", "<5", "n/a".
SUPPRESSED = re.compile(r"^\s*<\s*(\d+)\s*$")

# "Apartment, 2 bedrooms, 1 resident - Fully Accessible" and friends. The
# resident count is what turns a dwelling count into a places count; where a
# label carries both a bedroom and a resident figure, residents is the second.
DWELLING_LABEL = re.compile(
    r"^(?P<form>.*?),\s*(?P<first>\d+)\+?\s*(?:bedrooms?|residents?)"
    r"(?:,\s*(?P<residents>\d+)\s*residents?)?\s*-\s*(?P<category>.*)$"
)


def to_transitional(src: Path, dst: Path) -> Path:
    """Rewrite a Strict OOXML workbook into the transitional schema."""
    with zipfile.ZipFile(src) as zin, \
         zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith((".xml", ".rels")):
                for old, new in STRICT_TO_TRANSITIONAL:
                    data = data.replace(old, new)
            zout.writestr(item, data)
    return dst


def parse_value(raw):
    """Return (value, flag). Suppressed and unavailable cells keep their meaning.

    A suppressed cell is not zero and must never be summed as though it were, so
    it comes back as None alongside the ceiling the NDIA disclosed.
    """
    if raw is None:
        return None, "missing"
    if isinstance(raw, (int, float)):
        return float(raw), None
    text = str(raw).strip()
    match = SUPPRESSED.match(text)
    if match:
        return None, f"suppressed:<{match.group(1)}"
    if text.lower() in {"n/a", "na", "-", ""}:
        return None, "unavailable"
    cleaned = re.sub(r"[,$%\s]", "", text)
    try:
        return float(cleaned), None
    except ValueError:
        return None, "text"


def read_table(workbook, sheet_name):
    """Read one Supplement P sheet into {'columns': [...], 'rows': {label: {...}}}.

    Row 1 is the table caption, row 2 the header, then data rows followed by
    footnotes. Footnotes are long prose in the label column, so length
    discriminates them from region names.
    """
    sheet = workbook[sheet_name]
    raw_rows = list(sheet.iter_rows(values_only=True))
    header = [h for h in raw_rows[1] if h is not None]
    columns = [str(c).strip() for c in header[1:]]

    rows, notes = {}, []
    for raw in raw_rows[2:]:
        label = raw[0]
        if label is None:
            continue
        label = str(label).strip()
        if label.startswith("Back to") or len(label) > 60:
            if len(label) > 60:
                notes.append(label)
            continue
        record, flags = {}, {}
        for column, cell in zip(columns, raw[1:len(header)]):
            value, flag = parse_value(cell)
            record[column] = value
            if flag:
                flags[column] = flag
        rows[label] = {"values": record, "flags": flags}

    return {
        "caption": str(raw_rows[0][0]).strip() if raw_rows[0][0] else sheet_name,
        "columns": columns,
        "rows": rows,
        "notes": notes,
    }


def places_by_category(row_values):
    """Collapse a dwelling-type cross-tab row into places per design category.

    Each column label names a dwelling form and its resident count, so
    dwellings x residents gives resident capacity ("places") — the unit that is
    directly comparable with a participant count.
    """
    totals: dict[str, float] = {}
    for label, value in row_values.items():
        if label == "Total" or value is None:
            continue
        match = DWELLING_LABEL.match(label)
        if not match:
            continue
        residents = int(match.group("residents") or match.group("first"))
        category = match.group("category").strip()
        totals[category] = totals.get(category, 0.0) + value * residents
    return totals


def split_region(label):
    """'NSW - Capital Region' -> ('NSW', 'Capital Region'); state totals -> None."""
    if label == "Total":
        return ("National", None)
    if " - " in label:
        state, region = label.split(" - ", 1)
        return (state, region)
    return (label, None)


def build_geography(supply_dwellings, demand_status, level):
    """Every row label that carries region-level data, in workbook order."""
    seen, geography = set(), []
    for label in list(supply_dwellings["rows"]) + list(demand_status["rows"]):
        if label in seen or label == "Total":
            continue
        seen.add(label)
        state, region = split_region(label)
        if region is None:
            continue
        geography.append({"key": label, "state": state, "region": region, "level": level})
    return geography


def assemble(workbook, level):
    """Join the supply, pipeline and demand tables for one geographic level."""
    if level == "SA4":
        sheets = {
            "dwellings_by_build_type": "Table P.4",
            "dwellings_by_category": "Table P.5",
            "dwellings_by_max_residents": "Table P.6",
            "newbuild_places_by_category": "Table P.7",
            "pipeline_dwellings_by_category": "Table P.8",
            "demand_by_status": "Table P.9",
            "demand_by_category": "Table P.10",
            "newbuild_detail": "Table P.11",
            "existing_legacy_detail": "Table P.12",
            "pipeline_detail": "Table P.16",
        }
    else:
        sheets = {
            "dwellings_by_build_type": "Table P.13",
            "dwellings_by_category": "Table P.14",
            "dwellings_by_max_residents": "Table P.15",
            "demand_by_status": "Table P.17",
            "demand_by_category": "Table P.18",
        }

    tables = {key: read_table(workbook, name) for key, name in sheets.items()}
    geography = build_geography(
        tables["dwellings_by_category"], tables["demand_by_status"], level
    )

    records = []
    for place in geography:
        key = place["key"]
        record = dict(place)

        stock = tables["dwellings_by_category"]["rows"].get(key, {}).get("values", {})
        demand = tables["demand_by_category"]["rows"].get(key, {}).get("values", {})
        status = tables["demand_by_status"]["rows"].get(key, {}).get("values", {})

        newbuild_places, existing_places, pipeline_places, pipeline_stock = {}, {}, {}, {}
        if level == "SA4":
            newbuild_places = places_by_category(
                tables["newbuild_detail"]["rows"].get(key, {}).get("values", {}))
            existing_places = places_by_category(
                tables["existing_legacy_detail"]["rows"].get(key, {}).get("values", {}))
            pipeline_places = places_by_category(
                tables["pipeline_detail"]["rows"].get(key, {}).get("values", {}))
            pipeline_stock = tables["pipeline_dwellings_by_category"]["rows"].get(
                key, {}).get("values", {})

        record["categories"] = {}
        for category in DESIGN_CATEGORIES:
            enrolled_places = (newbuild_places.get(category, 0.0)
                               + existing_places.get(category, 0.0))
            need = demand.get(category)
            record["categories"][category] = {
                "enrolled_dwellings": stock.get(category),
                "enrolled_places": enrolled_places if level == "SA4" else None,
                "newbuild_places": newbuild_places.get(category, 0.0) or None,
                "existing_legacy_places": existing_places.get(category, 0.0) or None,
                "pipeline_dwellings": pipeline_stock.get(category),
                "pipeline_places": pipeline_places.get(category, 0.0) or None,
                "participants_with_need": need,
                # Places per participant needing this category. Below 1.0 means
                # fewer resident places exist than participants seeking them.
                "places_per_participant": (
                    round(enrolled_places / need, 3)
                    if level == "SA4" and need not in (None, 0) else None
                ),
            }

        record["totals"] = {
            "enrolled_dwellings": stock.get("Total"),
            "participants_sda_in_use": status.get(
                next((c for c in status if "in use" in c.lower()), ""), None),
            "participants_eligible_not_using": status.get(
                next((c for c in status if "eligible" in c.lower()), ""), None),
            "participants_with_need": next(
                (v for c, v in demand.items() if c.lower().startswith("total")), None),
            "unallocated_demand": demand.get("Missing"),
        }
        records.append(record)

    return {"tables": tables, "records": records}


def national_summary(records):
    """Aggregate the comparable categories across every region."""
    summary = {}
    for category in COMPARABLE_CATEGORIES:
        places = need = pipeline = dwellings = 0.0
        for record in records:
            cell = record["categories"][category]
            places += cell["enrolled_places"] or 0.0
            need += cell["participants_with_need"] or 0.0
            pipeline += cell["pipeline_places"] or 0.0
            dwellings += cell["enrolled_dwellings"] or 0.0
        summary[category] = {
            "enrolled_dwellings": int(dwellings),
            "enrolled_places": int(places),
            "participants_with_need": int(need),
            "pipeline_places": int(pipeline),
            "places_per_participant": round(places / need, 3) if need else None,
        }
    return summary


def extract_national_trend(source: Path, figure_prose=()):
    """Recover the quarterly national series from Figure P.1's embedded charts.

    The figure's numbers exist only inside the chart XML — the sheet itself holds
    just the alt-text description — so this is the one place the workbook carries
    a time series.
    """
    wanted = {
        "Participants with SDA in use": "sda_in_use",
        "Participants SDA eligible, not yet using SDA": "sda_eligible_not_using",
        "Active participants with SIL supports": "sil_participants",
        "Annualised SDA supports in active plans ($m)": "sda_annualised",
        "Annualised committed support for participants with SIL ($m)": "sil_annualised",
    }
    series, quarters = {}, []
    with zipfile.ZipFile(source) as archive:
        charts = [n for n in archive.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)]
        for name in sorted(charts):
            xml = archive.read(name).decode("utf-8", "replace")
            # Excel parks filtered-out series in the c15 extension namespace, so
            # both tags have to be split on or later series are read as one block.
            for block in re.split(r"<c(?:15)?:ser>", xml)[1:]:
                values = re.findall(r"<c:v>([^<]*)</c:v>", block)
                if not values:
                    continue
                label = values[0]
                periods = [v for v in values[1:] if re.match(r"^[A-Z][a-z]{2}-\d{2}$", v)]
                numbers = [float(v) for v in values[1:]
                           if re.match(r"^-?\d+(\.\d+)?$", v)]
                if label in wanted and len(periods) == len(numbers) and periods:
                    quarters = quarters or periods
                    series[wanted[label]] = numbers
    # The enrolled-dwellings series has no chart of its own: its numbers survive
    # only in the figure's accessibility description, so read them from there.
    if "enrolled_dwellings" not in series:
        month = {m: i for i, m in enumerate(
            "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
        found = {}
        for prose in figure_prose:
            if "enrolled dwellings" not in prose.lower():
                continue
            for name, year, count in re.findall(
                    r"In (\w+) (\d{4}) there were ([\d,]+) enrolled dwellings", prose):
                if name[:3] in month:
                    label = f"{name[:3]}-{year[2:]}"
                    found[label] = float(count.replace(",", ""))
        if found and quarters:
            series["enrolled_dwellings"] = [found.get(q) for q in quarters]

    return {"quarters": quarters, "series": series}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=Path("data"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    converted = args.out / "_transitional.xlsx"
    to_transitional(args.workbook, converted)
    workbook = openpyxl.load_workbook(converted, read_only=True, data_only=True)

    figure_prose = [str(cell) for row in workbook["Figure P.1"].iter_rows(values_only=True)
                    for cell in row if cell]

    sa4 = assemble(workbook, "SA4")
    sa3 = assemble(workbook, "SA3")

    bundle = {
        "source": args.workbook.name,
        "period": read_table(workbook, "Table P.5")["caption"],
        "design_categories": DESIGN_CATEGORIES,
        "comparable_categories": COMPARABLE_CATEGORIES,
        "national_trend": extract_national_trend(args.workbook, figure_prose),
        "national_summary": national_summary(sa4["records"]),
        "sa4": sa4["records"],
        "sa3": sa3["records"],
    }

    target = args.out / "sda.json"
    target.write_text(json.dumps(bundle, indent=1))
    converted.unlink()

    print(f"wrote {target}  ({target.stat().st_size / 1024:.0f} KB)")
    print(f"  SA4 regions: {len(sa4['records'])}   SA3 regions: {len(sa3['records'])}")
    print(f"  quarters of national trend: {len(bundle['national_trend']['quarters'])}")
    for category, cell in bundle["national_summary"].items():
        print(f"  {category:<24} places={cell['enrolled_places']:>6}"
              f"  need={cell['participants_with_need']:>6}"
              f"  ratio={cell['places_per_participant']}")


if __name__ == "__main__":
    main()
