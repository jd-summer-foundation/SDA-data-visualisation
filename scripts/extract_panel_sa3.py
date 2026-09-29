#!/usr/bin/env python3
"""Build the SA3 panel from every Supplement P edition in data/supplements/.

extract_panel.py reads the SA4 tables; this reads the SA3 ones, which the NDIA
publishes alongside them in every edition, and places each SA3 in its SA4 so
the two panels can be read together. What SA3 carries is narrower than SA4:

  published at SA3         enrolled dwellings by design category, dwellings by
                           build type and by maximum residents (totals only),
                           participants by status, need by design category
  not published at SA3     new-build places (P.7), the dwelling-form
                           cross-tabs, and the pipeline

so there are no enrolled places by category and no places not in SDA use at
SA3. Places from dwellings by maximum residents (6+ counted as six) is the
only places measure, and it is a total.

Supplement P names each SA3 but not its SA4, and gives no codes. Both come
from the ABS ASGS Edition 3 (2021) allocation file, data/asgs_2021_sa2.csv,
joined on state and SA3 name. The join is checked, not trusted: the build
fails unless every SA3 figure sums to its SA4's figure in the SA4 panel, for
every measure, category and edition.

Usage:  python3 scripts/extract_panel_sa3.py [data/supplements] [-o data/panel]

Reads data/panel/panel.csv (build it first) and writes, into the output
directory:
  panel_sa3.csv       the SA3 panel, in panel.csv's columns
  sa3_sa4.csv         each SA3's SA4, with both ASGS 2021 codes
  validation_sa3.json the mapping, the reconciliation and the table map
  VALIDATION_SA3.md   the same, written out for reading
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from extract_panel import (
    CATEGORY_ORDER,
    PANEL_COLUMNS,
    build_panel,
    fmt,
    read_edition,
    write_csv,
)
from validate_panel import TOLERANCE

STATE_ABBREVIATIONS = {
    "Australian Capital Territory": "ACT", "New South Wales": "NSW",
    "Northern Territory": "NT", "Queensland": "QLD", "South Australia": "SA",
    "Tasmania": "TAS", "Victoria": "VIC", "Western Australia": "WA",
}

# Supplement P's spelling where it differs from ASGS 2021's. Every edition
# writes "Urriarra"; the ABS, the ACT Government and the locality itself
# write "Uriarra".
SUPPLEMENT_SPELLINGS = {"ACT - Urriarra - Namadgi": "ACT - Uriarra - Namadgi"}

LEVEL_ORDER = {"SA3": 0, "Other": 1}
EXAMPLES = 5

# Measure families the SA3 tables can support, edition by edition.
FAMILIES = [
    ("Enrolled dwellings by category", "enrolled_dwellings", "Improved Liveability"),
    ("New-build dwellings (all categories)", "dwellings_new_build", "Total"),
    ("Places from dwellings by maximum residents (total)", "places_from_max_residents",
     "Total"),
    ("Participants with SDA in use", "participants_sda_in_use", "Total"),
    ("Participants eligible, not yet using", "participants_eligible_not_using", "Total"),
    ("Participants with need by category", "participants_with_need", "Improved Liveability"),
    ("Participants seeking SDA by category (legacy CRM)", "legacy_participants_seeking",
     "Improved Liveability"),
]

NOT_AT_SA3 = [
    ("Enrolled places by category", "P.7 new-build places and the dwelling-form cross-tabs "
     "(P.11/P.12) are SA4 only"),
    ("New-build or existing dwellings by category", "build type is published as a total"),
    ("Places not in SDA use", "needs enrolled places; places from maximum residents is "
     "the nearest total"),
    ("Pipeline dwellings or places", "P.8 and P.16 are SA4 only"),
]


# --------------------------------------------------------------------------
# SA3 -> SA4
# --------------------------------------------------------------------------

def read_sa4_panel(path: Path):
    """The SA4 panel's values, and its SA4 ids."""
    values, sa4 = {}, set()
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["level"] == "SA4":
                sa4.add(row["geography"])
            if row["value"] != "":
                values[(row["as_at"], row["geography"], row["category"], row["measure"])] = \
                    float(row["value"])
    return values, sa4


def read_asgs(path: Path):
    """ASGS 2021 SA3s as '<STATE> - <name>' -> (SA3 code, SA4 name, SA4 code).

    Read from the ABS SA2 allocation file. The non-spatial SA3s ('No usual
    address', 'Migratory - Offshore - Shipping') and Other Territories are
    kept, harmlessly: Supplement P publishes none of them.
    """
    sa3 = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            state = STATE_ABBREVIATIONS.get(row["STATE_NAME_2021"])
            if state is None:
                continue
            entry = (row["SA3_CODE_2021"], row["SA4_NAME_2021"], row["SA4_CODE_2021"])
            label = f"{state} - {row['SA3_NAME_2021']}"
            if sa3.setdefault(label, entry) != entry:
                raise ValueError(f"{label}: two SA3 codes or SA4s in the allocation file")
    return sa3


def sa3_parents(labels, asgs, sa4_ids):
    """Place every SA3 Supplement P publishes in its ASGS 2021 SA4, or fail.

    Returns label -> (SA4 id, SA3 code, SA4 code). An SA3 the allocation file
    does not know, or an SA4 the SA4 panel does not know, stops the build
    rather than being guessed at.
    """
    mapping = {}
    for label in labels:
        key = SUPPLEMENT_SPELLINGS.get(label, label)
        if key not in asgs:
            raise ValueError(f"{label}: not an ASGS 2021 SA3; if it is a spelling, "
                             "add it to SUPPLEMENT_SPELLINGS")
        sa3_code, sa4_name, sa4_code = asgs[key]
        geo = f"sa4:{label.split(' - ', 1)[0]} - {sa4_name}"
        if geo not in sa4_ids:
            raise ValueError(f"{label}: ASGS 2021 SA4 {geo} is not in the SA4 panel")
        mapping[label] = (geo, sa3_code, sa4_code)
    unused = set(SUPPLEMENT_SPELLINGS) - set(labels)
    if unused:
        raise ValueError(f"SUPPLEMENT_SPELLINGS entries no edition publishes: {sorted(unused)}")
    return mapping


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

class Check:
    def __init__(self, name):
        self.name, self.compared, self.examples, self.mismatched = name, 0, [], 0

    def compare(self, key, got, want):
        self.compared += 1
        if abs(got - want) > TOLERANCE:
            self.mismatched += 1
            if len(self.examples) < EXAMPLES:
                self.examples.append({"key": list(key), "sum": got, "published": want})

    def report(self):
        return {"check": self.name, "compared": self.compared,
                "mismatched": self.mismatched, "examples": self.examples}


def reconcile(as_at, panel, mapping, sa4_values):
    """SA3 figures sum to the SA4 panel; SA3 + Other rows sum to the state
    rows of the same SA3 table, and those to the SA4 panel's state rows."""
    to_sa4, to_state, state_vs_sa4 = (Check("SA3 = SA4 panel"),
                                      Check("SA3 + Other = state (SA3 table)"),
                                      Check("state (SA3 table) = state (SA4 panel)"))
    sums, state_sums, incomplete = defaultdict(float), defaultdict(float), set()
    for (geo, category, measure), (value, _, _) in panel.records.items():
        _, level, state = panel.geos[geo]
        if level not in ("SA3", "Other"):
            continue
        keys = [("state:" + state, category, measure)]
        if level == "SA3":
            keys.append((mapping[geo[4:]][0], category, measure))
        for key in keys:
            if value is None:
                incomplete.add(key)
            elif key[0].startswith("state:"):
                state_sums[key] += value
            else:
                sums[key] += value
    for key, total in sorted(sums.items()):
        want = sa4_values.get((as_at,) + key)
        if want is not None and key not in incomplete:
            to_sa4.compare(key, total, want)
    for key, total in sorted(state_sums.items()):
        published = panel.get(*key)
        if published is not None and key not in incomplete:
            to_state.compare(key, total, published)
    for (geo, category, measure), (value, _, _) in sorted(panel.records.items()):
        if panel.geos[geo][1] != "State" or value is None:
            continue
        want = sa4_values.get((as_at, geo, category, measure))
        if want is not None:
            state_vs_sa4.compare((geo, category, measure), value, want)
    return [c.report() for c in (to_sa4, to_state, state_vs_sa4)], len(incomplete)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def panel_rows(as_at, panel):
    """SA3 and unplaced 'Other' rows, in the SA4 panel's columns. Each SA3's
    SA4 is in sa3_sa4.csv rather than repeated on every row."""
    rows = []
    for (geo, category, measure), (value, flag, source) in panel.records.items():
        _, level, state = panel.geos[geo]
        if level not in LEVEL_ORDER:
            continue
        rows.append([as_at, geo, level, state or "", category, measure, fmt(value),
                     flag, source])
    rows.sort(key=lambda r: (r[0], LEVEL_ORDER[r[2]], r[1],
                             CATEGORY_ORDER.index(r[4]), r[5]))
    return rows


def _n(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def to_markdown(report):
    eds = [e["edition"] for e in report["editions"]]
    m = report["mapping"]
    out = ["# Supplement P SA3 panel: validation report", "",
           "Generated by `scripts/extract_panel_sa3.py` from every workbook in "
           "`data/supplements/`. Do not edit by hand.", "",
           "## What SA3 carries", "",
           "A tick means the measure is published (or derivable) at SA3 in that edition.", "",
           "| Measure | " + " | ".join(eds) + " |",
           "| --- | " + " | ".join("---" for _ in eds) + " |"]
    for row in report["usability"]:
        out.append(f"| {row['label']} | " + " | ".join(
            "✓" if e in row["editions"] else "" for e in eds) + " |")
    out += ["", "Not published at SA3:", ""]
    out += [f"- **{what}**: {why}." for what, why in NOT_AT_SA3]
    out += ["", "## SA3 to SA4", "",
            f"{m['sa3']} SA3 regions, in {m['sa4']} SA4s (median {m['median_per_sa4']} "
            f"per SA4, at most {m['max_per_sa4']}; {m['sa4_with_one']} SA4s are a single "
            "SA3). Supplement P names the SA3 but not its SA4 and gives no codes; both come "
            "from the ABS ASGS 2021 allocation file (`data/asgs_2021_sa2.csv`), joined on "
            "state and SA3 name. Where Supplement P spells an SA3 differently:", "",
            "| Supplement P | ASGS 2021 |", "| --- | --- |"]
    out += [f"| {x['supplement_p']} | {x['asgs_2021']} |" for x in m["spellings"]]
    out += ["", "Every placement is tested by the reconciliation below: an SA3 in the wrong "
            "SA4 leaves two SA4s that no longer sum.", "",
            "## Checks per quarter", "",
            "Each cell is mismatches / comparisons, across every measure and category the "
            "two panels share.", "",
            "| Edition | As at | SA3 regions | Added | Removed | " +
            " | ".join(c["check"] for c in report["editions"][0]["checks"]) +
            " | Suppressed or incomplete |",
            "| --- | --- | --- | --- | --- | " +
            " | ".join("---" for _ in report["editions"][0]["checks"]) + " | --- |"]
    for e in report["editions"]:
        out.append(f"| {e['edition']} | {e['as_at']} | {e['sa3_regions']} | "
                   f"{', '.join(e['added']) or '—'} | {', '.join(e['removed']) or '—'} | " +
                   " | ".join(f"{c['mismatched']}/{c['compared']:,}" for c in e["checks"]) +
                   f" | {e['incomplete']} |")
    flagged = [(e["edition"], k, n) for e in report["editions"] for k, n in e["flags"].items()]
    if flagged:
        out += ["", "Flagged cells, in any SA3 table (not_using is not read into the panel): "
                + "; ".join(f"{ed} {k} ({n})" for ed, k, n in flagged)
                + "."]
    out += ["", "## Table map", "",
            "Every SA3 table, by the sheet it sits on in each edition.", "",
            "| Table | " + " | ".join(eds) + " |",
            "| --- | " + " | ".join("---" for _ in eds) + " |"]
    roles = sorted({r for e in report["editions"] for r in e["tables"]})
    for role in roles:
        cells = []
        for e in report["editions"]:
            t = e["tables"].get(role)
            cells.append("" if not t else t["sheet"].replace("Table ", "")
                         + (f" {t['scheme']}" if t["scheme"] else ""))
        out.append(f"| {role} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("supplements", type=Path, nargs="?", default=Path("data/supplements"))
    parser.add_argument("-o", "--out", type=Path, default=Path("data/panel"))
    parser.add_argument("--sa4-panel", type=Path, default=Path("data/panel/panel.csv"))
    parser.add_argument("--asgs", type=Path, default=Path("data/asgs_2021_sa2.csv"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sa4_values, sa4_ids = read_sa4_panel(args.sa4_panel)
    asgs = read_asgs(args.asgs)

    paths = sorted(p for p in args.supplements.iterdir()
                   if re.search(r"Supplement_P_SDA_\d{4}-\d{2}_Q\d\.xls[xb]$", p.name))
    editions = []
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            edition = read_edition(path, Path(tmp), level="SA3")
            editions.append((edition, build_panel(edition, level="SA3")))
            print(f"  read {edition['edition']} (as at {edition['as_at']})", flush=True)

    labels = sorted({g[4:] for _, p in editions for g, (_, lvl, _) in p.geos.items()
                     if lvl == "SA3"})
    mapping = sa3_parents(labels, asgs, sa4_ids)

    rows, per_edition, previous = [], [], None
    for edition, panel in editions:
        as_at = edition["as_at"]
        rows += panel_rows(as_at, panel)
        checks, incomplete = reconcile(as_at, panel, mapping, sa4_values)
        present = {g[4:] for g, (_, lvl, _) in panel.geos.items() if lvl == "SA3"}
        flags = Counter(f"{e['role']}:{f}" for e in edition["tables"].values()
                        for r in e["rows"].values() for f in r["flags"].values())
        per_edition.append({
            "edition": edition["edition"], "as_at": as_at, "sa3_regions": len(present),
            "added": sorted(present - previous) if previous is not None else [],
            "removed": sorted(previous - present) if previous is not None else [],
            "checks": checks, "incomplete": incomplete, "flags": dict(sorted(flags.items())),
            "tables": {t["role"]: {"sheet": t["sheet"], "scheme": t["scheme"]}
                       for t in edition["table_map"] if t["level"] == "SA3"},
        })
        previous = present

    write_csv(args.out / "panel_sa3.csv", PANEL_COLUMNS, rows)
    write_csv(args.out / "sa3_sa4.csv", ["state", "sa3", "sa3_code", "sa4", "sa4_code"],
              [[label.split(" - ", 1)[0], f"sa3:{label}", sa3_code, sa4, sa4_code]
               for label, (sa4, sa3_code, sa4_code) in sorted(mapping.items())])

    children = Counter(sa4 for sa4, _, _ in mapping.values())
    counts = sorted(children.values())
    report = {
        "editions": per_edition,
        "mapping": {"sa3": len(mapping), "sa4": len(children),
                    "median_per_sa4": counts[len(counts) // 2], "max_per_sa4": counts[-1],
                    "sa4_with_one": sum(n == 1 for n in counts),
                    "spellings": [{"supplement_p": k, "asgs_2021": v}
                                  for k, v in sorted(SUPPLEMENT_SPELLINGS.items())]},
        "usability": [{"label": label, "measure": measure, "editions": [
            e["edition"] for e, p in editions
            if any(p.geos[g][1] == "SA3" and v is not None
                   for (g, c, m), (v, _, _) in p.records.items()
                   if c == category and m == measure)]}
            for label, measure, category in FAMILIES],
    }
    (args.out / "validation_sa3.json").write_text(json.dumps(report, indent=1) + "\n")
    (args.out / "VALIDATION_SA3.md").write_text(to_markdown(report))

    print(f"wrote {args.out}/panel_sa3.csv  ({len(rows):,} rows, "
          f"{(args.out / 'panel_sa3.csv').stat().st_size / 1e6:.1f} MB)")
    bad = [(e["edition"], c["check"], c["examples"]) for e in per_edition
           for c in e["checks"] if c["mismatched"]]
    for b in bad:
        print("  MISMATCH", *b)
    if bad:
        raise SystemExit("SA3 panel does not reconcile: fix the mapping before using it")


if __name__ == "__main__":
    main()
