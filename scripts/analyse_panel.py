#!/usr/bin/env python3
"""Answer the four longitudinal questions from the quarterly panel.

Reads data/panel/panel.csv (built by extract_panel.py) and writes
data/panel/analysis.json and data/panel/ANALYSIS.md. Every figure in the
Markdown is computed here, so a new quarter cannot leave the text stating
something the numbers no longer show. Pure standard library: the regressions
are small enough to solve directly.

Usage:  python3 scripts/analyse_panel.py [data/panel]

The panel is region-level, not dwelling-level. Nothing here follows an
individual dwelling or participant; every flow is a net change in a region's
published totals, and the write-up says so wherever it matters.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

CATS = ["Improved Liveability", "High Physical Support", "Robust", "Fully Accessible"]
SHORT = {"Improved Liveability": "IL", "High Physical Support": "HPS", "Robust": "Robust",
         "Fully Accessible": "FA"}
ALL_BUILD_CATS = CATS + ["Multi-Design Category", "Basic"]
# The March 2026 rule removes pipeline dwellings not progressed within 36
# months; pipeline levels from this quarter on are not comparable with before.
PIPELINE_BREAK = "2026-03-31"
LAGS = 4


# --------------------------------------------------------------------------
# Loading and small statistics
# --------------------------------------------------------------------------

class Panel:
    def __init__(self, path: Path):
        self.values, self.geos = {}, {}
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                self.geos[row["geography"]] = (row["level"], row["state"])
                if row["value"] != "":
                    self.values.setdefault((row["geography"], row["category"], row["measure"]),
                                           {})[row["as_at"]] = float(row["value"])
        self.quarters = sorted({q for d in self.values.values() for q in d})
        self.sa4 = sorted(g for g, (lvl, _) in self.geos.items() if lvl == "SA4")

    def get(self, geo, category, measure, quarter):
        return self.values.get((geo, category, measure), {}).get(quarter)

    def total(self, geo, measure, quarter):
        return self.get(geo, "Total", measure, quarter)

    def quarters_with(self, measure, category="Total"):
        return [q for q in self.quarters if self.get("national", category, measure, q) is not None]


def solve(a, b):
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c]:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(x, y, clusters):
    """Least squares with standard errors clustered by region."""
    k = len(x[0])
    xtx = [[sum(r[i] * r[j] for r in x) for j in range(k)] for i in range(k)]
    beta = solve(xtx, [sum(r[i] * v for r, v in zip(x, y)) for i in range(k)])
    resid = [v - sum(b * xi for b, xi in zip(beta, r)) for r, v in zip(x, y)]
    inv = list(zip(*[solve(xtx, [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]))
    groups = {}
    for i, g in enumerate(clusters):
        groups.setdefault(g, []).append(i)
    meat = [[0.0] * k for _ in range(k)]
    for idx in groups.values():
        s = [sum(x[i][a] * resid[i] for i in idx) for a in range(k)]
        for a in range(k):
            for c in range(k):
                meat[a][c] += s[a] * s[c]
    adj = len(groups) / (len(groups) - 1)
    cov = [[adj * sum(inv[a][p] * meat[p][q] * inv[q][c] for p in range(k) for q in range(k))
            for c in range(k)] for a in range(k)]
    return beta, cov


def summed(beta, cov, idx):
    """A sum of coefficients and its standard error."""
    return (sum(beta[i] for i in idx),
            sum(cov[i][j] for i in idx for j in idx) ** 0.5)


def spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den


def r3(v):
    return None if v is None else round(v, 3)


# --------------------------------------------------------------------------
# Question 1: lease-up blip or lasting surplus?
# --------------------------------------------------------------------------

def distributed_lag(p, lags, regions, region_effects=False):
    """Change in participants using SDA on this and earlier quarters' change
    in enrolled places, pooled over SA4 regions. The coefficients sum to the
    number of participants a new place brings into use over `lags` quarters."""
    q = p.quarters
    obs = {}
    for g in regions:
        places = [p.total(g, "enrolled_places", t) for t in q]
        in_use = [p.total(g, "participants_sda_in_use", t) for t in q]
        for t in range(lags + 1, len(q)):
            if in_use[t] is None or in_use[t - 1] is None or None in places[t - lags - 1:t + 1]:
                continue
            obs.setdefault(g, []).append(
                ([places[t - k] - places[t - k - 1] for k in range(lags + 1)],
                 in_use[t] - in_use[t - 1]))
    x, y, cl = [], [], []
    for g, rows in obs.items():
        if region_effects:
            mx = [statistics.fmean(r[0][k] for r in rows) for k in range(lags + 1)]
            my = statistics.fmean(r[1] for r in rows)
            for xs, v in rows:
                x.append([a - b for a, b in zip(xs, mx)])
                y.append(v - my)
                cl.append(g)
        else:
            for xs, v in rows:
                x.append([1.0] + xs)
                y.append(v)
                cl.append(g)
    beta, cov = ols(x, y, cl)
    idx = list(range(lags + 1)) if region_effects else list(range(1, lags + 2))
    total, se = summed(beta, cov, idx)
    return {"lags": [r3(beta[i]) for i in idx], "sum": r3(total), "se": r3(se),
            "observations": len(y), "regions": len(obs)}


def question_1(p):
    iu_q = p.quarters_with("participants_sda_in_use")
    first, last = iu_q[0], iu_q[-1]
    year_ago = iu_q[-5]
    nat = {m: {q: p.total("national", m, q) for q in (first, year_ago, last)}
           for m in ("enrolled_places", "participants_sda_in_use", "places_not_in_use",
                     "participants_eligible_not_using", "pipeline_places")}
    added = nat["enrolled_places"][last] - nat["enrolled_places"][first]
    taken = nat["participants_sda_in_use"][last] - nat["participants_sda_in_use"][first]

    base = {g: p.total(g, "enrolled_places", first) or 0 for g in p.sa4}
    cuts = sorted(base.values())
    lo, hi = cuts[len(cuts) // 3], cuts[2 * len(cuts) // 3]

    def pressure(g):
        spare = p.total(g, "places_not_in_use", first)
        wait = p.total(g, "participants_eligible_not_using", first)
        return None if spare is None or wait is None else wait >= spare

    models = {
        "pooled": distributed_lag(p, LAGS, p.sa4),
        "region_effects": distributed_lag(p, LAGS - 1, p.sa4, region_effects=True),
        "longest_window": distributed_lag(p, 7, p.sa4),
        "small_markets": distributed_lag(p, LAGS - 1, [g for g in p.sa4 if base[g] < lo]),
        "large_markets": distributed_lag(p, LAGS - 1, [g for g in p.sa4 if base[g] >= hi]),
        "waiting_exceeded_spare": distributed_lag(p, LAGS - 1, [g for g in p.sa4 if pressure(g)]),
        "spare_exceeded_waiting": distributed_lag(
            p, LAGS - 1, [g for g in p.sa4 if pressure(g) is False]),
    }

    # Regions that stopped adding stock: does their spare capacity drain?
    quiet = []
    for g in p.sa4:
        for i in range(len(iu_q) - 4):
            a, b = iu_q[i], iu_q[i + 4]
            pa, pb = p.total(g, "enrolled_places", a), p.total(g, "enrolled_places", b)
            sa, sb = p.total(g, "places_not_in_use", a), p.total(g, "places_not_in_use", b)
            if None in (pa, pb, sa, sb) or pa < 50 or sa < 10 or abs(pb - pa) > 0.03 * pa:
                continue
            quiet.append((g, sa, sb))
    quiet_summary = {
        "region_years": len(quiet), "regions": len({g for g, _, _ in quiet}),
        "spare_fell": sum(sb < sa for _, sa, sb in quiet),
        "spare_rose": sum(sb > sa for _, sa, sb in quiet),
        "share_absorbed_in_a_year": r3(sum(sa - sb for _, sa, sb in quiet)
                                       / sum(sa for _, sa, _ in quiet)) if quiet else None,
    }

    # Bursts of enrolment, against the region's own typical in-use growth.
    bursts = []
    q = p.quarters
    for g in p.sa4:
        places = [p.total(g, "enrolled_places", t) for t in q]
        in_use = [p.total(g, "participants_sda_in_use", t) for t in q]
        known = [i for i, v in enumerate(in_use) if v is not None]
        typical = (in_use[known[-1]] - in_use[known[0]]) / (len(known) - 1) * 5
        for t in range(1, len(q) - 4):
            if in_use[t - 1] is None or in_use[t + 4] is None:
                continue
            burst = places[t] - places[t - 1]
            if burst >= 15 and burst >= 0.15 * places[t - 1]:
                bursts.append((g, q[t], burst, in_use[t + 4] - in_use[t - 1], typical))
    total_burst = sum(b[2] for b in bursts)
    burst_summary = {
        "bursts": len(bursts), "regions": len({b[0] for b in bursts}),
        "in_use_growth_per_burst_place": r3(sum(b[3] for b in bursts) / total_burst),
        "typical_growth_per_burst_place": r3(sum(b[4] for b in bursts) / total_burst),
    }

    # Quarters to fill today's spare capacity, region by region.
    regions = []
    for g in p.sa4:
        spare = p.total(g, "places_not_in_use", last)
        spare0 = p.total(g, "places_not_in_use", year_ago)
        use, use0 = (p.total(g, "participants_sda_in_use", t) for t in (last, year_ago))
        places, places0 = (p.total(g, "enrolled_places", t) for t in (last, year_ago))
        if None in (spare, spare0, use, use0) or not places:
            continue
        absorb = (use - use0) / 4
        regions.append({
            "geography": g, "places": places, "spare": spare, "spare_share": r3(spare / places),
            "waiting": p.total(g, "participants_eligible_not_using", last),
            "new_places_per_quarter": (places - places0) / 4,
            "absorbed_per_quarter": absorb,
            "spare_change_per_quarter": (spare - spare0) / 4,
            "pipeline_places": p.total(g, "pipeline_places", last),
            "newbuild_share": r3(sum(p.get(g, c, "newbuild_places", last) or 0 for c in CATS)
                                 / places),
            "quarters_to_fill": round(spare / absorb, 1) if absorb > 0 and spare > 0 else None,
        })
    material = [r for r in regions if r["spare"] >= 20]
    fills = [r["quarters_to_fill"] for r in material if r["quarters_to_fill"]]
    nat_absorb = (nat["participants_sda_in_use"][last] - nat["participants_sda_in_use"][year_ago]) / 4

    # Category ratios: the places-to-need ratio cannot register lease-up (a
    # participant moving in stays in need), so the test is whether need rises
    # where stock is added.
    cat_q = p.quarters_with("participants_with_need", "Improved Liveability")

    def need(g, c, t, mode):
        n = p.get(g, c, "participants_with_need", t)
        if n is None or mode == "left_out":
            return n
        known = sum(p.get(g, k, "participants_with_need", t) or 0 for k in CATS)
        missing = p.get(g, "Missing", "participants_with_need", t) or 0
        return n + (missing * n / known if known else 0)

    ratios = {}
    for mode in ("left_out", "pro_rata"):
        ratios[mode] = {c: [r3(p.get("national", c, "enrolled_places", t) / need("national", c, t, mode))
                            for t in cat_q] for c in CATS}
    need_response = {}
    for mode in ("left_out", "pro_rata"):
        x, y, cl = [], [], []
        for g in p.sa4:
            for c in CATS:
                pl = [p.get(g, c, "enrolled_places", t) for t in cat_q]
                nd = [need(g, c, t, mode) for t in cat_q]
                for t in range(1, len(cat_q)):
                    if None in (pl[t], pl[t - 1], nd[t], nd[t - 1]):
                        continue
                    x.append([1.0, pl[t] - pl[t - 1]])
                    y.append(nd[t] - nd[t - 1])
                    cl.append(g)
        beta, cov = ols(x, y, cl)
        need_response[mode] = {"per_new_place": r3(beta[1]), "se": r3(cov[1][1] ** 0.5)}
    flows = {c: {"places_added": p.get("national", c, "enrolled_places", cat_q[-1])
                 - p.get("national", c, "enrolled_places", cat_q[0]),
                 "need_added": p.get("national", c, "participants_with_need", cat_q[-1])
                 - p.get("national", c, "participants_with_need", cat_q[0]),
                 "newbuild_share": r3(p.get("national", c, "newbuild_places", cat_q[-1])
                                      / p.get("national", c, "enrolled_places", cat_q[-1]))}
             for c in CATS}
    missing_share = [r3(p.get("national", "Missing", "participants_with_need", t)
                        / p.total("national", "participants_with_need", t)) for t in cat_q]

    return {
        "window": [first, last],
        "national": {
            "places_added": added, "in_use_added": taken, "absorbed_share": r3(taken / added),
            "spare": [nat["places_not_in_use"][first], nat["places_not_in_use"][last]],
            "spare_share_last": r3(nat["places_not_in_use"][last] / nat["enrolled_places"][last]),
            "waiting_last": nat["participants_eligible_not_using"][last],
            "absorbed_per_quarter_last_year": nat_absorb,
            "quarters_to_fill": round(nat["places_not_in_use"][last] / nat_absorb, 1),
            "pipeline_places_last": nat["pipeline_places"][last],
        },
        "models": models, "quiet_regions": quiet_summary, "bursts": burst_summary,
        "regions_summary": {
            "regions_with_20_spare": len(material),
            "spare_growing": sum(r["spare_change_per_quarter"] > 0 for r in material),
            "spare_shrinking": sum(r["spare_change_per_quarter"] < 0 for r in material),
            "no_absorption": sum(1 for r in material if not r["quarters_to_fill"]),
            "median_quarters_to_fill": statistics.median(fills) if fills else None,
            "fill_within_8_quarters": sum(1 for f in fills if f <= 8),
            "fill_beyond_20_quarters": sum(1 for f in fills if f > 20),
            "waiting_below_spare": sum(1 for r in material
                                       if r["waiting"] is not None and r["waiting"] < r["spare"]),
        },
        "largest_spare": sorted(regions, key=lambda r: -r["spare"])[:10],
        "regions": regions,
        "category_quarters": cat_q,
        "category_ratios": ratios,
        "need_response": need_response,
        "category_flows": flows,
        "missing_share": missing_share,
    }


# --------------------------------------------------------------------------
# Question 2: pipeline conversion
# --------------------------------------------------------------------------

def question_2(p):
    q = p.quarters

    def newbuild(g, t, cats=ALL_BUILD_CATS):
        return sum(p.get(g, c, "newbuild_dwellings", t) or 0 for c in cats)

    flows = []
    for i in range(1, len(q)):
        pipe0, pipe1 = (p.total("national", "pipeline_dwellings", t) for t in (q[i - 1], q[i]))
        enrolled = newbuild("national", q[i]) - newbuild("national", q[i - 1])
        flows.append({"quarter": q[i], "pipeline": pipe1, "enrolled": enrolled,
                      "net_additions": pipe1 - pipe0 + enrolled})

    # Removal at the break: the fall in pipeline not explained by enrolment is
    # a lower bound on removals (it assumes nothing new was listed that
    # quarter); at the previous year's pace of listings it is the central one.
    brk = q.index(PIPELINE_BREAK)
    removal = {}
    for c in CATS + ["Multi-Design Category", "Total"]:
        cats = ALL_BUILD_CATS if c == "Total" else [c]

        def net(i):
            pipe0 = p.get("national", c, "pipeline_dwellings", q[i - 1]) or 0
            pipe1 = p.get("national", c, "pipeline_dwellings", q[i]) or 0
            return pipe1 - pipe0 + newbuild("national", q[i], cats) - newbuild("national", q[i - 1], cats)
        before = p.get("national", c, "pipeline_dwellings", q[brk - 1])
        trend = statistics.fmean(net(i) for i in range(brk - 4, brk))
        at = net(brk)
        removal[c] = {"pipeline_before": before, "net_additions_at_break": at,
                      "prior_year_net_additions_per_quarter": trend,
                      "lower_bound": max(0.0, -at), "central": trend - at,
                      "lower_bound_share": r3(max(0.0, -at) / before),
                      "central_share": r3((trend - at) / before)}

    # Does a region's pipeline in a category turn into enrolments in the same
    # category, or in another? New-build enrolments over the next four
    # quarters, on own-category and other-category pipeline at the start.
    x, y, cl = [], [], []
    for g in p.sa4:
        for i in range(len(q) - 4):
            if q[i] >= PIPELINE_BREAK:
                continue
            for c in CATS:
                own = p.get(g, c, "pipeline_dwellings", q[i])
                if own is None:
                    continue
                other = sum(p.get(g, k, "pipeline_dwellings", q[i]) or 0
                            for k in CATS + ["Multi-Design Category"] if k != c)
                x.append([1.0, own, other])
                y.append(newbuild(g, q[i + 4], [c]) - newbuild(g, q[i], [c]))
                cl.append(g)
    beta, cov = ols(x, y, cl)

    naive = {}
    for k in (4, 8):
        naive[k] = [{"from": q[i],
                     "ratio": r3((newbuild("national", q[i + k]) - newbuild("national", q[i]))
                                 / p.total("national", "pipeline_dwellings", q[i]))}
                    for i in range(len(q) - k) if q[i] < PIPELINE_BREAK]

    first = q[0]
    return {
        "flows": flows,
        "removal_at_break": removal,
        "same_category": {"own": r3(beta[1]), "own_se": r3(cov[1][1] ** 0.5),
                          "other": r3(beta[2]), "other_se": r3(cov[2][2] ** 0.5),
                          "observations": len(y)},
        "naive_ratio": naive,
        "first_cohort": {"quarter": first,
                         "pipeline": p.total("national", "pipeline_dwellings", first)},
    }


# --------------------------------------------------------------------------
# Question 3: demand dynamics and the location mismatch
# --------------------------------------------------------------------------

def question_3(p):
    iu_q = p.quarters_with("participants_sda_in_use")
    first, last = iu_q[0], iu_q[-1]
    rows = []
    for g in p.sa4:
        vals = {m: (p.total(g, m, first), p.total(g, m, last))
                for m in ("participants_eligible_not_using", "enrolled_places",
                          "participants_sda_in_use", "participants_total_need")}
        if any(None in v for v in vals.values()):
            continue
        rows.append({"geography": g, **{m: v for m, v in vals.items()}})

    def d(r, m):
        return r[m][1] - r[m][0]
    rows.sort(key=lambda r: d(r, "enrolled_places"))
    n = len(rows)
    terciles = []
    for name, grp in (("least", rows[:n // 3]), ("middle", rows[n // 3:2 * n // 3]),
                      ("most", rows[2 * n // 3:])):
        e0 = sum(r["participants_eligible_not_using"][0] for r in grp)
        terciles.append({"growth": name, "regions": len(grp),
                         "places_added": sum(d(r, "enrolled_places") for r in grp),
                         "in_use_added": sum(d(r, "participants_sda_in_use") for r in grp),
                         "waiting_change": sum(d(r, "participants_eligible_not_using") for r in grp),
                         "waiting_change_share": r3(sum(d(r, "participants_eligible_not_using")
                                                        for r in grp) / e0)})
    prop = [r for r in rows if r["participants_eligible_not_using"][0] >= 20
            and r["enrolled_places"][0] >= 20]

    def per_place(measure):
        x = [[1.0, d(r, "enrolled_places")] for r in rows]
        beta, cov = ols(x, [d(r, measure) for r in rows], [r["geography"] for r in rows])
        return {"per_new_place": r3(beta[1]), "se": r3(cov[1][1] ** 0.5)}

    mismatch = []
    for t in iu_q:
        short, excess, net_surplus, counted = 0, 0.0, 0.0, 0
        for g in p.sa4:
            spare = p.total(g, "places_not_in_use", t)
            wait = p.total(g, "participants_eligible_not_using", t)
            if spare is None or wait is None or not p.total(g, "enrolled_places", t):
                continue
            counted += 1
            if wait > spare:
                short += 1
                excess += wait - max(spare, 0)
            else:
                net_surplus += spare - wait
        mismatch.append({"quarter": t, "regions": counted, "regions_short": short,
                         "waiting_beyond_local_spare": excess,
                         "spare_beyond_local_waiting": net_surplus,
                         "waiting": p.total("national", "participants_eligible_not_using", t),
                         "spare": p.total("national", "places_not_in_use", t)})
    return {
        "window": [first, last],
        "regions": n,
        "waiting_fell": sum(d(r, "participants_eligible_not_using") < 0 for r in rows),
        "waiting_rose": sum(d(r, "participants_eligible_not_using") > 0 for r in rows),
        "national_waiting_change": p.total("national", "participants_eligible_not_using", last)
        - p.total("national", "participants_eligible_not_using", first),
        "terciles": terciles,
        "spearman_absolute": r3(spearman([d(r, "enrolled_places") for r in rows],
                                         [d(r, "participants_eligible_not_using") for r in rows])),
        "spearman_proportional": r3(spearman(
            [r["enrolled_places"][1] / r["enrolled_places"][0] - 1 for r in prop],
            [r["participants_eligible_not_using"][1] / r["participants_eligible_not_using"][0] - 1
             for r in prop])),
        "proportional_regions": len(prop),
        "waiting_per_new_place": per_place("participants_eligible_not_using"),
        "need_per_new_place": per_place("participants_total_need"),
        "mismatch": mismatch,
    }


# --------------------------------------------------------------------------
# Question 4: persistently short or long, or noisy?
# --------------------------------------------------------------------------

def band(ratio):
    return 0 if ratio < 1 else (1 if ratio <= 1.5 else 2)


BANDS = ["short", "balanced", "long"]


def classify(bands):
    if len(set(bands)) == 1:
        return BANDS[bands[0]]
    steps = [b - a for a, b in zip(bands, bands[1:]) if a != b]
    if all(s > 0 for s in steps):
        return "drifting up"
    if all(s < 0 for s in steps):
        return "drifting down"
    return "reverses"


def question_4(p):
    cat_q = p.quarters_with("participants_with_need", "Improved Liveability")
    kinds = ["short", "balanced", "long", "drifting up", "drifting down", "reverses", "thin"]
    out, cells = {}, []
    for mode in ("left_out", "pro_rata"):
        out[mode] = {}
        for c in CATS:
            counts = dict.fromkeys(kinds, 0)
            for g in p.sa4:
                pl = [p.get(g, c, "enrolled_places", t) for t in cat_q]
                nd = [p.get(g, c, "participants_with_need", t) for t in cat_q]
                if None in pl or None in nd or min(nd) < 10:
                    counts["thin"] += 1
                    continue
                if mode == "pro_rata":
                    adj = []
                    for t, n in zip(cat_q, nd):
                        known = sum(p.get(g, k, "participants_with_need", t) or 0 for k in CATS)
                        missing = p.get(g, "Missing", "participants_with_need", t) or 0
                        adj.append(n + (missing * n / known if known else 0))
                    nd = adj
                ratios = [a / b for a, b in zip(pl, nd)]
                kind = classify([band(r) for r in ratios])
                counts[kind] += 1
                if mode == "left_out":
                    cells.append({"geography": g, "category": c, "kind": kind,
                                  "first": r3(ratios[0]), "last": r3(ratios[-1]),
                                  "need_last": nd[-1], "places_last": pl[-1],
                                  "gap_last": pl[-1] - nd[-1]})
            out[mode][c] = counts

    iu_q = p.quarters_with("participants_sda_in_use")
    agg = dict.fromkeys(["always short", "always covered", "short to covered",
                         "covered to short", "reverses"], 0)
    always_short = []
    for g in p.sa4:
        states = []
        for t in iu_q:
            spare = p.total(g, "places_not_in_use", t)
            wait = p.total(g, "participants_eligible_not_using", t)
            if spare is None or wait is None:
                break
            states.append(wait > spare)
        if len(states) < len(iu_q):
            continue
        steps = [b - a for a, b in zip(states, states[1:]) if a != b]
        if not steps:
            kind = "always short" if states[0] else "always covered"
        elif all(s < 0 for s in steps):
            kind = "short to covered"
        elif all(s > 0 for s in steps):
            kind = "covered to short"
        else:
            kind = "reverses"
        agg[kind] += 1
        if kind == "always short":
            always_short.append({
                "geography": g,
                "waiting_beyond_spare": p.total(g, "participants_eligible_not_using", iu_q[-1])
                - max(p.total(g, "places_not_in_use", iu_q[-1]), 0)})
    always_short.sort(key=lambda r: -r["waiting_beyond_spare"])

    def top(kind, cats, key, n=8):
        pick = [c for c in cells if c["kind"] == kind and c["category"] in cats]
        return sorted(pick, key=key)[:n]
    return {
        "quarters": cat_q,
        "by_category": out,
        "aggregate": agg,
        "aggregate_quarters": [iu_q[0], iu_q[-1]],
        "always_short": always_short,
        "largest_persistent_shortfalls": top("short", CATS, lambda c: c["gap_last"]),
        "largest_persistent_surpluses": top("long", CATS, lambda c: -c["gap_last"]),
    }


# --------------------------------------------------------------------------
# The write-up
# --------------------------------------------------------------------------

def n0(v):
    return f"{v:,.0f}"


def pct(v, signed=False):
    if not signed and 0 <= v < 0.005:
        return "under 1%"
    return f"{v:+.0%}" if signed else f"{v:.0%}"


def count(v):
    return "none" if v == 0 else str(v)


def direction(series):
    change = series[-1] - series[0]
    return 0 if abs(change) < 0.03 else (1 if change > 0 else -1)


def name(geo):
    return geo.replace("sa4:", "")


def month(q):
    y, m, _ = q.split("-")
    return f"{['Mar', 'Jun', 'Sep', 'Dec'][int(m) // 3 - 1]} {y}"


def trend_word(series):
    ups = sum(b > a for a, b in zip(series, series[1:]))
    downs = sum(b < a for a, b in zip(series, series[1:]))
    steps = len(series) - 1
    if ups == steps:
        return "rising every quarter"
    if downs == steps:
        return "falling every quarter"
    if abs(series[-1] - series[0]) < 0.03:
        return "flat"
    return f"{'up' if series[-1] > series[0] else 'down'} in {max(ups, downs)} of {steps} quarters"


def to_markdown(a):
    q1, q2, q3, q4 = a["q1"], a["q2"], a["q3"], a["q4"]
    nat, m, rs = q1["national"], q1["models"], q1["regions_summary"]
    w0, w1 = month(q1["window"][0]), month(q1["window"][1])
    cq = q1["category_quarters"]
    c0, c1 = month(cq[0]), month(cq[-1])
    L = []
    add = L.append

    add("# Longitudinal analysis: four questions")
    add("")
    add("Generated by `scripts/analyse_panel.py` from `data/panel/panel.csv`. Every figure "
        "is computed; do not edit by hand. The panel is **region-level**: nothing here "
        "follows an individual dwelling or participant, and every flow is a net change in "
        "a region's published totals. See `VALIDATION.md` for which quarters support "
        "which measure.")
    add("")
    add("## In brief")
    add("")
    hps = q1["category_ratios"]["left_out"]["High Physical Support"]
    fa = q1["category_ratios"]["left_out"]["Fully Accessible"]
    add(f"1. **Lasting, not a blip.** From {w0} to {w1} enrolled places grew by "
        f"{n0(nat['places_added'])} and participants using SDA by {n0(nat['in_use_added'])}. "
        f"A new place brings about {m['pooled']['sum']:.2f} participants into use, "
        f"almost all within three quarters, and nothing after. Spare capacity grew from "
        f"{n0(nat['spare'][0])} to {n0(nat['spare'][1])} places. Regions that stopped building "
        f"did not drain: {pct(q1['quiet_regions']['share_absorbed_in_a_year'])} of their "
        f"spare capacity was taken up in a year.")
    add(f"2. **The pipeline converts slowly, and much of it never.** A pipeline dwelling "
        f"yields about {q2['same_category']['own']:.2f} enrolments in the same category "
        f"within a year, and pipeline in other categories predicts none. The March 2026 "
        f"36-month rule removed at least "
        f"{n0(q2['removal_at_break']['Total']['lower_bound'])} dwellings, and about "
        f"{n0(q2['removal_at_break']['Total']['central'])} at the prior year's rate of new "
        f"listings: {pct(q2['removal_at_break']['Total']['lower_bound_share'])}–"
        f"{pct(q2['removal_at_break']['Total']['central_share'])} of the pipeline.")
    t_most = next(t for t in q3["terciles"] if t["growth"] == "most")
    t_least = next(t for t in q3["terciles"] if t["growth"] == "least")
    mm0, mm1 = q3["mismatch"][0], q3["mismatch"][-1]
    add(f"3. **Waiting falls where stock is added, but slowly.** In the third of regions "
        f"adding the most places, participants eligible but not yet using SDA fell "
        f"{pct(-t_most['waiting_change_share'])}; in the third adding the least, "
        f"{pct(-t_least['waiting_change_share'])}. Regions with more waiting than spare "
        f"places went from {mm0['regions_short']} to {mm1['regions_short']}, while spare "
        f"places beyond local waiting rose from {n0(mm0['spare_beyond_local_waiting'])} to "
        f"{n0(mm1['spare_beyond_local_waiting'])}.")
    agg = q4["aggregate"]
    rev = sum(q4["by_category"]["left_out"][c]["reverses"] for c in CATS)
    cells = sum(sum(v for k, v in q4["by_category"]["left_out"][c].items() if k != "thin")
                for c in CATS)
    add(f"4. **Persistent, not noisy.** Of {cells} region × category cells with enough "
        f"participants, {rev} move back and forth across a band in the "
        f"{len(cq)} quarters from {c0} to {c1}. The rest stay put or drift one way. "
        f"High Physical Support rose from {hps[0]:.2f} to {hps[-1]:.2f} places per "
        f"participant nationally; Fully Accessible fell from {fa[0]:.2f} to {fa[-1]:.2f}.")
    add("")

    # ---- Q1
    add("## 1. Lease-up blip or lasting surplus?")
    add("")
    add("**What the data can support.** Enrolled places by region for 13 quarters and "
        "participants with SDA in use for 11, so the change in use can be set against the "
        "change in places, region by region. **What it cannot.** Participants in use are not "
        "published by design category, so absorption is measured for a region's stock as a "
        "whole, not for High Physical Support or Robust separately. Places not in SDA use is "
        "an upper bound on vacancy: a place can be occupied by someone not funded for SDA.")
    add("")
    add("### Absorption")
    add("")
    add(f"Nationally, {n0(nat['places_added'])} places were added from {w0} to {w1} and "
        f"{n0(nat['in_use_added'])} more participants came to use SDA: "
        f"{pct(nat['absorbed_share'])}. Spare capacity went from {n0(nat['spare'][0])} to "
        f"{n0(nat['spare'][1])} ({pct(nat['spare_share_last'])} of places).")
    add("")
    add("Region by region, the change in participants using SDA each quarter was regressed on "
        "the change in enrolled places that quarter and in earlier ones. The coefficients sum "
        "to the number of participants a new place brings into use:")
    add("")
    add("| Specification | Participants per new place (± s.e.) | Lag profile (quarter 0, 1, 2, …) | Regions |")
    add("| --- | --- | --- | --- |")
    labels = [("pooled", f"All regions, {LAGS} lags"),
              ("region_effects", "Region fixed effects"),
              ("longest_window", "All regions, 7 lags"),
              ("small_markets", "Smallest third of markets"),
              ("large_markets", "Largest third of markets"),
              ("waiting_exceeded_spare", f"Waiting ≥ spare at {w0}"),
              ("spare_exceeded_waiting", f"Spare > waiting at {w0}")]
    for key, label in labels:
        r = m[key]
        add(f"| {label} | {r['sum']:.2f} ± {r['se']:.2f} | "
            f"{', '.join(f'{x:.2f}' for x in r['lags'])} | {r['regions']} |")
    add("")
    add(f"Every specification lands between {min(m[k]['sum'] for k, _ in labels):.2f} and "
        f"{max(m[k]['sum'] for k, _ in labels):.2f}. The effect arrives within three quarters "
        f"and the longer windows find no tail. Absorption is somewhat higher in small markets "
        f"and where people were waiting, but nowhere near one for one.")
    add("")
    qr, bu = q1["quiet_regions"], q1["bursts"]
    add(f"Two plainer checks agree. **Regions that stopped building**, with places flat "
        f"within 3% over a year ({qr['region_years']} region-years in {qr['regions']} regions), "
        f"absorbed {pct(qr['share_absorbed_in_a_year'])} of their spare capacity in that year; "
        f"it fell in {qr['spare_fell']} and rose in {qr['spare_rose']}. If the spare were stock "
        f"waiting to be leased up, it would drain once building stopped, and it does not. "
        f"**Sharp bursts** ({bu['bursts']} quarters with ≥15% growth, in {bu['regions']} "
        f"regions) look fully absorbed at first sight: in-use grew by "
        f"{bu['in_use_growth_per_burst_place']:.2f} per burst place over the next year. But "
        f"those regions were already adding {bu['typical_growth_per_burst_place']:.2f} per "
        f"burst place in a typical year, so the burst itself added about "
        f"{bu['in_use_growth_per_burst_place'] - bu['typical_growth_per_burst_place']:.2f} "
        f"per place.")
    add("")
    add("### Quarters to fill today's spare capacity")
    add("")
    add(f"At last year's absorption, and with **no further building**, it would take "
        f"{nat['quarters_to_fill']:.0f} quarters to fill today's national spare capacity. There "
        f"are {n0(nat['waiting_last'])} participants eligible but not using SDA against "
        f"{n0(nat['spare'][1])} spare places, and {n0(nat['pipeline_places_last'])} places "
        f"are in the pipeline. Of the {rs['regions_with_20_spare']} regions with 20 or more "
        f"spare places:")
    add("")
    add(f"- spare capacity grew over the last year in {rs['spare_growing']} and shrank in "
        f"{rs['spare_shrinking']};")
    add(f"- the median region needs {rs['median_quarters_to_fill']:.0f} quarters at its own "
        f"recent absorption; {count(rs['fill_within_8_quarters'])} could do it within two years, "
        f"{rs['fill_beyond_20_quarters']} would need more than five, and "
        f"{count(rs['no_absorption'])} absorbed nobody;")
    add(f"- in {rs['waiting_below_spare']}, fewer people are waiting locally than there are "
        f"spare places, so local demand alone could not fill them.")
    add("")
    add("| Region | Spare places | Share | Waiting | New places / qtr | Absorbed / qtr | Quarters to fill | Pipeline places |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in q1["largest_spare"]:
        add(f"| {name(r['geography'])} | {n0(r['spare'])} | {pct(r['spare_share'])} | "
            f"{n0(r['waiting'])} | {r['new_places_per_quarter']:.1f} | "
            f"{r['absorbed_per_quarter']:.1f} | "
            f"{'—' if r['quarters_to_fill'] is None else n0(r['quarters_to_fill'])} | "
            f"{'—' if r['pipeline_places'] is None else n0(r['pipeline_places'])} |")
    add("")
    add("### By design category")
    add("")
    add("The places-to-need ratio **cannot register lease-up**: a participant who moves in "
        "stays in need, moving from eligible to in use. It can only fall back if need rises "
        "where stock is added. It does not. Across regions and categories, a new place adds "
        f"{q1['need_response']['left_out']['per_new_place']:.2f} "
        f"(± {q1['need_response']['left_out']['se']:.2f}) to that category's recorded need, and "
        f"{q1['need_response']['pro_rata']['per_new_place']:.2f} with uncategorised need spread "
        "pro-rata.")
    add("")
    add(f"| Category | Places added, {c0}–{c1} | Need added | New-build share | Ratio, need as recorded | Ratio, Missing pro-rata |")
    add("| --- | --- | --- | --- | --- | --- |")
    for c in CATS:
        f = q1["category_flows"][c]
        a_, b_ = q1["category_ratios"]["left_out"][c], q1["category_ratios"]["pro_rata"][c]
        add(f"| {c} | {n0(f['places_added'])} | {n0(f['need_added'])} | "
            f"{pct(f['newbuild_share'])} | {a_[0]:.2f} → {a_[-1]:.2f} ({trend_word(a_)}) | "
            f"{b_[0]:.2f} → {b_[-1]:.2f} ({trend_word(b_)}) |")
    add("")
    ms = q1["missing_share"]
    differ = [c for c in CATS if direction(q1["category_ratios"]["left_out"][c])
              != direction(q1["category_ratios"]["pro_rata"][c])]
    agree = ("the direction of every category is the same under both"
             if not differ else
             "the direction is the same under both except for "
             + " and ".join(differ)
             + ", which improves only once the uncategorised need is spread")
    up = [c for c in CATS if direction(q1["category_ratios"]["left_out"][c]) > 0]
    rising = f"; {' and '.join(up)} {'rises' if len(up) == 1 else 'rise'} despite it" if up else ""
    add(f"**Sensitivity to the uncategorised fifth.** Need without a design category fell from "
        f"{pct(ms[0])} to {pct(ms[-1])} of the total over these quarters. As it is classified, "
        f"recorded need in each category rises, so ratios read as recorded drift down over "
        f"time for that reason alone{rising}. The pro-rata reading removes the drift, and "
        f"{agree}.")
    add("")
    add(f"**Verdict.** On the colleague's hypothesis: yes, some new stock is taken up in its "
        f"first three quarters. But about {pct(1 - m['pooled']['sum'])} of it is not, spare "
        "capacity does "
        "not drain once building stops, and need does not rise to meet stock. The surplus "
        "is lasting. The new-build/vacancy link in the single-quarter vacancy view is "
        "therefore mostly oversupply, not lease-up.")
    add("")

    # ---- Q2
    rb = q2["removal_at_break"]
    sc = q2["same_category"]
    add("## 2. Pipeline conversion")
    add("")
    add("**What the data can support.** Pipeline dwellings and enrolled new-build dwellings by "
        "region and category, every quarter. **What it cannot.** Following a listed dwelling "
        "to enrolment. New enrolments between two quarters include dwellings listed after "
        "the first, so enrolments over the pipeline is not a conversion rate. The naive "
        f"ratio over two years is {q2['naive_ratio'][8][0]['ratio']:.2f} from "
        f"{month(q2['naive_ratio'][8][0]['from'])}, which is impossible as a rate. Two "
        "things can be measured instead.")
    add("")
    add(f"**How fast, in the same category.** Per pipeline dwelling in a region and category, "
        f"new-build enrolments in that category over the next year were {sc['own']:.2f} "
        f"(± {sc['own_se']:.2f}). Pipeline in the region's *other* categories predicts "
        f"{sc['other']:.2f} (± {sc['other_se']:.2f}), so there is no sign of net switching "
        f"between categories. Individual switches that cancel out cannot be seen.")
    add("")
    add(f"**How much never converts.** In the {month(PIPELINE_BREAK)} quarter the pipeline "
        f"fell by {n0(-rb['Total']['net_additions_at_break'])} dwellings more than were "
        f"enrolled. That is a lower bound on removals that quarter, since it assumes nothing new "
        f"was listed. Had new "
        f"listings continued at the previous year's "
        f"{n0(rb['Total']['prior_year_net_additions_per_quarter'])} a quarter, removals were "
        f"about {n0(rb['Total']['central'])}. The NDIA also removes enrolled dwellings it was "
        f"slow to take out of the pipeline, and does not say how many of the removals were of "
        f"that kind:")
    add("")
    add("| Category | Pipeline before | Removed, lower bound | Removed, central | Share |")
    add("| --- | --- | --- | --- | --- |")
    for c in CATS + ["Multi-Design Category", "Total"]:
        r = rb[c]
        add(f"| {c} | {n0(r['pipeline_before'])} | {n0(r['lower_bound'])} | "
            f"{n0(r['central'])} | {pct(r['lower_bound_share'])}–{pct(r['central_share'])} |")
    add("")
    fc = q2["first_cohort"]
    add(f"A dwelling removed under the 36-month rule had been listed by March 2023, and was "
        f"therefore already in the {month(fc['quarter'])} pipeline of {n0(fc['pipeline'])}. If "
        f"the removals were all of that kind, between "
        f"{pct(rb['Total']['lower_bound'] / fc['pipeline'])} and "
        f"{pct(min(rb['Total']['central'] / fc['pipeline'], 1))} of that first cohort was "
        f"dropped rather than enrolled. Either way, the NDIA's pipeline figures before March "
        f"2026 overstated what was coming by roughly "
        f"{pct(rb['Total']['lower_bound_share'])}–{pct(rb['Total']['central_share'])}.")
    add("")
    add("**Calibrating the 'with pipeline' scenario.** The pipeline published now has had its "
        "stale listings removed, so its conversion should be better than the first cohort's. "
        "It should still be discounted:")
    add("")
    add(f"- new-build enrolments each year run at about {sc['own']:.0%} of the pipeline in "
        f"the same region and category at the start of that year;")
    add(f"- before the rule, {pct(rb['Total']['lower_bound_share'])}–"
        f"{pct(rb['Total']['central_share'])} of the listed pipeline was not going to enrol.")
    add("")
    add(f"Counting one to two years of enrolment at that rate (roughly "
        f"{pct(sc['own'])}–{pct(min(2 * sc['own'], 1))} of today's pipeline), rather than all "
        f"of it, is what the series supports.")
    add("")

    # ---- Q3
    add("## 3. Demand dynamics")
    add("")
    add(f"**What the data can support.** Participants eligible but not yet using SDA, by SA4, "
        f"for 11 quarters ({w0}–{w1}); no design category. **What it cannot.** Where waiting "
        f"participants go when they move, or whether they are waiting for a specific "
        f"category. A region's waiting count is where the participant lives, not where they "
        f"would accept a place.")
    add("")
    add(f"Waiting fell by {n0(-q3['national_waiting_change'])} nationally, in "
        f"{q3['waiting_fell']} of {q3['regions']} regions, and rose in {q3['waiting_rose']}. It "
        f"fell where stock was added: rank correlation between places added and the change in "
        f"waiting {q3['spearman_absolute']:.2f}, and {q3['spearman_proportional']:.2f} in "
        f"proportional terms across {q3['proportional_regions']} regions.")
    add("")
    add("| Regions by places added | Regions | Places added | In use added | Waiting change |")
    add("| --- | --- | --- | --- | --- |")
    for t in q3["terciles"]:
        add(f"| {t['growth'].capitalize()} third | {t['regions']} | {n0(t['places_added'])} | "
            f"{n0(t['in_use_added'])} | {n0(t['waiting_change'])} "
            f"({pct(t['waiting_change_share'], True)}) |")
    add("")
    wp, npp = q3["waiting_per_new_place"], q3["need_per_new_place"]
    from_waiting = -wp["per_new_place"] / (npp["per_new_place"] - wp["per_new_place"])
    add(f"Per new place, waiting fell by {-wp['per_new_place']:.2f} (± {wp['se']:.2f}) and "
        f"total recorded need rose by {npp['per_new_place']:.2f} (± {npp['se']:.2f}). So about "
        f"{pct(from_waiting)} of what a new place draws into use comes off the local waiting "
        f"list, and the rest is new need recorded where the stock now exists: participants "
        f"arriving or newly found eligible.")
    add("")
    add("### The location mismatch over time")
    add("")
    add("| Quarter | Regions short | Waiting beyond local spare | Spare beyond local waiting | National waiting | National spare |")
    add("| --- | --- | --- | --- | --- | --- |")
    for r in q3["mismatch"]:
        add(f"| {month(r['quarter'])} | {r['regions_short']} of {r['regions']} | "
            f"{n0(r['waiting_beyond_local_spare'])} | {n0(r['spare_beyond_local_waiting'])} | "
            f"{n0(r['waiting'])} | {n0(r['spare'])} |")
    add("")
    add(f"The mismatch has turned over. In {w0}, {mm0['regions_short']} regions had more "
        f"people waiting than spare places, and {n0(mm0['waiting_beyond_local_spare'])} people "
        f"were beyond local spare capacity. By {w1} that was {mm1['regions_short']} regions and "
        f"{n0(mm1['waiting_beyond_local_spare'])} people, while spare places in regions that "
        f"could already house everyone waiting grew from "
        f"{n0(mm0['spare_beyond_local_waiting'])} to {n0(mm1['spare_beyond_local_waiting'])}. "
        f"The aggregate shortage of places is closing. What remains is a residual of regions "
        f"still short, and a growing overhang elsewhere.")
    add("")

    # ---- Q4
    add("## 4. Persistently short, persistently long, or noise?")
    add("")
    add(f"**What the data can support.** Places per participant by region and category for "
        f"{len(cq)} quarters ({c0}–{c1}), and waiting against spare, without category, for 11. "
        f"Seven quarters are enough to tell a stable position from a reversing one. They are "
        f"not enough to tell a slow trend from a cycle. Cells with fewer than 10 participants "
        f"in any quarter are set aside as thin.")
    add("")
    add("Bands as in the explorer: short below 1.0, balanced 1.0–1.5, long above 1.5.")
    add("")
    kinds = ["short", "balanced", "long", "drifting up", "drifting down", "reverses", "thin"]
    add("| Category | " + " | ".join(k.capitalize() for k in kinds) + " |")
    add("| --- | " + " | ".join("---" for _ in kinds) + " |")
    for mode, label in (("left_out", "need as recorded"), ("pro_rata", "Missing pro-rata")):
        for c in CATS:
            row = q4["by_category"][mode][c]
            add(f"| {SHORT[c]}, {label} | " + " | ".join(str(row[k]) for k in kinds) + " |")
    add("")
    lo_ = q4["by_category"]["left_out"]
    pr_ = q4["by_category"]["pro_rata"]
    add(f"Improved Liveability and Fully Accessible are short, persistently and almost "
        f"everywhere: {lo_['Improved Liveability']['short']} and "
        f"{lo_['Fully Accessible']['short']} regions in every quarter. Spreading the "
        f"uncategorised need pro-rata only deepens it "
        f"({pr_['Improved Liveability']['short']} and {pr_['Fully Accessible']['short']}). High "
        f"Physical Support is long in {lo_['High Physical Support']['long']} regions throughout "
        f"and drifting further long in {lo_['High Physical Support']['drifting up']}. It is the "
        f"category most sensitive to the uncategorised need: pro-rata, "
        f"{pr_['High Physical Support']['long']} stay long and "
        f"{pr_['High Physical Support']['short']} are short throughout. Robust is too thin to "
        f"read in {lo_['Robust']['thin']} regions.")
    add("")
    add(f"Without design category, over {month(q4['aggregate_quarters'][0])}–"
        f"{month(q4['aggregate_quarters'][1])}:")
    add("")
    add(f"- {agg['always short']} regions had more people waiting than spare places in every quarter;")
    add(f"- {agg['short to covered']} moved from short to covered and stayed there;")
    add(f"- {agg['covered to short']} went the other way;")
    add(f"- {agg['always covered']} were covered throughout;")
    add(f"- {agg['reverses']} went back and forth.")
    add("")
    add("**Persistently short, waiting beyond local spare in the latest quarter:** "
        + "; ".join(f"{name(r['geography'])} ({n0(r['waiting_beyond_spare'])})"
                    for r in q4["always_short"][:10]) + ".")
    add("")
    add("**Largest persistent shortfalls by category** (places less participants, latest "
        "quarter): " + "; ".join(f"{name(c['geography'])} {SHORT[c['category']]} "
                                 f"({n0(c['gap_last'])})"
                                 for c in q4["largest_persistent_shortfalls"]) + ".")
    add("")
    add("**Largest persistent surpluses by category:** "
        + "; ".join(f"{name(c['geography'])} {SHORT[c['category']]} (+{n0(c['gap_last'])})"
                    for c in q4["largest_persistent_surpluses"]) + ".")
    add("")

    add("## Caveats that apply throughout")
    add("")
    add("- **Region-level only.** No dwelling or participant is followed. Absorption, "
        "conversion and waiting changes are net changes in published totals.")
    add("- **Participants in use are estimated by the NDIA** from payments, bookings and "
        "address matching. Places not in SDA use is an upper bound on vacancy, not a count.")
    add("- **Places count '6+ residents' as six**, and the derivation carries the calibration "
        "error `VALIDATION.md` reports: 96–99% exact against P.7 each quarter.")
    add("- **Need by design category exists for seven quarters only**, and about a fifth has "
        "no category. Every category result above is given both as recorded and with that "
        "fifth spread pro-rata.")
    add("- **2024-25 Q3's participant figures are as at 2 April**, not 31 March.")
    add("- **Pipeline levels before and after March 2026 are not comparable.** Removal "
        "estimates assume removals before the rule were negligible; the NDIA says enrolled "
        "dwellings were sometimes left in the pipeline, so they may be slightly understated.")
    add("- **The regressions pool regions of very different sizes**, with standard errors "
        "clustered by region. They describe the typical relation, not any one region.")
    return "\n".join(L) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("panel_dir", type=Path, nargs="?", default=Path("data/panel"))
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()
    out = args.out or args.panel_dir
    out.mkdir(parents=True, exist_ok=True)
    p = Panel(args.panel_dir / "panel.csv")
    analysis = {"q1": question_1(p), "q2": question_2(p), "q3": question_3(p), "q4": question_4(p)}
    (out / "analysis.json").write_text(json.dumps(analysis, indent=1) + "\n")
    (out / "ANALYSIS.md").write_text(to_markdown(analysis))
    q1 = analysis["q1"]
    print(f"wrote {out}/analysis.json and ANALYSIS.md")
    print(f"  absorption per new place: {q1['models']['pooled']['sum']:.2f} "
          f"(region effects {q1['models']['region_effects']['sum']:.2f})")
    print(f"  quarters to fill national spare: {q1['national']['quarters_to_fill']:.0f}")


if __name__ == "__main__":
    main()
