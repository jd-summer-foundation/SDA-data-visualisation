"""Checks on the quarterly panel, edition by edition and across editions.

Called by extract_panel.py; kept apart only for size. Nothing here changes a
figure. It measures how far each quarter can be trusted, and names the
places where the series breaks, so the analysis built on the panel can say
what it rests on rather than smoothing over it.
"""
from __future__ import annotations

from extract_panel import (
    DESIGN_CATEGORIES,
    RESIDENT_COUNTS,
    crosstab,
    geography,
)

TOLERANCE = 0.5          # counts are integers; anything within half a unit agrees
EXAMPLES = 5             # mismatches listed per check

# Footnote and intro phrases that announce a change in rules or method. Each
# is reported against the first edition that carries it.
ANNOUNCEMENTS = [
    ("in-kind arrangements for tasmania have phased out",
     "In-kind dwellings phased out; in-kind tables dropped after 2022-23 Q4"),
    ("sda funding, sda in use",
     "Participant status re-based on evidence of SDA use (payments, bookings, address)"),
    ("participants who are sda eligible (sda funding not yet in use)",
     "Status table reduced to 'SDA in use' and 'eligible, not yet using'"),
    ("sda need is defined as participants with sda in use or participants eligible",
     "Need by design category re-introduced, from the latest eligible SDA decision"),
    ('design category of "basic" are now included in "missing"',
     "Basic decisions folded into 'Missing'"),
    ("data for participants and committed supports are as of 2 april",
     "Participant data as at 2 April rather than 31 March (Services Australia incident)"),
    ("not progressed to enrolment within 36 months",
     "Pipeline dwellings not progressed within 36 months removed from 30 March 2026"),
]

# What each panel measure family needs, and so which editions can support it.
FAMILIES = [
    ("Enrolled dwellings by category", "enrolled_dwellings", "Improved Liveability"),
    ("Enrolled places by category", "enrolled_places", "Improved Liveability"),
    ("Pipeline dwellings by category", "pipeline_dwellings", "Improved Liveability"),
    ("Pipeline places by category", "pipeline_places", "Improved Liveability"),
    ("Participants with SDA in use", "participants_sda_in_use", "Total"),
    ("Participants eligible, not yet using", "participants_eligible_not_using", "Total"),
    ("Participants with need by category", "participants_with_need", "Improved Liveability"),
    ("Participants seeking SDA by category (legacy CRM)", "legacy_participants_seeking",
     "Improved Liveability"),
    ("Places not in SDA use", "places_not_in_use", "Total"),
]

NATIONAL_SERIES = [
    ("enrolled_dwellings", "Total"), ("enrolled_places", "Total"),
    ("places_from_max_residents", "Total"),
    ("pipeline_dwellings", "Total"), ("pipeline_places", "Total"),
    ("participants_sda_in_use", "Total"), ("participants_eligible_not_using", "Total"),
    ("participants_total_need", "Total"), ("participants_with_need", "Missing"),
    ("places_not_in_use", "Total"),
]


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= TOLERANCE


class Check:
    """Counts agreements between pairs of figures and keeps a few examples."""

    def __init__(self, name):
        self.name, self.compared, self.mismatched, self.examples = name, 0, 0, []

    def compare(self, where, got, want):
        if got is None or want is None:
            return
        self.compared += 1
        if not close(got, want):
            self.mismatched += 1
            if len(self.examples) < EXAMPLES:
                self.examples.append({"where": where, "got": got, "want": want})

    def result(self):
        return {"check": self.name, "compared": self.compared,
                "mismatched": self.mismatched, "examples": self.examples}


def measures_at(panel, level):
    return sorted({(c, m) for (g, c, m) in panel.records if panel.geos[g][1] == level})


def check_hierarchy(panel):
    """SA4 (and unplaced 'Other') rows sum to their state; states (and
    'Unknown') sum to the national total -- for every measure."""
    by_state, by_level = {}, {}
    for geo_id, (_, level, state) in panel.geos.items():
        by_level.setdefault(level, []).append(geo_id)
        if level in ("SA4", "Other"):
            by_state.setdefault(state, []).append(geo_id)

    down, up = Check("SA4 + Other = state"), Check("states + Unknown = national")
    # Places not in use is undefined for the unplaced 'Other' rows (they have
    # participants but no stock), so a state's figure nets off participants
    # its SDA regions do not. That is a definition, not an inconsistency.
    keys = {(c, m) for (_, c, m) in panel.records if m != "places_not_in_use"}
    for category, measure in sorted(keys):
        for state, children in by_state.items():
            parent = f"state:{state}"
            if not panel.has(parent, category, measure):
                continue
            parts = [panel.get(g, category, measure) for g in children
                     if panel.has(g, category, measure)]
            if parts and all(p is not None for p in parts):
                down.compare(f"{parent} {category} {measure}", sum(parts),
                             panel.get(parent, category, measure))
        if panel.has("national", category, measure):
            parts = [panel.get(g, category, measure)
                     for g in by_level.get("State", []) + by_level.get("Unknown", [])
                     if panel.has(g, category, measure)]
            if parts and all(p is not None for p in parts):
                up.compare(f"national {category} {measure}", sum(parts),
                           panel.get("national", category, measure))
    return [down.result(), up.result()]


def check_identities(edition, panel):
    """Relations that must hold between tables of the same edition."""
    tables = edition["tables"]
    checks = {name: Check(name) for name in (
        "P.4 build types sum to P.5 total",
        "P.6 resident counts sum to P.5 total",
        "P.5 = new-build + existing/legacy cross-tab dwellings, by category",
        "P.8 = pipeline cross-tab dwellings, by category",
        "categories sum to Total (dwellings, new-build places, pipeline, need)",
        "status columns add up",
        "need by category total = status total",
        "not-using table = status 'SDA not in use'",
    )}
    get = panel.get
    build = ["dwellings_existing", "dwellings_legacy", "dwellings_new_build",
             "dwellings_new_build_refurbished"]
    residents = [f"dwellings_max_{n}{'plus' if n == 6 else ''}_resident{'' if n == 1 else 's'}"
                 for n in RESIDENT_COUNTS.values()]
    pipeline_detail = {}
    if "pipeline_detail" in tables:
        for label, row in tables["pipeline_detail"]["rows"].items():
            pipeline_detail[geography(label)[0]] = crosstab(row["values"], row["flags"])

    for geo_id in panel.geos:
        total = get(geo_id, "Total", "enrolled_dwellings")
        if all(panel.has(geo_id, "Total", m) for m in build):
            checks["P.4 build types sum to P.5 total"].compare(
                geo_id, sum(get(geo_id, "Total", m) or 0 for m in build), total)
        if all(panel.has(geo_id, "Total", m) for m in residents):
            checks["P.6 resident counts sum to P.5 total"].compare(
                geo_id, sum(get(geo_id, "Total", m) or 0 for m in residents), total)
        for category in DESIGN_CATEGORIES:
            if panel.has(geo_id, category, "enrolled_dwellings"):
                checks["P.5 = new-build + existing/legacy cross-tab dwellings, by category"].compare(
                    f"{geo_id} {category}",
                    (get(geo_id, category, "newbuild_dwellings") or 0)
                    + (get(geo_id, category, "existing_legacy_dwellings") or 0),
                    get(geo_id, category, "enrolled_dwellings"))
            if panel.has(geo_id, category, "pipeline_dwellings") and geo_id in pipeline_detail:
                cell = pipeline_detail[geo_id].get(category)
                checks["P.8 = pipeline cross-tab dwellings, by category"].compare(
                    f"{geo_id} {category}", cell["dwellings"] if cell else 0,
                    get(geo_id, category, "pipeline_dwellings"))
        for measure in ("enrolled_dwellings", "newbuild_places", "pipeline_dwellings",
                        "participants_with_need", "legacy_participants_seeking",
                        "inkind_dwellings"):
            if not panel.has(geo_id, "Total", measure):
                continue
            parts = [get(geo_id, c, measure) for c in DESIGN_CATEGORIES + ["Not Defined", "Missing"]
                     if panel.has(geo_id, c, measure)]
            checks["categories sum to Total (dwellings, new-build places, pipeline, need)"].compare(
                f"{geo_id} {measure}", sum(p or 0 for p in parts), get(geo_id, "Total", measure))

        status = checks["status columns add up"]
        t = lambda m: get(geo_id, "Total", m)  # noqa: E731
        if panel.has(geo_id, "Total", "legacy_in_sda_not_seeking"):
            status.compare(f"{geo_id} funded = in SDA (not seeking + seeking alternative)",
                           (t("legacy_in_sda_not_seeking") or 0)
                           + (t("legacy_in_sda_seeking_alternative") or 0),
                           t("participants_sda_funded"))
            status.compare(f"{geo_id} total = funded + additional eligible",
                           (t("participants_sda_funded") or 0) + (t("legacy_eligible_unfunded") or 0),
                           t("participants_total_need"))
        elif panel.has(geo_id, "Total", "participants_funded_not_in_use"):
            status.compare(f"{geo_id} funded = in use + not in use",
                           (t("participants_sda_in_use") or 0)
                           + (t("participants_funded_not_in_use") or 0),
                           t("participants_sda_funded"))
            status.compare(f"{geo_id} total = funded + additional eligible",
                           (t("participants_sda_funded") or 0)
                           + (t("participants_eligible_unfunded") or 0),
                           t("participants_total_need"))
        elif panel.has(geo_id, "Total", "participants_sda_in_use"):
            status.compare(f"{geo_id} total = in use + eligible",
                           (t("participants_sda_in_use") or 0)
                           + (t("participants_eligible_not_using") or 0),
                           t("participants_total_need"))
        if panel.has(geo_id, "Total", "participants_with_need"):
            checks["need by category total = status total"].compare(
                geo_id, t("participants_with_need"), t("participants_total_need"))

    if "not_using" in tables:
        col = next(c for c in tables["not_using"]["columns"] if "not in use" in c.lower()
                   and "percentage" not in c.lower())
        for label, row in tables["not_using"]["rows"].items():
            geo_id = geography(label)[0]
            checks["not-using table = status 'SDA not in use'"].compare(
                geo_id, row["values"].get(col), get(geo_id, "Total", "participants_funded_not_in_use"))
    return [c.result() for c in checks.values() if c.compared]


def calibrate(edition, panel):
    """The two checks on the places derivation, as extract_sda runs them,
    over the 88 SA4 regions: P.7 against the same arithmetic run over P.11,
    and total places against P.6's dwellings by maximum residents."""
    tables = edition["tables"]
    out = {}
    if "newbuild_places" in tables and "newbuild_detail" in tables:
        checked = exact = 0
        worst, published_total, derived_total = 0.0, 0.0, 0.0
        detail = tables["newbuild_detail"]["rows"]
        for label, row in tables["newbuild_places"]["rows"].items():
            if geography(label)[1] != "SA4" or label not in detail:
                continue
            derived = crosstab(detail[label]["values"], detail[label]["flags"])
            for category, want in row["values"].items():
                if category not in DESIGN_CATEGORIES or want is None:
                    continue
                got = (derived.get(category) or {"places": 0.0})["places"]
                checked += 1
                exact += abs(want - got) <= TOLERANCE
                worst = max(worst, abs(want - got))
                published_total += want
                derived_total += got
        out["p7"] = {
            "values_checked": checked, "exact": exact,
            "exact_share": round(exact / checked, 4) if checked else None,
            "largest_difference_places": worst,
            "net_bias": round(derived_total / published_total - 1, 5) if published_total else None,
        }
    checked = within = 0
    worst, worst_region = 0.0, None
    for geo_id, (_, level, _) in panel.geos.items():
        if level != "SA4":
            continue
        derived = panel.get(geo_id, "Total", "enrolled_places")
        expected = panel.get(geo_id, "Total", "places_from_max_residents")
        if derived is None or not expected:
            continue
        checked += 1
        gap = derived - expected
        within += abs(gap) <= 0.02 * expected
        if abs(gap) > abs(worst):
            worst, worst_region = gap, geo_id
    out["p6"] = {
        "regions_checked": checked, "within_2_percent": within,
        "largest_difference_places": worst, "largest_difference_region": worst_region,
        "national_derived": panel.get("national", "Total", "enrolled_places"),
        "national_from_max_residents": panel.get("national", "Total", "places_from_max_residents"),
    }
    return out


def figure_against_tables(edition, panel):
    """The figure's own latest quarter against the same edition's tables."""
    q = edition["as_at"]
    pairs = [("enrolled_dwellings", "enrolled_dwellings"),
             ("participants_sda_in_use", "participants_sda_in_use"),
             ("participants_eligible_not_using", "participants_eligible_not_using"),
             ("participants_with_sda_supports", "participants_sda_funded")]
    out = []
    for series, measure in pairs:
        fig = edition["figure"].get((series, q))
        table = panel.get("national", "Total", measure)
        if fig is not None and table is not None:
            out.append({"series": series, "figure": fig, "table": table,
                        "agrees": close(fig, table)})
    return out


def figure_prose_against_chart(edition):
    """Where the chart XML can be read, does it say what the prose says?"""
    agree, disagree = 0, []
    prose = edition["figure"]
    for key, value in edition["chart"].items():
        if key in prose:
            if close(prose[key], value):
                agree += 1
            else:
                disagree.append({"series": key[0], "quarter": key[1],
                                 "prose": prose[key], "chart": value})
    # A prose series that matches a *different* chart series point for point
    # has been given the wrong label.
    mislabelled = []
    by_series = {}
    for (series, quarter), value in prose.items():
        by_series.setdefault(series, {})[quarter] = value
    chart_by_series = {}
    for (series, quarter), value in edition["chart"].items():
        chart_by_series.setdefault(series, {})[quarter] = value
    for series, values in by_series.items():
        if series in chart_by_series:
            continue
        for other, chart_values in chart_by_series.items():
            shared = [q for q in values if q in chart_values]
            if len(shared) >= 4 and all(close(values[q], chart_values[q]) for q in shared):
                mislabelled.append({"prose_label": series, "is_actually": other,
                                    "quarters": len(shared)})
    return {"agree": agree, "disagree": disagree[:EXAMPLES],
            "disagree_count": len(disagree), "mislabelled": mislabelled}


def figure_revisions(editions):
    """Figure P.1 overlaps between editions: every quarter is restated by up
    to thirteen editions, and they should agree."""
    seen = {}
    for e in editions:
        for (series, quarter), value in e["figure"].items():
            seen.setdefault((series, quarter), []).append((e["edition"], value))
    revised = []
    agreeing = 0
    for (series, quarter), reports in sorted(seen.items()):
        if len(reports) < 2:
            continue
        values = {v for _, v in reports}
        if len(values) == 1:
            agreeing += 1
        else:
            revised.append({"series": series, "quarter": quarter,
                            "reports": [{"edition": ed, "value": v} for ed, v in reports]})
    return {"overlapping_points": agreeing + len(revised), "agreeing": agreeing,
            "revised": revised}


def region_sets(editions, panels):
    reference = None
    out = []
    for e, p in zip(editions, panels):
        sa4 = {g for g, (_, lvl, _) in p.geos.items() if lvl == "SA4"}
        stock = {geography(label)[0] for label in e["tables"]["stock_categories"]["rows"]
                 if geography(label)[1] == "SA4"}
        other = sorted(g for g, (_, lvl, _) in p.geos.items() if lvl == "Other")
        if reference is None:
            reference = stock
        out.append({"edition": e["edition"], "sa4_in_stock_tables": len(stock),
                    "sa4_anywhere": len(sa4),
                    "added": sorted(stock - reference), "removed": sorted(reference - stock),
                    "unplaced_other_rows": other})
    return out


def column_changes(editions):
    """Per role: the editions where it appears, disappears, changes scheme
    or gains/loses columns. Captions are compared only through the role."""
    breaks = []
    last_seen, last_tables, present = {}, {}, None
    for e in editions:
        current = {t["role"]: t for t in e["table_map"] if t["level"] == "SA4"}
        if present is not None:
            for role in sorted(present - set(current)):
                breaks.append({"edition": e["edition"], "role": role, "change": "table absent"})
            for role in sorted(set(current) - present):
                breaks.append({"edition": e["edition"], "role": role, "change": "table appears"})
        # A table that returns after a gap is compared with its last sighting.
        for role, b in sorted(current.items()):
            a = last_seen.get(role)
            if not a:
                continue
            if a["scheme"] != b["scheme"]:
                breaks.append({"edition": e["edition"], "role": role,
                               "change": f"scheme {a['scheme']} -> {b['scheme']}"})
            dropped = [c for c in a["columns"] if c not in b["columns"]]
            added = [c for c in b["columns"] if c not in a["columns"]]
            if dropped or added:
                # What the dropped columns held nationally when last published,
                # so a break carries its size.
                before = last_tables.get(role, {}).get("rows", {}).get("Total", {}).get("values", {})
                counts = [c for c in dropped
                          if not any(w in c.lower() for w in ("total", "percentage"))]
                held = [before.get(c) for c in counts] if a["scheme"] == b["scheme"] else []
                breaks.append({"edition": e["edition"], "role": role, "change": "columns changed",
                               "dropped": dropped, "added": added,
                               "dropped_national_before": (sum(held) if held and all(
                                   isinstance(v, (int, float)) for v in held) else None)})
        last_seen.update(current)
        last_tables.update(e["tables"])
        present = set(current)
    return breaks


def announcements(editions):
    out = []
    for phrase, meaning in ANNOUNCEMENTS:
        for e in editions:
            texts = list(e["intro"]) + [n for t in e["tables"].values() for n in t["notes"]]
            if any(phrase in " ".join(t.lower().split()) for t in texts):
                out.append({"edition": e["edition"], "announcement": meaning})
                break
    return out


def usability(editions, panels):
    rows = []
    for label, measure, category in FAMILIES:
        present = [e["edition"] for e, p in zip(editions, panels)
                   if any(p.get(g, category, measure) is not None
                          for g, (_, lvl, _) in p.geos.items() if lvl == "SA4")]
        rows.append({"family": label, "measure": measure, "editions": present})
    return rows


def national_series(editions, panels):
    out = []
    for e, p in zip(editions, panels):
        row = {"edition": e["edition"], "as_at": e["as_at"]}
        for measure, category in NATIONAL_SERIES:
            row[f"{measure}:{category}"] = p.get("national", category, measure)
        out.append(row)
    return out


def validate(editions, panels):
    per_edition = []
    for e, p in zip(editions, panels):
        suppressed = sum(len(row["flags"]) for t in e["tables"].values()
                         for row in t["rows"].values())
        negative = sorted(g for g, (_, lvl, _) in p.geos.items()
                          if lvl == "SA4" and (p.get(g, "Total", "places_not_in_use") or 0) < 0)
        p7_defects = sorted(f"{g} {c}" for (g, c, m), (_, flag, _) in p.records.items()
                            if m == "enrolled_places" and flag == "p7_zero_with_dwellings"
                            and p.geos[g][1] == "SA4")
        quarters = sorted({q for (_, q) in e["figure"]})
        per_edition.append({
            "edition": e["edition"], "source": e["source"], "as_at": e["as_at"],
            "figure_p1_quarters": [quarters[0], quarters[-1]] if quarters else None,
            "p7_zero_with_dwellings": p7_defects,
            "table_map": [{k: t[k] for k in ("sheet", "role", "level", "scheme")}
                          | {"columns": len(t["columns"])} for t in e["table_map"]],
            "flagged_cells_sa4_tables": suppressed,
            "duplicate_rows_dropped": {t["sheet"]: t["duplicates"]
                                       for t in e["tables"].values() if t["duplicates"]},
            "hierarchy": check_hierarchy(p),
            "identities": check_identities(e, p),
            "calibration": calibrate(e, p),
            "figure_vs_tables": figure_against_tables(e, p),
            "figure_prose_vs_chart": figure_prose_against_chart(e),
            "sa4_with_negative_places_not_in_use": negative,
        })
    return {
        "editions": per_edition,
        "usability": usability(editions, panels),
        "table_breaks": column_changes(editions),
        "announcements": announcements(editions),
        "regions": region_sets(editions, panels),
        "figure_p1_revisions": figure_revisions(editions),
        "national_series": national_series(editions, panels),
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _n(v):
    if v is None:
        return "—"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def to_markdown(report):
    eds = [e["edition"] for e in report["editions"]]
    lines = ["# Supplement P panel: validation report", "",
             "Generated by `scripts/extract_panel.py` from every workbook in "
             "`data/supplements/`. Do not edit by hand.", ""]

    lines += ["## Which quarters support which measure", "",
              "A tick means the measure is published (or derivable) at SA4 in that edition.", "",
              "| Measure | " + " | ".join(eds) + " |",
              "| --- | " + " | ".join("---" for _ in eds) + " |"]
    for row in report["usability"]:
        lines.append(f"| {row['family']} | " + " | ".join(
            "✓" if ed in row["editions"] else "" for ed in eds) + " |")

    lines += ["", "## Announced changes in rules and method", "",
              "| First edition | Change |", "| --- | --- |"]
    lines += [f"| {a['edition']} | {a['announcement']} |" for a in report["announcements"]]

    lines += ["", "## Table breaks between editions", "",
              "Detected by comparing each SA4-level table with the previous edition's.", "",
              "| Edition | Table | Change |", "| --- | --- | --- |"]
    for b in report["table_breaks"]:
        detail = b["change"]
        if b.get("dropped") or b.get("added"):
            parts = []
            if b.get("dropped"):
                parts.append(f"dropped {len(b['dropped'])}: " + "; ".join(b["dropped"][:6])
                             + (" …" if len(b["dropped"]) > 6 else ""))
            if b.get("added"):
                parts.append(f"added {len(b['added'])}: " + "; ".join(b["added"][:6])
                             + (" …" if len(b["added"]) > 6 else ""))
            detail += " — " + " / ".join(parts)
            if b.get("dropped_national_before") is not None:
                detail += f" (nationally {_n(b['dropped_national_before'])} the edition before)"
        lines.append(f"| {b['edition']} | {b['role']} | {detail} |")

    lines += ["", "## Regions", "",
              "| Edition | SA4 in stock tables | Added | Removed | Unplaced 'Other' rows |",
              "| --- | --- | --- | --- | --- |"]
    for r in report["regions"]:
        lines.append(f"| {r['edition']} | {r['sa4_in_stock_tables']} | "
                     f"{', '.join(r['added']) or '—'} | {', '.join(r['removed']) or '—'} | "
                     f"{', '.join(o.split(':')[1] for o in r['unplaced_other_rows']) or '—'} |")

    lines += ["", "## Checks per quarter", "",
              "Each cell is mismatches / comparisons. P.7: new-build places the derivation "
              "reproduces exactly, and its net bias. P.6: SA4 regions whose derived places are "
              "within 2% of dwellings × maximum residents.", "",
              "| Edition | As at | SA4→state | state→national | Identities | P.7 exact | P.7 bias "
              "| P.6 within 2% | P.7 zeros | Figure P.1 ends | Figure = tables | Non-numeric | Negative spare |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in report["editions"]:
        h = e["hierarchy"]
        ids_bad = sum(i["mismatched"] for i in e["identities"])
        ids_n = sum(i["compared"] for i in e["identities"])
        p7, p6 = e["calibration"].get("p7", {}), e["calibration"]["p6"]
        fig = e["figure_vs_tables"]
        lines.append(
            f"| {e['edition']} | {e['as_at']} | {h[0]['mismatched']}/{h[0]['compared']} | "
            f"{h[1]['mismatched']}/{h[1]['compared']} | {ids_bad}/{ids_n} | "
            f"{p7.get('exact_share', 0):.1%} of {p7.get('values_checked')} | "
            f"{p7.get('net_bias', 0):+.2%} | {p6['within_2_percent']}/{p6['regions_checked']} | "
            f"{len(e['p7_zero_with_dwellings'])} | "
            f"{(e['figure_p1_quarters'] or ['', '—'])[1]}"
            f"{' (lags)' if e['figure_p1_quarters'] and e['figure_p1_quarters'][1] != e['as_at'] else ''} | "
            f"{sum(f['agrees'] for f in fig)}/{len(fig)} | {e['flagged_cells_sa4_tables']} | "
            f"{len(e['sa4_with_negative_places_not_in_use'])} |")

    lines += ["", "### Notes by edition", ""]
    failing = [(e["edition"], i) for e in report["editions"] for i in e["identities"] + e["hierarchy"]
               if i["mismatched"]]
    if failing:
        for ed, i in failing:
            lines.append(f"- **{ed}**, {i['check']}: {i['mismatched']} of {i['compared']}")
            for x in i["examples"]:
                lines.append(f"  - {x['where']}: {_n(x['got'])} against {_n(x['want'])}")
    for e in report["editions"]:
        if e["p7_zero_with_dwellings"]:
            lines.append(f"- **{e['edition']}**, P.7 publishes zero new-build places against "
                         f"P.11 dwellings (derivation used instead): "
                         + ", ".join(x.replace("sa4:", "") for x in e["p7_zero_with_dwellings"]))
        if e["sa4_with_negative_places_not_in_use"]:
            lines.append(f"- **{e['edition']}**, more participants with SDA in use than enrolled "
                         f"places: " + ", ".join(x.replace("sa4:", "")
                                                 for x in e["sa4_with_negative_places_not_in_use"]))
        for f in e["figure_vs_tables"]:
            if not f["agrees"]:
                lines.append(f"- **{e['edition']}**, Figure P.1 {f['series']} reads "
                             f"{_n(f['figure'])}; the tables say {_n(f['table'])}")
        pc = e["figure_prose_vs_chart"]
        for m in pc["mislabelled"]:
            lines.append(f"- **{e['edition']}**, Figure P.1's prose labels a series "
                         f"'{m['prose_label']}' that is {m['is_actually']} in the chart "
                         f"({m['quarters']} quarters identical)")
        if pc["disagree_count"]:
            lines.append(f"- **{e['edition']}**, Figure P.1 prose and chart disagree on "
                         f"{pc['disagree_count']} points")
        if e["duplicate_rows_dropped"]:
            lines.append(f"- **{e['edition']}**, identical duplicate rows dropped: " + "; ".join(
                f"{s}: {', '.join(v)}" for s, v in e["duplicate_rows_dropped"].items()))

    rev = report["figure_p1_revisions"]
    lines += ["", "## Figure P.1 across editions", "",
              f"{rev['overlapping_points']} series-quarter points are stated by more than one "
              f"edition; {rev['agreeing']} agree everywhere and {len(rev['revised'])} do not.", ""]
    mislabelled = {(e["edition"], m["prose_label"]): m["is_actually"]
                   for e in report["editions"] for m in e["figure_prose_vs_chart"]["mislabelled"]}
    if rev["revised"]:
        lines += ["| Series | Quarter | Values by edition | Note |", "| --- | --- | --- | --- |"]
        for r in rev["revised"]:
            groups = {}
            for x in r["reports"]:
                groups.setdefault(x["value"], []).append(x["edition"])
            notes = [f"{ed} prose mislabels {mislabelled[(ed, r['series'])]}"
                     for ed in {x["edition"] for x in r["reports"]}
                     if (ed, r["series"]) in mislabelled]
            lines.append(f"| {r['series']} | {r['quarter']} | " + "; ".join(
                f"{_n(v)} ({eds_[0]}{'–' + eds_[-1] if len(eds_) > 1 else ''})"
                for v, eds_ in groups.items()) + f" | {'; '.join(notes) or 'restated'} |")

    lines += ["", "## National series from the tables", ""]
    keys = [k for k in report["national_series"][0] if ":" in k]
    lines += ["| Edition | " + " | ".join(k.replace(":Total", "").replace(":", " ") for k in keys) + " |",
              "| --- | " + " | ".join("---" for _ in keys) + " |"]
    for row in report["national_series"]:
        lines.append(f"| {row['edition']} | " + " | ".join(_n(row[k]) for k in keys) + " |")

    lines += ["", "## Table map", "",
              "Every table, by the sheet it sits on in each edition. The panel reads the SA4 "
              "ones; the scheme names a version of a table whose columns mean something "
              "different.", ""]
    roles = []
    for e in report["editions"]:
        for t in e["table_map"]:
            key = (t["role"], t["level"])
            if key not in roles:
                roles.append(key)
    lines += ["| Table | " + " | ".join(eds) + " |", "| --- | " + " | ".join("---" for _ in eds) + " |"]
    for role, level in roles:
        cells = []
        for e in report["editions"]:
            t = next((t for t in e["table_map"] if (t["role"], t["level"]) == (role, level)), None)
            cells.append(f"{t['sheet'].replace('Table ', '')}"
                         f"{' ' + t['scheme'] if t['scheme'] else ''}" if t else "")
        lines.append(f"| {role} ({level}) | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def print_summary(report):
    for e in report["editions"]:
        h = e["hierarchy"]
        ids_bad = sum(i["mismatched"] for i in e["identities"])
        p7, p6 = e["calibration"].get("p7", {}), e["calibration"]["p6"]
        print(f"  {e['edition']}: hierarchy {h[0]['mismatched']}+{h[1]['mismatched']} off, "
              f"identities {ids_bad} off, P.7 {p7.get('exact_share', 0):.1%} exact "
              f"(bias {p7.get('net_bias', 0):+.2%}), P.6 {p6['within_2_percent']}/"
              f"{p6['regions_checked']} within 2%")
    rev = report["figure_p1_revisions"]
    print(f"  Figure P.1: {rev['agreeing']}/{rev['overlapping_points']} overlapping points agree")
