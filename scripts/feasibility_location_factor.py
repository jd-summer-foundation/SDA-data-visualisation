#!/usr/bin/env python3
"""Phase 1 of the location-factor experiment: how much identifying variation is there?

The hypothesis: the SDA location factor is set per SA4 and building type, but
land and construction costs vary within an SA4, so the margin on a new SDA
dwelling is highest on the SA4's cheapest land, and new SDA should lean toward
cheap SA3s more than ordinary housing does. This script runs no test of that.
It reports whether the data could support one: how the factors vary, how far
cost varies within SA4s, how many SA4 borders separate different factors, and
how collinear cost is with the comparators and controls.

Reads only committed files:
  data/pricing/location_factors.csv, base_amounts.csv   (extract_pricing.py)
  data/abs/building_approvals_sa2.csv, census_2021_sa3.csv,
           sa3_adjacency.csv                              (reduce_abs.py,
                                                          build_sa3_adjacency.py)
  data/panel/panel_sa3.csv, sa3_sa4.csv                  (extract_panel_sa3.py)
  data/panel/newbuild_types_sa4.csv                      (extract_newbuild_types.py)
  data/asgs_2021_sa2.csv

Writes data/panel/location_factor_feasibility.json, LOCATION_FACTOR_FEASIBILITY.md
and location_factor_pairs.csv. Every figure in the Markdown is computed here.

Usage:  python3 scripts/feasibility_location_factor.py [-o data/panel]

Region-level throughout: nothing here follows an individual dwelling, and
every SDA flow is a net change in a region's published totals.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyse_panel import ols, spearman  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

START, END = "2023-06-30", "2026-06-30"
# Approvals over a window as long as the SDA one, a year earlier (approval
# precedes enrolment), and over the same window for comparison.
APPROVALS_LAGGED = ("2022-09-30", "2025-06-30")
APPROVALS_SAME = ("2023-09-30", "2026-06-30")
NEED_EARLIEST = "2023-12-31"        # participants_eligible_not_using begins
NEED_BY_CATEGORY = "2024-12-31"     # participants_with_need begins
MIN_BORDER_KM = 0.5
ACTIVITY_THRESHOLDS = [5, 10, 25, 50]
GAP_THRESHOLDS = [0.01, 0.03, 0.05, 0.10]
FORMS = [("Apartment", "Apartment"), ("Villa", "Villa/Duplex/Townhouse"), ("House", "House")]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load():
    d = {}
    d["factors"] = rows(DATA / "pricing" / "location_factors.csv")
    d["amounts"] = rows(DATA / "pricing" / "base_amounts.csv")
    d["sa3"] = {r["sa3"]: r for r in rows(DATA / "panel" / "sa3_sa4.csv")}
    d["census"] = {r["sa3_code_2021"]: r for r in rows(DATA / "abs" / "census_2021_sa3.csv")}
    d["adjacency"] = rows(DATA / "abs" / "sa3_adjacency.csv")
    d["approvals"] = rows(DATA / "abs" / "building_approvals_sa2.csv")
    d["asgs"] = rows(DATA / "asgs_2021_sa2.csv")
    panel = defaultdict(dict)
    for r in rows(DATA / "panel" / "panel_sa3.csv"):
        if r["value"] != "":
            panel[(r["geography"], r["category"], r["measure"])][r["as_at"]] = float(r["value"])
    d["panel"] = panel
    d["types"] = rows(DATA / "panel" / "newbuild_types_sa4.csv")
    return d


def change(panel, geo, category, measure, a=START, b=END):
    series = panel.get((geo, category, measure), {})
    if a not in series or b not in series:
        raise ValueError(f"{geo} {category} {measure}: missing {a} or {b}")
    return series[b] - series[a]


# --------------------------------------------------------------------------
# 1. Pricing
# --------------------------------------------------------------------------

def versions(d):
    """How the factors changed from each published version to the next.

    Before 2023-24 one table ('All') served every stock type; from 1 July 2023
    new builds have their own table and existing stock keeps the other. So the
    factor a new build faced is 'All' before and 'New build' after, and an
    existing dwelling's is 'All' before and 'Existing' after.
    """
    by = {}
    for r in d["factors"]:
        key = (r["edition"], r["version"])
        v = by.setdefault(key, {"valid_from": r["valid_from"], "released": r["released"], "f": {}})
        v["f"][(r["stock_type"], r["sa4"], r["building_type"])] = float(r["factor"])
    order = sorted(by, key=lambda k: (by[k]["valid_from"], by[k]["released"]))

    def facing(f, stock):
        own = "New build" if stock == "new" else "Existing"
        return {(s, t): v for (st, s, t), v in f.items()
                if st in (own, "All") and t != "Legacy"}
    steps = []
    for a, b in zip(order, order[1:]):
        row = {"from": list(a), "to": list(b), "valid_from": by[b]["valid_from"],
               "released": by[b]["released"]}
        for stock in ("new", "existing"):
            x, y = facing(by[a]["f"], stock), facing(by[b]["f"], stock)
            diffs = {k: y[k] - x[k] for k in x}
            moved = {k: v for k, v in diffs.items() if abs(v) > 0.001}
            row[stock] = {"cells": len(diffs), "changed": len(moved),
                          "sa4s": len({k[0] for k in moved}),
                          "max_abs": max((abs(v) for v in diffs.values()), default=0.0)}
        steps.append(row)
    # The July 2023 re-set, for the main types: last combined table against the
    # first new-build table still in force.
    last_all = max((k for k in order if any(s == "All" for s, _, _ in by[k]["f"])),
                   key=lambda k: by[k]["valid_from"])
    changes = [st for st in steps if st["new"]["changed"]]
    current = order[-1]
    reset = []
    for t in ("House, 2 residents", "Villa/Duplex/Townhouse, 1 resident",
              "Apartment, 2 bedrooms, 1 resident", "House, 3 residents"):
        old = {s: v for (st, s, tt), v in by[last_all]["f"].items() if st == "All" and tt == t}
        new = {s: v for (st, s, tt), v in by[current]["f"].items() if st == "New build" and tt == t}
        diff = {s: new[s] - old[s] for s in old}
        top = sorted(diff, key=lambda s: -diff[s])
        reset.append({"building_type": t, "rose": sum(v > 0.005 for v in diff.values()),
                      "fell": sum(v < -0.005 for v in diff.values()),
                      "median": statistics.median(diff.values()),
                      "spearman": spearman([old[s] for s in sorted(old)], [new[s] for s in sorted(old)]),
                      "up_most": [(s, diff[s]) for s in top[:3]],
                      "down_most": [(s, diff[s]) for s in top[-3:][::-1]]})
    return {"versions": [{"edition": k[0], "version": k[1], "valid_from": by[k]["valid_from"],
                          "released": by[k]["released"]} for k in order],
            "steps": steps, "last_combined": list(last_all), "current": list(current),
            "new_build_changes": [[st["to"][0], st["to"][1]] for st in changes],
            "reset": reset}


def pricing(d):
    editions = sorted({r["edition"] for r in d["factors"]})
    latest = editions[-1]
    f = defaultdict(dict)  # (stock, type) -> sa4 -> factor
    for r in d["factors"]:
        if r["edition"] == latest:
            f[(r["stock_type"], r["building_type"])][r["sa4"]] = float(r["factor"])
    by_type = []
    for (stock, btype), vals in f.items():
        counts = Counter(vals.values())
        top_value, top_n = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
        by_type.append({
            "stock": stock, "building_type": btype, "sa4s": len(vals),
            "distinct": len(counts), "singletons": sum(1 for n in counts.values() if n == 1),
            "modal_value": top_value, "modal_sa4s": top_n,
            "median_sa4s_per_value": statistics.median(counts.values()),
            "min": min(vals.values()), "median": statistics.median(vals.values()),
            "max": max(vals.values()),
            "below_1": sum(v < 1 for v in vals.values()),
            "above_1": sum(v > 1 for v in vals.values()),
        })
    # Within an SA4, across the eleven new-build types.
    sa4s = sorted(next(iter(f.values())))
    new_types = [t for (s, t) in f if s == "New build"]
    ranges = {s: max(f[("New build", t)][s] for t in new_types)
              - min(f[("New build", t)][s] for t in new_types) for s in sa4s}
    apt, house = "Apartment, 2 bedrooms, 1 resident", "House, 2 residents"
    ap = [f[("New build", apt)][s] for s in sa4s]
    ho = [f[("New build", house)][s] for s in sa4s]
    widest = sorted(sa4s, key=lambda s: -ranges[s])[:5]
    within = {
        "median_range": statistics.median(ranges.values()),
        "max_range": max(ranges.values()),
        "identical_across_types": sum(1 for v in ranges.values() if v < 0.005),
        "range_at_least_0_10": sum(1 for v in ranges.values() if v >= 0.095),
        "widest": [{"sa4": s, "range": ranges[s],
                    "apartment": f[("New build", apt)][s], "house": f[("New build", house)][s]}
                   for s in widest],
        "apartment_vs_house_spearman": spearman(ap, ho),
        "house_below_apartment": sum(h < a for a, h in zip(ap, ho)),
        "house_above_apartment": sum(h > a for a, h in zip(ap, ho)),
        "apartment_type": apt, "house_type": house,
    }
    # New build against existing, same edition and building type.
    new_vs_existing = []
    for t in new_types:
        diffs = [f[("Existing", t)][s] - f[("New build", t)][s] for s in sa4s]
        new_vs_existing.append({"building_type": t, "same": sum(abs(x) < 0.005 for x in diffs),
                                "median_diff": statistics.median(diffs)})
    legacy_equals = sum(abs(f[("Legacy", "Legacy")][s] - f[("Existing", "Group home, 5 residents")][s])
                        < 0.005 for s in sa4s)
    # Base amounts: what one factor point is worth.
    amt = {(r["stock_type"], r["building_type"], r["design_category"], r["breakout_room"],
            r["fire_sprinklers"], r["ooa"], r["gst"]): int(r["amount"])
           for r in d["amounts"] if r["edition"] == latest}
    gst = "Not paid, or paid and credits claimed"
    examples = []
    for cat in ("High Physical Support", "Robust"):
        for t in (house, "Villa/Duplex/Townhouse, 1 resident"):
            base = amt[("New build (post-2023)", t, cat, "No", "No", "No", gst)]
            fv = f[("New build", t)]
            residents = int(t.split(", ")[-1].split()[0])
            examples.append({
                "category": cat, "building_type": t, "base_per_participant": base,
                "residents": residents, "dwelling_base": base * residents,
                "min_factor": min(fv.values()), "max_factor": max(fv.values()),
                "median_factor": statistics.median(fv.values()),
                "per_0_05_factor": round(base * residents * 0.05),
            })
    return {"editions": editions, "latest": latest, "history": versions(d),
            "by_type": by_type, "within_sa4": within,
            "new_vs_existing": new_vs_existing, "legacy_equals_group_home_5": legacy_equals,
            "sa4s": len(sa4s), "base_amounts": len(amt), "examples": examples}


# --------------------------------------------------------------------------
# 2-3. Approvals and cost, by SA3
# --------------------------------------------------------------------------

def approvals(d):
    """SA3 totals per quarter, after re-checking the committed file's sums."""
    sa2_sa3 = {r["SA2_CODE_2021"]: r["SA3_CODE_2021"] for r in d["asgs"]}
    per = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # region -> quarter -> [h, o]
    for r in d["approvals"]:
        per[r["region"]][r["quarter"]] = [float(r["houses"]), float(r["other_residential"])]
    quarters = sorted(per["0"])
    mismatches = checks = 0
    for q in quarters:
        states = defaultdict(lambda: [0.0, 0.0])
        for code, series in per.items():
            if len(code) == 9 and q in series:
                for i in (0, 1):
                    states[code[0]][i] += series[q][i]
        for i in (0, 1):
            total = 0.0
            for s in "12345678":
                checks += 1
                pub = per[s][q][i]
                total += pub
                mismatches += abs(states[s][i] - pub) > 1e-9
            checks += 1
            mismatches += abs(total - per["0"][q][i]) > 1e-9
    if mismatches:
        raise ValueError(f"building approvals: {mismatches} of {checks} sums fail")
    panel_codes = {r["sa3_code"] for r in d["sa3"].values()}
    sa3 = defaultdict(lambda: defaultdict(float))
    outside = 0.0
    for code, series in per.items():
        if len(code) != 9:
            continue
        s3 = sa2_sa3[code]
        for q, (h, o) in series.items():
            if s3 in panel_codes:
                sa3[s3][q] += h + o
            elif APPROVALS_LAGGED[0] <= q <= APPROVALS_LAGGED[1]:
                outside += h + o
    national = {q: sum(per["0"][q]) for q in quarters}
    return sa3, quarters, checks, national, outside


def window(series, bounds):
    return sum(v for q, v in series.items() if bounds[0] <= q <= bounds[1])


def sa3_frame(d, appr):
    """One record per Supplement P SA3 with everything the tests would use."""
    area = defaultdict(float)
    for r in d["asgs"]:
        area[r["SA3_CODE_2021"]] += float(r["AREA_ALBERS_SQKM"] or 0)
    frame = {}
    for geo, r in d["sa3"].items():
        code = r["sa3_code"]
        c = d["census"][code]
        mort, rent = float(c["median_mortgage_monthly"]), float(c["median_rent_weekly"])
        p = d["panel"]
        frame[geo] = {
            "sa4": r["sa4"], "state": r["state"], "code": code,
            "mortgage": mort if mort > 0 else None, "rent": rent if rent > 0 else None,
            "persons": float(c["persons"]), "area": area[code],
            "new_build": change(p, geo, "Total", "dwellings_new_build"),
            "hps": change(p, geo, "High Physical Support", "enrolled_dwellings"),
            "robust": change(p, geo, "Robust", "enrolled_dwellings"),
            "legacy": p[(geo, "Total", "dwellings_legacy")][END],
            "existing": p[(geo, "Total", "dwellings_existing")][END],
            "eligible_not_using": p[(geo, "Total", "participants_eligible_not_using")][NEED_EARLIEST],
            "with_need": p[(geo, "Total", "participants_with_need")][NEED_BY_CATEGORY],
            "approvals_lagged": window(appr[code], APPROVALS_LAGGED),
            "approvals_same": window(appr[code], APPROVALS_SAME),
        }
    return frame


# --------------------------------------------------------------------------
# 5. Identifying variation
# --------------------------------------------------------------------------

def by_sa4(frame, keep=lambda g, r: True):
    out = defaultdict(list)
    for g, r in frame.items():
        if keep(g, r):
            out[r["sa4"]].append(g)
    return out


def qualifying(frame):
    groups = by_sa4(frame, lambda g, r: r["mortgage"] is not None)
    table = []
    for t in ACTIVITY_THRESHOLDS:
        q = [s for s, gs in groups.items()
             if len(gs) >= 2 and sum(frame[g]["new_build"] for g in gs) >= t]
        q2 = [s for s in q if sum(frame[g]["new_build"] > 0 for g in groups[s]) >= 2]
        table.append({"threshold": t, "sa4s": len(q), "sa4s_two_building": len(q2),
                      "sa3s": sum(len(groups[s]) for s in q),
                      "share_of_new_build": sum(frame[g]["new_build"] for s in q for g in groups[s])
                      / sum(r["new_build"] for r in frame.values())})
    return groups, table


def dispersion(frame, groups, key):
    logs = {g: math.log(frame[g][key]) for gs in groups.values() for g in gs
            if frame[g][key] is not None}
    dev, ranges, sds = {}, {}, []
    for s, gs in groups.items():
        gs = [g for g in gs if g in logs]
        mu = statistics.fmean(logs[g] for g in gs)
        for g in gs:
            dev[g] = logs[g] - mu
        if len(gs) >= 2:
            ranges[s] = max(logs[g] for g in gs) - min(logs[g] for g in gs)
            sds.append(statistics.pstdev([logs[g] for g in gs]))
    total = statistics.pvariance(list(logs.values()))
    within = statistics.fmean(v * v for v in dev.values())
    widest = sorted(ranges, key=lambda s: -ranges[s])[:3]
    return dev, {
        "sa3s": len(logs), "sd_total": total ** 0.5, "sd_within": within ** 0.5,
        "share_within": within / total, "median_range": statistics.median(ranges.values()),
        "p90_range": sorted(ranges.values())[int(0.9 * len(ranges))],
        "max_range": max(ranges.values()), "median_sd": statistics.median(sds),
        "widest": [{"sa4": s, "range": ranges[s]} for s in widest],
    }


def collinearity(frame, groups, dev):
    """Within-SA4 rank correlations of relative cost with the comparators."""
    cols = defaultdict(list)
    x, y, clusters = [], [], []
    for s, gs in groups.items():
        gs = [g for g in gs if g in dev]
        if len(gs) < 2:
            continue
        tot = {k: sum(frame[g][k] for g in gs) for k in
               ("approvals_lagged", "new_build", "eligible_not_using", "with_need", "persons",
                "area")}
        n = len(gs)
        for g in gs:
            r = frame[g]
            share = {k: (r[k] / tot[k] if tot[k] > 0 else 1 / n) for k in tot}
            cols["cost"].append(dev[g])
            cols["approvals_share"].append(share["approvals_lagged"])
            cols["new_sda_share"].append(share["new_build"])
            cols["eligible_share"].append(share["eligible_not_using"])
            cols["need_share"].append(share["with_need"])
            cols["population_share"].append(share["persons"])
            cols["area_share"].append(share["area"])
            cols["approvals_per_1000"].append(1000 * r["approvals_lagged"] / r["persons"])
            # Relative cost on the controls, shares demeaned within the SA4.
            x.append([share[k] - 1 / n for k in ("approvals_lagged", "eligible_not_using",
                                                 "persons", "area")])
            y.append(dev[g])
            clusters.append(s)
    names = ["approvals_share", "new_sda_share", "eligible_share", "need_share",
             "population_share", "area_share", "approvals_per_1000"]
    matrix = {a: {b: spearman(cols[a], cols[b]) for b in ["cost"] + names} for a in names}
    beta, _ = ols(x, y, clusters)
    fitted = [sum(b * v for b, v in zip(beta, row)) for row in x]
    ssr = sum((a - b) ** 2 for a, b in zip(y, fitted))
    sst = sum(v * v for v in y)
    return {"sa3s": len(y), "sa4s": len(set(clusters)), "spearman": matrix,
            "r2_cost_on_controls": 1 - ssr / sst,
            "residual_sd": (ssr / len(y)) ** 0.5, "cost_sd": (sst / len(y)) ** 0.5}


def main_types(d):
    """New-build growth by building type over the window, and by category."""
    growth = defaultdict(float)
    for r in d["types"]:
        sign = 1 if r["as_at"] == END else -1 if r["as_at"] == START else 0
        if sign and r["dwellings"] != "":
            growth[(r["building_type"], r["design_category"])] += sign * float(r["dwellings"])
    total = defaultdict(float)
    for (t, _), v in growth.items():
        total[t] += v
    all_new = sum(total.values())
    ranked = sorted(total.items(), key=lambda kv: -kv[1])
    by_cat = {}
    for cat in ("High Physical Support", "Robust"):
        items = sorted(((t, v) for (t, c), v in growth.items() if c == cat), key=lambda kv: -kv[1])
        s = sum(v for _, v in items)
        by_cat[cat] = {"total": s, "top": [{"building_type": t, "dwellings": v, "share": v / s}
                                           for t, v in items[:3]]}
    main = {}
    for short, prefix in FORMS:
        t = max((t for t in total if t.startswith(prefix)), key=lambda t: total[t])
        main[short] = t
    return {"ranked": [{"building_type": t, "dwellings": v, "share": v / all_new} for t, v in ranked],
            "total": all_new, "by_category": by_cat, "main": main}


def border_pairs(d, frame, types, out_dir):
    latest = max(r["edition"] for r in d["factors"])
    f = defaultdict(dict)
    for r in d["factors"]:
        if r["edition"] == latest and r["stock_type"] == "New build":
            f[r["sa4"]][r["building_type"]] = float(r["factor"])
    # A single summary factor per SA4: the national new-build mix.
    weights = {r["building_type"]: max(r["dwellings"], 0) for r in types["ranked"]}
    wsum = sum(weights.values())
    mix = {s: sum(f[s][t] * w for t, w in weights.items()) / wsum for s in f}
    all_pairs = d["adjacency"]
    cross = [p for p in all_pairs if p["cross_sa4"] == "yes"]
    used = [p for p in cross if float(p["shared_km"]) >= MIN_BORDER_KM]
    main = types["main"]
    table, recs = [], []
    for p in used:
        a, b = p["sa4_a"], p["sa4_b"]
        rec = {"pair": p, "gaps": {k: abs(f[a][t] - f[b][t]) for k, t in main.items()},
               "mix_gap": abs(mix[a] - mix[b])}
        ra, rb = frame[p["sa3_a"]], frame[p["sa3_b"]]
        rec["sda_either"] = ra["new_build"] > 0 or rb["new_build"] > 0
        rec["sda_both"] = ra["new_build"] > 0 and rb["new_build"] > 0
        if ra["mortgage"] and rb["mortgage"]:
            rec["dlog_cost"] = math.log(ra["mortgage"] / rb["mortgage"])
            rec["dlog_mix"] = math.log(mix[a] / mix[b])
        recs.append(rec)
    for k in list(main) + ["mix"]:
        gaps = [r["mix_gap"] if k == "mix" else r["gaps"][k] for r in recs]
        row = {"type": main.get(k, "National new-build mix"), "key": k,
               "median": statistics.median(gaps), "max": max(gaps)}
        for th in GAP_THRESHOLDS:
            row[f"ge_{th:.2f}"] = sum(g >= th - 1e-9 for g in gaps)
            row[f"ge_{th:.2f}_both_sda"] = sum(g >= th - 1e-9 and r["sda_both"]
                                               for g, r in zip(gaps, recs))
        table.append(row)
    with_cost = [r for r in recs if "dlog_cost" in r]
    sa4_pairs = {tuple(sorted((r["pair"]["sa4_a"], r["pair"]["sa4_b"]))) for r in recs}
    sa3_in = Counter(g for r in recs for g in (r["pair"]["sa3_a"], r["pair"]["sa3_b"]))
    # The committed pair list, with the factor on each side.
    with open(out_dir / "location_factor_pairs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        head = ["sa3_a", "sa4_a", "sa3_b", "sa4_b", "shared_km", "edition"]
        for k in main:
            head += [f"{k.lower()}_factor_a", f"{k.lower()}_factor_b"]
        head += ["mix_factor_a", "mix_factor_b", "differs"]
        w.writerow(head)
        for p in cross:
            a, b = p["sa4_a"], p["sa4_b"]
            row = [p["sa3_a"], a, p["sa3_b"], b, p["shared_km"], latest]
            for k, t in main.items():
                row += [f"{f[a][t]:.2f}", f"{f[b][t]:.2f}"]
            row += [f"{mix[a]:.3f}", f"{mix[b]:.3f}",
                    "yes" if any(f[a][t] != f[b][t] for t in main.values()) else "no"]
            w.writerow(row)
    return {
        "edition": latest, "pairs_all": len(all_pairs), "pairs_within": len(all_pairs) - len(cross),
        "pairs_cross": len(cross), "pairs_used": len(used), "sa4_pairs": len(sa4_pairs),
        "sa3s_in_pairs": len(sa3_in), "max_pairs_per_sa3": max(sa3_in.values()),
        "short_dropped": len(cross) - len(used), "gaps": table,
        "sda_either": sum(r["sda_either"] for r in recs),
        "sda_both": sum(r["sda_both"] for r in recs),
        "gap_vs_cost_spearman": spearman([r["dlog_mix"] for r in with_cost],
                                         [r["dlog_cost"] for r in with_cost]),
        "median_abs_cost_gap": statistics.median(abs(r["dlog_cost"]) for r in with_cost),
        "pairs_with_cost": len(with_cost),
        "mix_weights": {t: w / wsum for t, w in weights.items()},
    }


def outcome_notes(frame):
    nb = [r["new_build"] for r in frame.values()]
    return {"new_build_total": sum(nb), "hps_total": sum(r["hps"] for r in frame.values()),
            "robust_total": sum(r["robust"] for r in frame.values()),
            "negative": sum(v < 0 for v in nb), "zero": sum(v == 0 for v in nb),
            "positive": sum(v > 0 for v in nb),
            "missing_cost": sorted(g for g, r in frame.items() if r["mortgage"] is None),
            "legacy_total": sum(r["legacy"] for r in frame.values()),
            "legacy_sa3s": sum(r["legacy"] > 0 for r in frame.values()),
            "existing_total": sum(r["existing"] for r in frame.values()),
            "existing_sa3s": sum(r["existing"] > 0 for r in frame.values()),
            "missing_cost_persons": sum(r["persons"] for r in frame.values()
                                        if r["mortgage"] is None)}


def analyse(d, out_dir):
    appr, quarters, checks, national, outside = approvals(d)
    frame = sa3_frame(d, appr)
    groups, qual = qualifying(frame)
    dev_m, disp_m = dispersion(frame, groups, "mortgage")
    _, disp_r = dispersion(frame, groups, "rent")
    rent_groups = by_sa4(frame, lambda g, r: r["mortgage"] is not None and r["rent"] is not None)
    both = [g for gs in rent_groups.values() for g in gs]
    rel_rent = {}
    for s, gs in rent_groups.items():
        mu = statistics.fmean(math.log(frame[g]["rent"]) for g in gs)
        for g in gs:
            rel_rent[g] = math.log(frame[g]["rent"]) - mu
    types = main_types(d)
    return {
        "pricing": pricing(d),
        "approvals": {"first": quarters[0], "last": quarters[-1], "quarters": len(quarters),
                      "checks": checks, "lagged": APPROVALS_LAGGED, "same": APPROVALS_SAME,
                      "national_lagged": window(national, APPROVALS_LAGGED),
                      "national_same": window(national, APPROVALS_SAME),
                      "sa3_lagged": sum(r["approvals_lagged"] for r in frame.values()),
                      "outside_panel_lagged": outside,
                      "sa3_zero_lagged": sum(r["approvals_lagged"] == 0 for r in frame.values())},
        "cost": {"sa3s": len(frame), "mortgage": disp_m, "rent": disp_r,
                 "mortgage_rent_spearman": spearman([dev_m[g] for g in both],
                                                    [rel_rent[g] for g in both]),
                 "median_mortgage": statistics.median(r["mortgage"] for r in frame.values()
                                                      if r["mortgage"]),
                 "median_rent": statistics.median(r["rent"] for r in frame.values() if r["rent"])},
        "outcome": outcome_notes(frame),
        "qualifying": qual,
        "collinearity": collinearity(frame, groups, dev_m),
        "types": types,
        "borders": border_pairs(d, frame, types, out_dir),
    }


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def f2(v):
    return f"{v:.2f}"


def n0(v):
    return f"{v:,.0f}"


def pc(v):
    return f"{v:.0%}"


def nm(geo):
    return geo.split(":", 1)[1]


def month(q):
    y, m, _ = q.split("-")
    return f"{['Mar', 'Jun', 'Sep', 'Dec'][int(m) // 3 - 1]} {y}"


def quarter_start(q):
    y, m, _ = q.split("-")
    m = int(m) - 2
    return f"{['Jan', 'Apr', 'Jul', 'Oct'][(m - 1) // 3]} {y}"


def to_markdown(a):
    pr, ap, co, oc = a["pricing"], a["approvals"], a["cost"], a["outcome"]
    ql, cl, ty, bd = a["qualifying"], a["collinearity"], a["types"], a["borders"]
    q10 = next(r for r in ql if r["threshold"] == 10)
    main = ty["main"]
    gap = {r["key"]: r for r in bd["gaps"]}
    house = gap["House"]
    sp = cl["spearman"]
    ws = pr["within_sa4"]
    m = co["mortgage"]
    L = []
    w = L.append
    w("# Location-factor experiment, Phase 1: ingest and feasibility")
    w("")
    w("Generated by `scripts/feasibility_location_factor.py` from committed files. Every figure "
      "is computed; do not edit by hand. Region-level throughout: nothing here follows an "
      "individual dwelling, and every SDA flow is a net change in a region's published totals. "
      "No test of the hypothesis is run here; this reports whether the data could support one.")
    w("")
    w("## In brief")
    w("")
    hi = pr["history"]
    ch = hi["new_build_changes"]
    w(f"1. **The factors were re-set once in the window that matters.** Of the "
      f"{len(hi['versions'])} versions from {hi['versions'][0]['edition']} to "
      f"{hi['versions'][-1]['edition']}, new-build factors changed in {len(ch)}: "
      + " and ".join(f"{e} v{v}" for e, v in ch)
      + ". Until 30 June 2023 one table served all stock; from 1 July 2023 new builds have their "
      f"own, unchanged since. The {pr['latest']} factors used below are the ones in force since then.")
    w(f"2. **The factors vary a lot, and by building type.** Across the {pr['sa4s']} SA4s the "
      f"new-build factor for {ws['house_type']} runs "
      f"{f2(next(r for r in pr['by_type'] if r['stock'] == 'New build' and r['building_type'] == ws['house_type'])['min'])}"
      f"–{f2(next(r for r in pr['by_type'] if r['stock'] == 'New build' and r['building_type'] == ws['house_type'])['max'])}. "
      f"Within an SA4 the eleven building types differ by a median {f2(ws['median_range'])}, and houses "
      f"sit below apartments in {ws['house_below_apartment']} of {pr['sa4s']} SA4s.")
    w(f"3. **Cost varies within SA4s, but modestly.** The within-SA4 standard deviation of log median "
      f"mortgage is {f2(m['sd_within'])} ({pc(m['share_within'])} of all SA3 variance); the median SA4's "
      f"cheapest and dearest SA3s differ by {f2(m['median_range'])} log points (about "
      f"{pc(math.exp(m['median_range']) - 1)}).")
    w(f"4. **Enough SA4s to test within.** {q10['sa4s']} SA4s have at least two SA3s with cost data and "
      f"at least 10 new-build dwellings added; they hold {pc(q10['share_of_new_build'])} of new-build growth.")
    w(f"5. **Cost is not collinear with the comparators.** Within SA4s, relative cost has a rank "
      f"correlation of {f2(sp['approvals_share']['cost'])} with the SA3's share of approvals and "
      f"{f2(sp['eligible_share']['cost'])} with its share of waiting participants; the controls "
      f"explain {pc(cl['r2_cost_on_controls'])} of relative cost. Approvals and need are collinear "
      f"with each other ({f2(sp['approvals_share']['eligible_share'])}), which matters for the "
      "regression, not the rank test.")
    w(f"6. **Many borders separate different factors.** Of {bd['pairs_used']} adjacent SA3 pairs in "
      f"different SA4s (sharing at least {MIN_BORDER_KM} km of border), {house['ge_0.05']} straddle a new-build {main['House']} factor gap of 0.05 or "
      f"more, {house['ge_0.05_both_sda']} of them with new SDA on both sides. But the pairs share "
      f"SA3s and SA4 borders ({bd['sa4_pairs']} distinct SA4 pairs), and adjacent SA3s across a "
      f"border still differ in cost by a median {f2(bd['median_abs_cost_gap'])} log points.")
    w("")

    # ---- 1. Pricing
    w("## 1. Pricing")
    w("")
    w(f"**Sources.** `data/pricing/` holds the {pr['latest']} Pricing Arrangements for SDA (v1.0) "
      "and Pricing Schedule for SDA. `scripts/extract_pricing.py` reads both and requires them to "
      f"agree on every location factor and every base amount; they do. It writes "
      f"{len(pr['by_type']) * pr['sa4s']:,} location factors and {pr['base_amounts']:,} base amounts. "
      "Three things differ from what was expected:")
    w("")
    w("- **Table numbers.** The location factors are Tables 23 and 24 (Appendices E and F) in the "
      "Arrangements, and Tables 35 and 36 in the Schedule. Tables are found by caption, not number.")
    w("- **Two retired SA4 names.** The existing-and-legacy table (not the new-build table) labels "
      "two regions by names the ABS retired in 2016: `QLD - Fitzroy` (now Central Queensland) and "
      "`QLD - Mackay` (now Mackay - Isaac - Whitsunday). These are mapped explicitly; any other "
      "unmatched name fails the build. All 88 SA4s are present in both tables.")
    w("- **A misleading heading.** The existing-stock tables *with* OOA head a column 'Robust No "
      "OOA'. The amounts are higher than the no-OOA table's, so the caption governs.")
    w("")
    w("Base amounts are in Appendices A–D (post-2023 new build, pre-2023 new build, existing, "
      "legacy), by building type × design category, with variants for sprinklers, OOA, breakout "
      "room and (post-2023 new builds only) GST treatment. The shared-living amounts of Appendix H "
      "and the refurbishment costs of Appendix G are not base amounts and are not extracted.")
    w("")
    w("### How the factors are distributed")
    w("")
    w(f"Per building type, across the {pr['sa4s']} SA4s. The reference, *Median capital city*, is "
      "1.00 throughout and is not an SA4.")
    w("")
    w("| Stock | Building type | Distinct values | Values held by one SA4 | Most common value (SA4s) | Median SA4s per value | Min | Median | Max | Below 1 | Above 1 |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in pr["by_type"]:
        w(f"| {r['stock']} | {r['building_type']} | {r['distinct']} | {r['singletons']} | "
          f"{f2(r['modal_value'])} ({r['modal_sa4s']}) | {r['median_sa4s_per_value']:g} | "
          f"{f2(r['min'])} | {r['median']:.3f} | {f2(r['max'])} | {r['below_1']} | {r['above_1']} |")
    w("")
    per_value = [r["median_sa4s_per_value"] for r in pr["by_type"]]
    w("Factors are published to two decimals, so SA4s share values by rounding more than by "
      "design: no value is held by more than "
      f"{max(r['modal_sa4s'] for r in pr['by_type'])} SA4s, and the median value by "
      f"{min(per_value):g} to {max(per_value):g}, depending on the building type.")
    w("")
    w("### Across building types within an SA4")
    w("")
    w(f"The spread of the eleven new-build factors within one SA4 has a median of {f2(ws['median_range'])} "
      f"and a maximum of {f2(ws['max_range'])}; {ws['range_at_least_0_10']} SA4s spread by 0.10 or more "
      f"and {ws['identical_across_types']} by less than 0.01. The pattern is systematic: across SA4s "
      f"the {ws['apartment_type']} and {ws['house_type']} factors have a rank correlation of "
      f"{f2(ws['apartment_vs_house_spearman'])}, and the house factor is below the apartment factor in "
      f"{ws['house_below_apartment']} SA4s and above it in {ws['house_above_apartment']}. Apartments "
      "are priced flat across the country; houses carry the land, so their factors are low in "
      "regional SA4s and high in inner cities. The widest:")
    w("")
    w("| SA4 | Spread across types | Apartment 2 bed 1 resident | House 2 residents |")
    w("| --- | --- | --- | --- |")
    for r in ws["widest"]:
        w(f"| {nm(r['sa4'])} | {f2(r['range'])} | {f2(r['apartment'])} | {f2(r['house'])} |")
    w("")
    w("So a single factor per SA4 is a simplification; it has to be weighted by the building types "
      "actually built (Section 4).")
    w("")
    w("**New build against existing.** The existing-stock factors are a different schedule, not a "
      "copy:")
    w("")
    w("| Building type | SA4s with the same factor | Median existing − new |")
    w("| --- | --- | --- |")
    for r in pr["new_vs_existing"]:
        w(f"| {r['building_type']} | {r['same']} | {r['median_diff']:+.2f} |")
    w("")
    w(f"The Legacy factor equals the existing Group home, 5 residents factor in "
      f"{pr['legacy_equals_group_home_5']} of {pr['sa4s']} SA4s.")
    w("")
    w("### What a factor point is worth")
    w("")
    w(f"Post-2023 new build, no sprinklers, no OOA, GST not paid or credits claimed ({pr['latest']}):")
    w("")
    w("| Category | Building type | Base per participant | Per dwelling | Factor range | Per dwelling per 0.05 of factor |")
    w("| --- | --- | --- | --- | --- | --- |")
    for r in pr["examples"]:
        w(f"| {r['category']} | {r['building_type']} | ${n0(r['base_per_participant'])} | "
          f"${n0(r['dwelling_base'])} | {f2(r['min_factor'])}–{f2(r['max_factor'])} | "
          f"${n0(r['per_0_05_factor'])} a year |")
    w("")
    w("### Changes between editions")
    w("")
    w(f"`data/pricing/` holds every version from {hi['versions'][0]['edition']} v"
      f"{hi['versions'][0]['version']} to {hi['versions'][-1]['edition']} v"
      f"{hi['versions'][-1]['version']} ({len(hi['versions'])} in all). Before 2023-24 one "
      "table served every stock type; since 1 July 2023 the new-build table applies to every new "
      "build, whenever first enrolled, and existing and legacy stock keep the other. Each version "
      "against the one before, for the factor a new build and an existing dwelling faced:")
    w("")
    w("| From | To | Valid from | Released | New-build cells changed | SA4s | Largest change | Existing cells changed | SA4s | Largest change |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for st in hi["steps"]:
        nb_, ex_ = st["new"], st["existing"]
        w(f"| {st['from'][0]} v{st['from'][1]} | {st['to'][0]} v{st['to'][1]} | {st['valid_from']} | "
          f"{st['released']} | {nb_['changed']} of {nb_['cells']} | {nb_['sa4s']} | {nb_['max_abs']:.2f} | "
          f"{ex_['changed']} of {ex_['cells']} | {ex_['sa4s']} | {ex_['max_abs']:.2f} |")
    w("")
    w(f"**The July 2023 re-set.** New-build factors in {hi['current'][0]} v{hi['current'][1]} against "
      f"the last combined table ({hi['last_combined'][0]} v{hi['last_combined'][1]}):")
    w("")
    w("| Building type | SA4s rising | SA4s falling | Median change | Rank correlation old–new | Rose most | Fell most |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for r in hi["reset"]:
        w(f"| {r['building_type']} | {r['rose']} | {r['fell']} | {r['median']:+.2f} | "
          f"{f2(r['spearman'])} | " + ", ".join(f"{nm(s_)} ({v:+.2f})" for s_, v in r["up_most"])
          + " | " + ", ".join(f"{nm(s_)} ({v:+.2f})" for s_, v in r["down_most"]) + " |")
    w("")
    w("So the factors that could have steered the building enrolled over the window are two sets: "
      "the combined table for sites committed before mid-2023, and the new-build table after. The "
      "border test uses each, and the change between them.")
    w("")

    # ---- 2. Approvals
    w("## 2. Building approvals")
    w("")
    w(f"`data/abs/building_approvals_sa2.csv`: dwelling units approved in new residential buildings, "
      f"all sectors, houses and other residential, by ASGS 2021 SA2 and quarter, "
      f"{quarter_start(ap['first'])} to {month(ap['last'])} ({ap['quarters']} quarters). "
      "`scripts/reduce_abs.py` checks every month before writing: SA2s sum to their state's published "
      "total and states to the national total, for houses and for other residential. This script "
      f"re-checks the committed quarterly file the same way: {ap['checks']:,} sums, none off.")
    w("")
    w(f"Aggregated to SA3 through `data/asgs_2021_sa2.csv`. Over the lagged comparison window, "
      f"{quarter_start(ap['lagged'][0])} to {month(ap['lagged'][1])}, "
      f"{n0(ap['national_lagged'])} dwellings were approved nationally; the 336 Supplement P SA3s "
      f"hold {n0(ap['sa3_lagged'])}, and {n0(ap['outside_panel_lagged'])} fall in SA2s outside "
      f"them (Other Territories). {ap['sa3_zero_lagged']} SA3s approved none. Over the same window as "
      f"the SDA change ({quarter_start(ap['same'][0])} to {month(ap['same'][1])}) the national total "
      f"is {n0(ap['national_same'])}.")
    w("")

    # ---- 3. Cost
    w("## 3. Cost measures")
    w("")
    w("`data/abs/census_2021_sa3.csv`: 2021 Census G02 median mortgage repayment (monthly), median "
      "rent (weekly) and median household income (weekly), and G01 persons, joined to the 336 SA3s "
      f"on ASGS 2021 code. Medians across SA3s: mortgage ${n0(co['median_mortgage'])} a month, rent "
      f"${n0(co['median_rent'])} a week. "
      + ("One SA3 has no published median mortgage and is left out of cost measures: "
         + ", ".join(nm(g) for g in oc["missing_cost"])
         + f" ({n0(oc['missing_cost_persons'])} residents, mostly national park)."
         if oc["missing_cost"] else ""))
    w("")

    # ---- 4. Adjacency
    w("## 4. Adjacency and the factor on each side")
    w("")
    w(f"`data/abs/sa3_adjacency.csv`, derived from the ABS SA3 boundaries by "
      "`scripts/build_sa3_adjacency.py`: two SA3s are adjacent when they share at least one boundary "
      f"edge, not merely a corner. {bd['pairs_all']} pairs; {bd['pairs_within']} within an SA4 and "
      f"{bd['pairs_cross']} across SA4s. {bd['short_dropped']} cross-SA4 pairs sharing less than "
      f"{MIN_BORDER_KM} km of border are set aside, leaving {bd['pairs_used']} pairs across "
      f"{bd['sa4_pairs']} distinct SA4 borders, involving {bd['sa3s_in_pairs']} SA3s (one SA3 is in "
      f"up to {bd['max_pairs_per_sa3']} pairs).")
    w("")
    w(f"**Main new-build types.** New-build dwellings grew by {n0(ty['total'])} from {month(START)} to "
      f"{month(END)} (Supplement P Table P.11, SA4 level, `data/panel/newbuild_types_sa4.csv`; P.11 "
      "includes New Build (Refurbished), which the SA3 `dwellings_new_build` total does not):")
    w("")
    w("| Building type | Added | Share |")
    w("| --- | --- | --- |")
    for r in ty["ranked"]:
        w(f"| {r['building_type']} | {n0(r['dwellings'])} | {pc(r['share'])} |")
    w("")
    for cat, v in ty["by_category"].items():
        w(f"- **{cat}** ({n0(v['total'])} added): "
          + "; ".join(f"{t['building_type']} {pc(t['share'])}" for t in v["top"]) + ".")
    w("")
    w("The most-built type of each form stands for it below: "
      + ", ".join(f"{k.lower()}s by *{t}*" for k, t in main.items())
      + ". A national-mix factor weights each SA4's eleven factors by these shares; Phase 2 would "
      "weight by each SA4's own mix.")
    w("")
    w(f"`data/panel/location_factor_pairs.csv` lists every cross-SA4 pair with the {bd['edition']} "
      "factor on each side. Absolute factor gaps across the "
      f"{bd['pairs_used']} pairs:")
    w("")
    head = "| Factor | Median gap | Max gap | " + " | ".join(f"≥ {t:.2f}" for t in GAP_THRESHOLDS)
    w(head + " | ≥ 0.05, new SDA both sides |")
    w("| --- | --- | --- | " + " | ".join("---" for _ in GAP_THRESHOLDS) + " | --- |")
    for r in bd["gaps"]:
        w(f"| {r['type']} | {f2(r['median'])} | {f2(r['max'])} | "
          + " | ".join(str(r[f"ge_{t:.2f}"]) for t in GAP_THRESHOLDS)
          + f" | {r['ge_0.05_both_sda']} |")
    w("")

    # ---- 5. Identifying variation
    w("## 5. How much identifying variation is there?")
    w("")
    w("### SA4s to test within")
    w("")
    w(f"Outcome: the change in `dwellings_new_build` per SA3, {month(START)} to {month(END)}: "
      f"{n0(oc['new_build_total'])} in all, rising in {oc['positive']} SA3s, flat in {oc['zero']} and "
      f"falling in {oc['negative']}. Enrolled High Physical Support dwellings rose by "
      f"{n0(oc['hps_total'])} and Robust by {n0(oc['robust_total'])}; those include existing "
      "dwellings newly enrolled, and SA3 has no category split of new build and no building type.")
    w("")
    w("| New-build dwellings added in the SA4 at least | SA4s with ≥ 2 SA3s | …of which ≥ 2 SA3s building | SA3s in them | Share of all new build |")
    w("| --- | --- | --- | --- | --- |")
    for r in ql:
        w(f"| {r['threshold']} | {r['sa4s']} | {r['sa4s_two_building']} | {r['sa3s']} | "
          f"{pc(r['share_of_new_build'])} |")
    w("")
    w("### Cost dispersion within SA4s")
    w("")
    w("| Measure | SA3s | SD of log, all SA3s | SD of log within SA4 | Share of variance within SA4 | Median SA4 range | 90th percentile range | Widest SA4s |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, dd in (("Median mortgage", co["mortgage"]), ("Median rent", co["rent"])):
        w(f"| {label} | {dd['sa3s']} | {f2(dd['sd_total'])} | {f2(dd['sd_within'])} | "
          f"{pc(dd['share_within'])} | {f2(dd['median_range'])} | {f2(dd['p90_range'])} | "
          + ", ".join(f"{nm(x['sa4'])} ({f2(x['range'])})" for x in dd["widest"]) + " |")
    w("")
    w(f"Most cost variation is between SA4s, which is what the factor already prices. What is left "
      f"within SA4s is real but narrow: a typical SA3 sits about {pc(math.exp(m['sd_within']) - 1)} "
      "above or below its SA4's mean. Relative mortgage and relative rent agree only in part (rank "
      f"correlation {f2(co['mortgage_rent_spearman'])}), so the rent robustness check is informative.")
    w("")
    w("### Collinearity")
    w("")
    w(f"Within-SA4 rank correlations across {cl['sa3s']} SA3s in {cl['sa4s']} SA4s with two or more "
      "SA3s. Cost is log median mortgage relative to the SA4 mean; shares are of the SA4's total. "
      f"Approvals are the lagged window; waiting is `participants_eligible_not_using` at "
      f"{month(NEED_EARLIEST)}; need is `participants_with_need` at {month(NEED_BY_CATEGORY)}.")
    w("")
    names = [("approvals_share", "Approvals share"), ("new_sda_share", "New SDA share"),
             ("eligible_share", "Waiting share"), ("need_share", "Need share"),
             ("population_share", "Population share"), ("area_share", "Area share"),
             ("approvals_per_1000", "Approvals per 1,000 residents")]
    w("| | Relative cost | " + " | ".join(n for _, n in names) + " |")
    w("| --- | --- | " + " | ".join("---" for _ in names) + " |")
    for k, label in names:
        w(f"| {label} | {f2(sp[k]['cost'])} | " + " | ".join(f2(sp[k][j]) for j, _ in names) + " |")
    w("")
    w(f"Regressing relative cost on the SA3's shares of approvals, waiting participants, population "
      f"and area (all within SA4) explains {pc(cl['r2_cost_on_controls'])} of it: the residual "
      f"standard deviation is {f2(cl['residual_sd'])} against {f2(cl['cost_sd'])} before. The "
      f"variation the test needs survives the controls. The controls are collinear with one another, "
      f"and new SDA share tracks approvals share ({f2(sp['new_sda_share']['approvals_share'])}) and "
      f"waiting share ({f2(sp['new_sda_share']['eligible_share'])}) about equally, so the regression "
      "can separate cost from the controls but not the controls from each other.")
    w("")
    w("### Across SA4 borders")
    w("")
    w(f"Of the {bd['pairs_used']} usable pairs, {bd['sda_either']} have new SDA on at least one side and "
      f"{bd['sda_both']} on both. Across pairs, the log gap in the national-mix factor has a rank "
      f"correlation of {f2(bd['gap_vs_cost_spearman'])} with the log gap in median mortgage "
      f"({bd['pairs_with_cost']} pairs): the higher-factor side is only slightly more likely to be the "
      "dearer one, so the factor gap is not just a cost gap. But the two sides are not alike in cost "
      f"either (median gap {f2(bd['median_abs_cost_gap'])} log points, as large as the within-SA4 spread), "
      "so the border comparison needs cost as a control, not as an assumption.")
    w("")

    # ---- Recommendation
    w("## Recommendation")
    w("")
    w("Ahead of Phase 2:")
    w("")
    w(f"1. **Within-SA4 rank test: run it.** {q10['sa4s']} SA4s qualify at 10 dwellings, cost is not "
      "collinear with approvals or need within them, and the permutation within SA4 needs nothing "
      "else. It does not need past factors, since it asks only whether SDA leans toward cheap SA3s "
      "more than approvals do. The within-SA4 cost spread is narrow, so expect wide intervals.")
    w("2. **SA4 fixed-effects regression: run it, with need and approvals entered together and read "
      "for the cost coefficient only.** Their mutual collinearity makes their own coefficients "
      "unstable, but relative cost is well identified. HPS and Robust separately; Robust will be "
      "thin (see the counts above).")
    w("3. **Border test: run it on both factor sets, and on the change between them.** The pair "
      "count is large, but pairs overlap heavily, so the effective sample is nearer the "
      f"{bd['sa4_pairs']} SA4 borders. Cluster by SA4 pair and control for the cost gap.")
    w(f"4. **Legacy placebo: run it, but expect little from it.** Legacy stock is only "
      f"{n0(oc['legacy_total'])} dwellings, in {oc['legacy_sa3s']} SA3s, at {month(END)}. It is a "
      "level, not a flow: its SA4 share is set against relative cost exactly as new build's is. "
      f"Existing stock ({n0(oc['existing_total'])} dwellings in {oc['existing_sa3s']} SA3s) also "
      "predates NDIS pricing and would make a larger second placebo for where the building was, "
      "with the caveat that its *enrolment*, unlike its construction, can respond to price.")
    w("5. **Dose-response: run the cost-spread half; the factor-versus-cheapest-SA3 half needs a "
      "cost level comparable across SA4s, which a 2021 median mortgage only approximates.**")
    return "\n".join(L) + "\n"


def rounded(o):
    if isinstance(o, float):
        return round(o, 4)
    if isinstance(o, dict):
        return {k: rounded(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [rounded(v) for v in o]
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", default=str(DATA / "panel"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    a = analyse(load(), out)
    (out / "location_factor_feasibility.json").write_text(json.dumps(rounded(a), indent=1) + "\n")
    (out / "LOCATION_FACTOR_FEASIBILITY.md").write_text(to_markdown(a))
    print(f"wrote {out}/location_factor_feasibility.json, LOCATION_FACTOR_FEASIBILITY.md, "
          "location_factor_pairs.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
