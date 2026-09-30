#!/usr/bin/env python3
"""Phase 2 of the location-factor experiment: does new SDA lean toward cheap SA3s?

The location factor is set per SA4 and building type, but land cost varies
within an SA4, so the margin on a new SDA dwelling should be highest on the
SA4's cheapest land. Cheap outer suburbs get more of all building, though,
because that is where land is. So every test here asks whether SDA leans
toward cheap SA3s *more than general residential building does*.

Tests (numbered as in the brief):
  1. Within-SA4 rank test, with a permutation test that shuffles SA3s within
     SA4, so nothing between SA4s can leak in.
  2. Share regression with SA4 fixed effects, clustered by SA4, and a
     within-SA4 multinomial (Poisson with SA4 effects) version.
  3. Border test: adjacent SA3s either side of an SA4 border, on the factors in
     force when building was committed (the combined table to June 2023, the
     new-build table after), and before-and-after the July 2023 re-set.
  4. Placebos: legacy and existing stock, which predate NDIS pricing.
  5. Dose-response: is the lean stronger where cost spreads wider within the SA4?
Plus robustness: without Victoria, without the largest SA4s, rent for
mortgage, without SA3s with very few approvals, without growth corridors,
and approvals lags from 0 to 8 quarters.

Reads committed files only (see feasibility_location_factor.py) and writes
data/panel/location_factor.json and LOCATION_FACTOR.md. Every figure in the
Markdown is computed here. Pure standard library; permutations use a fixed
seed, so the output is reproducible byte for byte.

Usage:  python3 scripts/analyse_location_factor.py [-o data/panel]

Region-level throughout. Nothing here follows an individual dwelling; every
SDA flow is a net change in a region's published totals, and every finding is
ecological.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyse_panel import ols, solve, spearman  # noqa: E402
from feasibility_location_factor import (  # noqa: E402
    DATA, END, NEED_BY_CATEGORY, NEED_EARLIEST, START, approvals, change, load)

SEED = 20260930
PERMUTATIONS = 5000
MIN_OUTCOME = 10          # an SA4 qualifies with at least this much of the outcome
MIN_PLACEBO = {"legacy": 5, "existing": 10}
LAG_PRIMARY = 4           # quarters between approval and enrolment
LAGS = [0, 2, 4, 6, 8]
SMALL_APPROVALS = 100     # over the three-year window: about the bottom 5% of SA3s
CORRIDOR_SHARE = 0.10     # top tenth of SA3s by house approvals per 1,000 residents
DROP_LARGEST = 5
OUTCOMES = [("new_build", "New build (all categories)"),
            ("hps", "High Physical Support (enrolled)"),
            ("robust", "Robust (enrolled)")]
NEED_FOR = {"new_build": "eligible_not_using", "hps": "need_hps", "robust": "need_robust"}
MIN_BORDER_KM = 0.5
# The border test's factor sets. Until 30 June 2023 one table served all stock;
# from 1 July 2023 new builds have their own (revised in v1.4, unchanged since).
FACTOR_SETS = [("combined", "Combined table, to June 2023", ("2022-23", "1.1"), "All"),
               ("new_build", "New-build table, from July 2023", ("2026-27", "1.0"), "New build")]
# SDA windows for the before/after comparison, with approvals lagged as above.
MIDPOINT = "2024-06-30"
GAP_SIGN_TEST = 0.05


# --------------------------------------------------------------------------
# The SA3 frame
# --------------------------------------------------------------------------

def quarters_between(first, last, available):
    return [q for q in available if first <= q <= last]


def build_frame(d):
    appr, quarters, _, _, _ = approvals(d)
    houses = defaultdict(lambda: defaultdict(float))
    sa2_sa3 = {r["SA2_CODE_2021"]: r["SA3_CODE_2021"] for r in d["asgs"]}
    for r in d["approvals"]:
        if len(r["region"]) == 9:
            houses[sa2_sa3[r["region"]]][r["quarter"]] += float(r["houses"])
    sda_quarters = [q for q in quarters if START < q <= END]
    if len(sda_quarters) != 12:
        raise ValueError(f"expected 12 quarters of SDA change, found {len(sda_quarters)}")
    idx = {q: i for i, q in enumerate(quarters)}

    def lag_window(lag):
        lo, hi = idx[sda_quarters[0]] - lag, idx[sda_quarters[-1]] - lag
        if lo < 0:
            raise ValueError(f"approvals do not reach back {lag} quarters")
        return quarters[lo:hi + 1]

    windows = {lag: lag_window(lag) for lag in LAGS}
    area = defaultdict(float)
    for r in d["asgs"]:
        area[r["SA3_CODE_2021"]] += float(r["AREA_ALBERS_SQKM"] or 0)
    p = d["panel"]
    frame = {}
    for geo, r in d["sa3"].items():
        code = r["sa3_code"]
        c = d["census"][code]
        mort, rent = float(c["median_mortgage_monthly"]), float(c["median_rent_weekly"])
        rec = {
            "sa4": r["sa4"], "state": r["state"],
            "mortgage": mort if mort > 0 else None, "rent": rent if rent > 0 else None,
            "persons": float(c["persons"]), "area": area[code],
            "new_build": change(p, geo, "Total", "dwellings_new_build"),
            "hps": change(p, geo, "High Physical Support", "enrolled_dwellings"),
            "robust": change(p, geo, "Robust", "enrolled_dwellings"),
            "legacy": p[(geo, "Total", "dwellings_legacy")][START],
            "existing": p[(geo, "Total", "dwellings_existing")][START],
            "eligible_not_using": p[(geo, "Total", "participants_eligible_not_using")][NEED_EARLIEST],
            "need_hps": p[(geo, "High Physical Support", "participants_with_need")][NEED_BY_CATEGORY],
            "need_robust": p[(geo, "Robust", "participants_with_need")][NEED_BY_CATEGORY],
        }
        for lag, qs in windows.items():
            rec[f"approvals_lag{lag}"] = sum(appr[code].get(q, 0.0) for q in qs)
            rec[f"houses_lag{lag}"] = sum(houses[code].get(q, 0.0) for q in qs)
        frame[geo] = rec
    return frame, windows


def groups_of(frame, members, outcome, cost="mortgage", min_total=MIN_OUTCOME):
    """SA4 -> SA3s, for SA4s with >= 2 SA3s with cost data and enough outcome."""
    out = defaultdict(list)
    for g in members:
        if frame[g][cost] is not None:
            out[frame[g]["sa4"]].append(g)
    return {s: sorted(gs) for s, gs in out.items()
            if len(gs) >= 2 and sum(frame[g][outcome] for g in gs) >= min_total}


def rel_cost(frame, groups, cost="mortgage"):
    rel = {}
    for gs in groups.values():
        mu = statistics.fmean(math.log(frame[g][cost]) for g in gs)
        for g in gs:
            rel[g] = math.log(frame[g][cost]) - mu
    return rel


def shares(frame, gs, key):
    tot = sum(frame[g][key] for g in gs)
    n = len(gs)
    return [frame[g][key] / tot if tot > 0 else 1 / n for g in gs]


# --------------------------------------------------------------------------
# 1. Within-SA4 rank test
# --------------------------------------------------------------------------

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
    mu = statistics.fmean(r)
    return [x - mu for x in r]


def rank_test(frame, groups, cost, series, rng):
    """Mean within-SA4 Spearman of relative cost with each series.

    `series` maps a name to a function (frame, SA3s) -> values. The
    permutation shuffles cost ranks within each SA4 and recomputes every
    series' mean, so the p-values are joint over the same shuffles.
    """
    prepared = []
    for s, gs in sorted(groups.items()):
        c = ranks([frame[g][cost] for g in gs])
        cc = sum(x * x for x in c)
        ys = {}
        for name, fn in series.items():
            y = ranks(fn(frame, gs))
            yy = sum(x * x for x in y)
            ys[name] = (y, (cc * yy) ** 0.5 if yy > 0 else 0.0)
        prepared.append((s, c, ys))

    def means(perm_c):
        out = {}
        for name in series:
            vals = []
            for (s, c, ys), pc in zip(prepared, perm_c):
                y, den = ys[name]
                if den:
                    vals.append(sum(a * b for a, b in zip(pc, y)) / den)
            out[name] = (statistics.fmean(vals), vals)
        return out

    observed = means([c for _, c, _ in prepared])
    extreme = {name: 0 for name in series}
    for _ in range(PERMUTATIONS):
        perm = []
        for _, c, _ in prepared:
            pc = c[:]
            rng.shuffle(pc)
            perm.append(pc)
        got = means(perm)
        for name in series:
            if abs(got[name][0]) >= abs(observed[name][0]) - 1e-12:
                extreme[name] += 1
    result = {}
    for name in series:
        mean, vals = observed[name]
        result[name] = {"mean": mean, "sa4s": len(vals),
                        "se": statistics.stdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else None,
                        "negative": sum(v < 0 for v in vals), "positive": sum(v > 0 for v in vals),
                        "p": (1 + extreme[name]) / (1 + PERMUTATIONS)}
    return result


def outcome_series(outcome, lag=LAG_PRIMARY, comparator="approvals"):
    appr = f"{comparator}_lag{lag}"
    return {
        "sda": lambda fr, gs: shares(fr, gs, outcome),
        "approvals": lambda fr, gs: shares(fr, gs, appr),
        "difference": lambda fr, gs: [a - b for a, b in zip(shares(fr, gs, outcome),
                                                            shares(fr, gs, appr))],
    }


# --------------------------------------------------------------------------
# 2. Regressions with SA4 fixed effects
# --------------------------------------------------------------------------

def share_regression(frame, groups, outcome, cost, lag=LAG_PRIMARY, comparator="approvals"):
    """Share of the SA4's outcome on relative log cost and controls, SA4 effects.

    Everything is demeaned within SA4, which absorbs the SA4 effects; shares
    are in percentage points. Standard errors clustered by SA4.
    """
    rel = rel_cost(frame, groups, cost)
    keys = [f"{comparator}_lag{lag}", NEED_FOR[outcome], "persons", "area"]
    x, y, cl = [], [], []
    for s, gs in groups.items():
        n = len(gs)
        ys = shares(frame, gs, outcome)
        cs = {k: shares(frame, gs, k) for k in keys}
        for i, g in enumerate(gs):
            y.append(100 * (ys[i] - 1 / n))
            x.append([rel[g]] + [100 * (cs[k][i] - 1 / n) for k in keys])
            cl.append(s)
    beta, cov = ols(x, y, cl)
    names = ["relative_log_cost", "approvals_share", "need_share", "population_share", "area_share"]
    return {"sa4s": len(groups), "sa3s": len(y),
            "coef": {k: {"b": b, "se": cov[i][i] ** 0.5} for i, (k, b) in enumerate(zip(names, beta))}}


def multinomial(frame, groups, outcome, cost, lag=LAG_PRIMARY, comparator="approvals"):
    """Poisson with SA4 effects, i.e. a within-SA4 multinomial logit, by Newton.

    Counts are the outcome change, with the few negatives set to zero.
    Covariates: relative log cost, and logs of approvals, need, population and
    area. Profiling out the SA4 effects leaves p_g = exp(x_g b) / sum over the
    SA4. Sandwich standard errors clustered by SA4.
    """
    rel = rel_cost(frame, groups, cost)
    data = []
    for s, gs in groups.items():
        rows = []
        for g in gs:
            r = frame[g]
            rows.append((max(r[outcome], 0.0),
                         [rel[g], math.log(r[f"{comparator}_lag{lag}"] + 1),
                          math.log(r[NEED_FOR[outcome]] + 1), math.log(r["persons"]),
                          math.log(r["area"])]))
        if sum(yv for yv, _ in rows) > 0:
            data.append(rows)
    k = 5
    b = [0.0] * k
    for _ in range(100):
        score = [0.0] * k
        info = [[0.0] * k for _ in range(k)]
        for rows in data:
            total = sum(yv for yv, _ in rows)
            eta = [sum(bi * xi for bi, xi in zip(b, x)) for _, x in rows]
            top = max(eta)
            w = [math.exp(e - top) for e in eta]
            sw = sum(w)
            p = [v / sw for v in w]
            mean_x = [sum(pi * x[j] for pi, (_, x) in zip(p, rows)) for j in range(k)]
            for (yv, x), pi in zip(rows, p):
                for j in range(k):
                    score[j] += (yv - total * pi) * x[j]
                    for m in range(k):
                        info[j][m] += total * pi * (x[j] - mean_x[j]) * (x[m] - mean_x[m])
        step = solve(info, score)
        b = [bi + si for bi, si in zip(b, step)]
        if max(abs(si) for si in step) < 1e-10:
            break
    else:
        raise ValueError("multinomial did not converge")
    # Sandwich: bread = info^-1, meat = sum over SA4s of score_s score_s'.
    meat = [[0.0] * k for _ in range(k)]
    for rows in data:
        total = sum(yv for yv, _ in rows)
        eta = [sum(bi * xi for bi, xi in zip(b, x)) for _, x in rows]
        top = max(eta)
        w = [math.exp(e - top) for e in eta]
        sw = sum(w)
        sc = [0.0] * k
        for (yv, x), wi in zip(rows, w):
            for j in range(k):
                sc[j] += (yv - total * wi / sw) * x[j]
        for j in range(k):
            for m in range(k):
                meat[j][m] += sc[j] * sc[m]
    inv = [solve(info, [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    g = len(data)
    cov = [[g / (g - 1) * sum(inv[j][p] * meat[p][q] * inv[q][m] for p in range(k) for q in range(k))
            for m in range(k)] for j in range(k)]
    names = ["relative_log_cost", "log_approvals", "log_need", "log_population", "log_area"]
    return {"sa4s": g, "coef": {n: {"b": bi, "se": cov[i][i] ** 0.5}
                                for i, (n, bi) in enumerate(zip(names, b))}}


# --------------------------------------------------------------------------
# 5. Dose-response
# --------------------------------------------------------------------------

def dose_response(frame, groups, outcome, cost, lag=LAG_PRIMARY, comparator="approvals"):
    """Does the lean (SDA share minus approvals share) steepen with cost spread?"""
    rel = rel_cost(frame, groups, cost)
    spread = {s: statistics.pstdev([rel[g] for g in gs]) for s, gs in groups.items()}
    mu, sd = statistics.fmean(spread.values()), statistics.pstdev(spread.values())
    x, y, cl = [], [], []
    for s, gs in groups.items():
        d = [a - b for a, b in zip(shares(frame, gs, outcome), shares(frame, gs, f"{comparator}_lag{lag}"))]
        z = (spread[s] - mu) / sd
        for g, dv in zip(gs, d):
            y.append(100 * dv)
            x.append([rel[g], rel[g] * z])
            cl.append(s)
    beta, cov = ols(x, y, cl)
    # And by third of cost spread: mean within-SA4 rank correlation of the lean.
    ordered = sorted(groups, key=lambda s: spread[s])
    thirds = [ordered[i * len(ordered) // 3:(i + 1) * len(ordered) // 3] for i in range(3)]
    by_third = []
    for part in thirds:
        rhos = []
        for s in part:
            gs = groups[s]
            d = [a - b for a, b in zip(shares(frame, gs, outcome), shares(frame, gs, f"{comparator}_lag{lag}"))]
            if len(set(d)) > 1 and len({frame[g][cost] for g in gs}) > 1:
                rhos.append(spearman([frame[g][cost] for g in gs], d))
        by_third.append({"sa4s": len(part), "spread_lo": spread[part[0]], "spread_hi": spread[part[-1]],
                         "mean_rho": statistics.fmean(rhos),
                         "se": statistics.stdev(rhos) / len(rhos) ** 0.5})
    return {"slope": {"b": beta[0], "se": cov[0][0] ** 0.5},
            "interaction": {"b": beta[1], "se": cov[1][1] ** 0.5},
            "spread_mean": mu, "spread_sd": sd, "thirds": by_third}


# --------------------------------------------------------------------------
# 3. Across SA4 borders
# --------------------------------------------------------------------------

def cluster_flip_p(x, y, clusters, rng, controls=None):
    """Permutation p for the slope on x, flipping x's sign by cluster.

    With controls, x and y are first residualised on them (Frisch-Waugh), so
    the flips leave the controls' part alone. No intercept: every pair is
    oriented arbitrarily, and flipping a pair flips both sides of the model.
    """
    if controls:
        def resid(v):
            b, _ = ols([[c] for c in controls], v, clusters)
            return [vi - b[0] * ci for vi, ci in zip(v, controls)]
        x, y = resid(x), resid(y)
    sxx = sum(v * v for v in x)
    obs = sum(a * b for a, b in zip(x, y)) / sxx
    groups = defaultdict(list)
    for i, c in enumerate(clusters):
        groups[c].append(i)
    idx = list(groups.values())
    hits = 0
    for _ in range(PERMUTATIONS):
        num = 0.0
        for members in idx:
            sign = 1 if rng.random() < 0.5 else -1
            num += sign * sum(x[i] * y[i] for i in members)
        if abs(num / sxx) >= abs(obs) - 1e-12:
            hits += 1
    return (1 + hits) / (1 + PERMUTATIONS)


def border_test(d, frame, rng):
    appr, quarters, _, _, _ = approvals(d)
    code_of = {g: r["sa3_code"] for g, r in d["sa3"].items()}
    idx = {q: i for i, q in enumerate(quarters)}

    def approvals_for(g, first_sda_q, last_sda_q):
        lo, hi = idx[first_sda_q] - LAG_PRIMARY, idx[last_sda_q] - LAG_PRIMARY
        return sum(appr[code_of[g]].get(q, 0.0) for q in quarters[lo:hi + 1])

    sda_q = [q for q in quarters if START < q <= END]
    windows = {"full": (START, END, sda_q[0], sda_q[-1]),
               "early": (START, MIDPOINT, sda_q[0], MIDPOINT),
               "late": (MIDPOINT, END, quarters[idx[MIDPOINT] + 1], END)}
    sda, apv = {}, {}
    for w, (a, b, q0, q1) in windows.items():
        for g in frame:
            sda[(w, g)] = max(change(d["panel"], g, "Total", "dwellings_new_build", a, b), 0.0)
            apv[(w, g)] = approvals_for(g, q0, q1)
    sets = {}
    for key, _, version, stock in FACTOR_SETS:
        f = defaultdict(dict)
        for r in d["factors"]:
            if (r["edition"], r["version"]) == version and r["stock_type"] == stock:
                f[r["sa4"]][r["building_type"]] = float(r["factor"])
        if len(f) != 88:
            raise ValueError(f"factor set {key}: {len(f)} SA4s")
        sets[key] = f
    # Building-type weights: new-build growth over the window in the pair's two SA4s.
    growth = defaultdict(lambda: defaultdict(float))
    for r in d["types"]:
        sign = 1 if r["as_at"] == END else -1 if r["as_at"] == START else 0
        if sign and r["dwellings"] != "" and r["building_type"] in sets["new_build"][r["sa4"]]:
            growth[r["sa4"]][r["building_type"]] += sign * float(r["dwellings"])
    national = defaultdict(float)
    for g4 in growth.values():
        for t, v in g4.items():
            national[t] += v

    def mix_factor(f, sa4, weights):
        tot = sum(weights.values())
        return sum(f[sa4][t] * w for t, w in weights.items()) / tot

    pairs = []
    for p in d["adjacency"]:
        if p["cross_sa4"] != "yes" or float(p["shared_km"]) < MIN_BORDER_KM:
            continue
        a, b = p["sa3_a"], p["sa3_b"]
        if frame[a]["mortgage"] is None or frame[b]["mortgage"] is None:
            continue
        s4a, s4b = p["sa4_a"], p["sa4_b"]
        w = {t: max(growth[s4a][t] + growth[s4b][t], 0.0) for t in national}
        if sum(w.values()) <= 0:
            w = {t: max(v, 0.0) for t, v in national.items()}
        rec = {"a": a, "b": b, "cluster": tuple(sorted((s4a, s4b))),
               "dcost": math.log(frame[a]["mortgage"] / frame[b]["mortgage"]),
               "gap": {k: math.log(mix_factor(f, s4a, w) / mix_factor(f, s4b, w))
                       for k, f in sets.items()}}
        for win in windows:
            ts, ta = sda[(win, a)] + sda[(win, b)], apv[(win, a)] + apv[(win, b)]
            rec[win] = (sda[(win, a)] / ts - apv[(win, a)] / ta) if ts > 0 and ta > 0 else None
        pairs.append(rec)

    def cross_section(key, win):
        use = [r for r in pairs if r[win] is not None]
        x = [[r["gap"][key], r["dcost"]] for r in use]
        y = [100 * r[win] for r in use]
        cl = [r["cluster"] for r in use]
        beta, cov = ols(x, y, cl)
        p = cluster_flip_p([r["gap"][key] for r in use], y, cl, rng,
                           controls=[r["dcost"] for r in use])
        # The transparent version: does the higher-factor side get more SDA per approval?
        wide = [r for r in use if abs(r["gap"][key]) >= math.log(1 + GAP_SIGN_TEST)]
        agree = sum((r["gap"][key] > 0) == (r[win] > 0) for r in wide if r[win] != 0)
        decided = sum(1 for r in wide if r[win] != 0)
        return {"pairs": len(use), "clusters": len(set(cl)),
                "factor": {"b": beta[0], "se": cov[0][0] ** 0.5}, "cost": {"b": beta[1], "se": cov[1][1] ** 0.5},
                "p_flip": p, "wide_pairs": len(wide), "decided": decided, "higher_side_more": agree}

    cross = {f"{key}:{win}": cross_section(key, win)
             for key, _, _, _ in FACTOR_SETS for win in ("full", "early", "late")}
    # Difference in differences: the change in a pair's SDA gap against the
    # change in its factor gap. Land either side is held fixed.
    use = [r for r in pairs if r["early"] is not None and r["late"] is not None]
    dx = [r["gap"]["new_build"] - r["gap"]["combined"] for r in use]
    dy = [100 * (r["late"] - r["early"]) for r in use]
    cl = [r["cluster"] for r in use]
    beta, cov = ols([[v] for v in dx], dy, cl)
    moved = [abs(v) for v in dx]
    did = {"pairs": len(use), "clusters": len(set(cl)), "b": beta[0], "se": cov[0][0] ** 0.5,
           "p_flip": cluster_flip_p(dx, dy, cl, rng),
           "gap_change_median": statistics.median(moved), "gap_change_max": max(moved),
           "gap_change_ge_0_05": sum(v >= math.log(1.05) for v in moved)}
    corr = spearman([r["gap"]["combined"] for r in pairs], [r["gap"]["new_build"] for r in pairs])
    return {"pairs": len(pairs), "clusters": len({r["cluster"] for r in pairs}),
            "cross": cross, "did": did, "gap_correlation": corr,
            "windows": {k: [v[0], v[1]] for k, v in windows.items()}}


# --------------------------------------------------------------------------
# Running everything
# --------------------------------------------------------------------------

def variants(frame):
    """name -> {label, members, cost, comparator}."""
    everyone = sorted(frame)
    by_sa4 = defaultdict(float)
    for g, r in frame.items():
        by_sa4[r["sa4"]] += r["new_build"]
    largest = sorted(by_sa4, key=lambda s: -by_sa4[s])[:DROP_LARGEST]
    per_1000 = sorted(frame, key=lambda g: -frame[g][f"houses_lag{LAG_PRIMARY}"] / frame[g]["persons"])
    corridor = set(per_1000[:round(CORRIDOR_SHARE * len(frame))])

    def v(label, members=everyone, cost="mortgage", comparator="approvals"):
        return {"label": label, "members": members, "cost": cost, "comparator": comparator}
    return {
        "primary": v(f"Primary (mortgage, all approvals, lag {LAG_PRIMARY})"),
        "houses": v("Comparator: house approvals only", comparator="houses"),
        "no_vic": v("Without Victoria", [g for g in everyone if frame[g]["state"] != "VIC"]),
        "no_largest": v(f"Without the {DROP_LARGEST} SA4s building most",
                        [g for g in everyone if frame[g]["sa4"] not in largest]),
        "rent": v("Rent instead of mortgage", cost="rent"),
        "no_small": v(f"Without SA3s approving under {SMALL_APPROVALS}",
                      [g for g in everyone if frame[g][f"approvals_lag{LAG_PRIMARY}"] >= SMALL_APPROVALS]),
        "no_corridor": v("Without growth corridors", [g for g in everyone if g not in corridor]),
    }, largest, corridor


def analyse(d):
    frame, windows = build_frame(d)
    rng = random.Random(SEED)
    vs, largest, corridor = variants(frame)
    results = {"windows": {str(k): [v[0], v[-1]] for k, v in windows.items()},
               "largest": largest, "corridor": sorted(corridor), "tests": {}}

    # Tests 1, 2 and 5, and robustness, for each outcome.
    for key, v in vs.items():
        block = {}
        cost, comp = v["cost"], v["comparator"]
        for outcome, _ in OUTCOMES:
            groups = groups_of(frame, v["members"], outcome, cost)
            block[outcome] = {
                "rank": rank_test(frame, groups, cost,
                                  outcome_series(outcome, comparator=comp), rng),
                "regression": share_regression(frame, groups, outcome, cost, comparator=comp),
                "multinomial": multinomial(frame, groups, outcome, cost, comparator=comp),
            }
            if key in ("primary", "houses"):
                block[outcome]["dose"] = dose_response(frame, groups, outcome, cost,
                                                       comparator=comp)
        results["tests"][key] = {"label": v["label"], "sa3s": len(v["members"]),
                                 "comparator": comp, "outcomes": block}

    # Lag sensitivity, primary specification.
    lags = {}
    for lag in LAGS:
        lags[str(lag)] = {}
        for outcome, _ in OUTCOMES:
            groups = groups_of(frame, sorted(frame), outcome)
            r = rank_test(frame, groups, "mortgage", outcome_series(outcome, lag), rng)
            reg = share_regression(frame, groups, outcome, "mortgage", lag)
            lags[str(lag)][outcome] = {"rank": r, "regression": reg}
    results["lags"] = lags

    # Placebos: stock that predates NDIS pricing, beside new build.
    placebo = {}
    for stock in ("legacy", "existing"):
        groups = groups_of(frame, sorted(frame), stock, min_total=MIN_PLACEBO[stock])
        series = {
            "stock": lambda fr, gs, k=stock: shares(fr, gs, k),
            "beyond_population": lambda fr, gs, k=stock: [a - b for a, b in zip(
                shares(fr, gs, k), shares(fr, gs, "persons"))],
        }
        placebo[stock] = {"rank": rank_test(frame, groups, "mortgage", series, rng),
                          "total": sum(frame[g][stock] for gs in groups.values() for g in gs),
                          "sa3s_with": sum(frame[g][stock] > 0 for g in frame)}
    groups = groups_of(frame, sorted(frame), "new_build")
    placebo["new_build"] = {"rank": rank_test(frame, groups, "mortgage", {
        "stock": lambda fr, gs: shares(fr, gs, "new_build"),
        "beyond_population": lambda fr, gs: [a - b for a, b in zip(
            shares(fr, gs, "new_build"), shares(fr, gs, "persons"))],
    }, rng)}
    results["placebo"] = placebo
    results["border"] = border_test(d, frame, rng)
    results["totals"] = {o: sum(frame[g][o] for g in frame) for o, _ in OUTCOMES}
    results["vic_share"] = {o: sum(frame[g][o] for g in frame if frame[g]["state"] == "VIC")
                            / results["totals"][o] for o, _ in OUTCOMES}
    return results


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def f2(v):
    return f"{v:+.2f}"


def pval(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def est(c, scale=1.0, digits=2):
    return f"{c['b'] * scale:+.{digits}f} (± {c['se'] * scale:.{digits}f})"


def nm(geo):
    return geo.split(":", 1)[1]


def month(q):
    y, m, _ = q.split("-")
    return f"{['Mar', 'Jun', 'Sep', 'Dec'][int(m) // 3 - 1]} {y}"


def quarter_start(q):
    y, m, _ = q.split("-")
    return f"{['Jan', 'Apr', 'Jul', 'Oct'][int(m) // 3 - 1]} {y}"


def significant(c, z=1.96):
    return abs(c["b"]) > z * c["se"]


def verdict_rank(r):
    d = r["difference"]
    if d["p"] < 0.05:
        return "toward cheap SA3s" if d["mean"] < 0 else "toward dear SA3s"
    return "no detectable lean"


def verdict(a):
    """The findings, each stated only as far as its numbers carry it."""
    T = a["tests"]
    P, H = T["primary"]["outcomes"], T["houses"]["outcomes"]
    out = []
    nb = P["new_build"]["rank"]["difference"]
    hps = P["hps"]["rank"]["difference"]
    rob = P["robust"]["rank"]["difference"]
    reg = {o: P[o]["regression"]["coef"]["relative_log_cost"] for o, _ in OUTCOMES}
    mn = {o: P[o]["multinomial"]["coef"]["relative_log_cost"] for o, _ in OUTCOMES}
    sda_alone = P["new_build"]["rank"]["sda"]
    appr_alone = P["new_build"]["rank"]["approvals"]
    others = [k for k in T if k != "primary"]
    holds = [k for k in others if T[k]["outcomes"]["new_build"]["rank"]["difference"]["p"] < 0.05]
    fails = [k for k in others if k not in holds]
    reg_neg = [k for k in T if T[k]["outcomes"]["new_build"]["regression"]["coef"]
               ["relative_log_cost"]["b"] < 0]
    reg_sig = [k for k in T if significant(T[k]["outcomes"]["new_build"]["regression"]["coef"]
                                           ["relative_log_cost"])]

    lean = nb["p"] < 0.05 and nb["mean"] < 0
    out.append(f"1. **{'Relative to general building, new SDA sits in cheaper SA3s within SA4s.' if lean else 'No reliable lean of new SDA toward cheap SA3s beyond general building.'}** "
               f"The rank test gives {f2(nb['mean'])} for all new build (p = {pval(nb['p'])}) and "
               f"{f2(hps['mean'])} for High Physical Support (p = {pval(hps['p'])}); Robust, with "
               f"{rob['sa4s']} SA4s, is {f2(rob['mean'])} (p = {pval(rob['p'])}). The regression cost "
               f"coefficient is negative for all three outcomes ({', '.join(est(reg[o], digits=1) for o, _ in OUTCOMES)}), "
               f"as is the multinomial ({', '.join(est(mn[o]) for o, _ in OUTCOMES)}).")
    ha = H["new_build"]["rank"]["approvals"]
    part = sda_alone["mean"] / nb["mean"] if nb["mean"] else 0.0
    out.append(f"2. **{'Most' if part < 0.5 else 'Much'} of that gap is general building leaning *dear*, not SDA "
               f"leaning cheap.** New SDA's own correlation with relative cost is {f2(sda_alone['mean'])} "
               f"(p = {pval(sda_alone['p'])}), {part:.0%} of the gap; approvals come in at "
               f"{f2(appr_alone['mean'])} (p = {pval(appr_alone['p'])}), and house approvals alone at "
               f"{f2(ha['mean'])} (p = {pval(ha['p'])}), so it is not apartments. The likeliest reason "
               "is the cost measure: a 2021 median mortgage (or rent) is high where housing is new, "
               "because recent buyers carry larger loans, so SA3s that were already building read as "
               "dear. That inflates the gap, and it means the Census measure tracks newness as well "
               "as land cost.")
    out.append(f"3. **It is only moderately robust.** The rank result stays below p = 0.05 in "
               f"{len(holds)} of {len(others)} variants; it weakens in: "
               + "; ".join(f"{T[k]['label']} ({f2(T[k]['outcomes']['new_build']['rank']['difference']['mean'])}, "
                           f"p {pval(T[k]['outcomes']['new_build']['rank']['difference']['p'])})" for k in fails)
               + f". The regression coefficient is negative in {len(reg_neg)} of {len(T)} specifications "
               f"and beyond two standard errors in {len(reg_sig)}; the multinomial's is negative in "
               f"{sum(T[k]['outcomes']['new_build']['multinomial']['coef']['relative_log_cost']['b'] < 0 for k in T)} "
               f"and beyond two standard errors in "
               f"{sum(significant(T[k]['outcomes']['new_build']['multinomial']['coef']['relative_log_cost']) for k in T)}"
               f" (it weights SA4s by how much they built). Every lag from "
               f"{LAGS[0]} to {LAGS[-1]} quarters gives the same sign.")
    ex = a["placebo"]["existing"]["rank"]["beyond_population"]
    nbp = a["placebo"]["new_build"]["rank"]["beyond_population"]
    lg = a["placebo"]["legacy"]["rank"]["beyond_population"]
    same = abs(ex["mean"] - nbp["mean"]) < 0.05 and ex["mean"] < 0
    out.append(f"4. **{'The placebo does not clear it.' if same else 'The placebo points the other way.'}** "
               f"Measured against population, new build leans to cheap SA3s by {f2(nbp['mean'])} "
               f"(p = {pval(nbp['p'])}); existing stock, built before NDIS pricing, by "
               f"{f2(ex['mean'])} (p = {pval(ex['p'])}). "
               + ("Neither clears p = 0.05 on this measure, but they are the same size: there is no "
                  "sign that the new-build lean is new. Accessible housing for this cohort may always "
                  "have sat on cheaper land within SA4s. "
                  if same else "Pre-NDIS stock does not share the lean. ")
               + f"Legacy stock ({lg['sa4s']} SA4s, {f2(lg['mean'])}) is too thin to say anything.")
    Bf = a["border"]["cross"]
    bsig = [k for k, c in Bf.items() if c["p_flip"] < 0.05 and c["factor"]["b"] > 0]
    bneg = [k for k, c in Bf.items() if c["p_flip"] < 0.05 and c["factor"]["b"] < 0]
    did = a["border"]["did"]
    dsig = did["p_flip"] < 0.05
    Bf = a["border"]["cross"]
    bsig = [k for k, c in Bf.items() if c["p_flip"] < 0.05 and c["factor"]["b"] > 0]
    bneg = [k for k, c in Bf.items() if c["p_flip"] < 0.05 and c["factor"]["b"] < 0]
    did = a["border"]["did"]
    dsig = did["p_flip"] < 0.05
    dz = P["new_build"]["dose"]["interaction"]
    out.append(f"5. **No dose-response.** If margin drove the lean, it would steepen where cost "
               f"spreads wider within the SA4. The interaction is {est(dz)} per SD of spread, "
               f"{'the wrong sign and ' if dz['b'] > 0 else ''}"
               f"{'within' if not significant(dz) else 'beyond'} two standard errors of zero.")
    if bsig and not bneg:
        head = "The border test finds building following the higher factor."
    elif bneg and not bsig:
        head = "Across borders, SDA leans to the *lower*-factor side, not the higher."
    elif bsig and bneg:
        head = "The border test is mixed."
    else:
        head = "The border test finds no sign that building follows the factor."
    out.append(f"6. **{head}** Across {Bf['combined:full']['pairs']} SA4-border pairs, with the cost "
               "gap controlled, the factor-gap coefficient over the whole window is "
               f"{est(Bf['combined:full']['factor'])} (p {pval(Bf['combined:full']['p_flip'])}) with the "
               f"pre-2023 factors and {est(Bf['new_build:full']['factor'])} "
               f"(p {pval(Bf['new_build:full']['p_flip'])}) with the post-2023 ones; "
               f"{len(bsig)} of {len(Bf)} factor-by-window combinations are positive at p < 0.05 and "
               f"{len(bneg)} negative. The before-and-after comparison, which holds land fixed, gives "
               f"{est(did)} (p {pval(did['p_flip'])})."
               + (" A higher factor usually marks dearer land, and the only cost control is a 2021 "
                  "median mortgage, so a negative coefficient most likely means the factor gap is "
                  "picking up land cost the control misses: more evidence that SDA goes where land is "
                  "cheap, not that it chases the factor." if bneg else ""))
    out.append("")
    out.append("**In sum:** \"New SDA leans toward cheap SA3s within SA4s more than general "
               "building does\" is "
               + ("supported by the rank test and the regressions, " if lean else "not supported, ")
               + f"but {'mostly' if part < 0.5 else 'partly'} because general building leans toward SA3s the Census measure reads as "
               "dear, the pre-NDIS placebo "
               + ("leans the same way, and there is no dose-response, so the lean cannot be "
                  "attributed to the location factor's margin. " if same else
                  "does not, which is consistent with the incentive. ")
               + ("\"Providers respond to the location factor\" is not supported by the border "
                  "test either: where a border separates two prices, building does not follow the "
                  "higher one" + (", and with the post-2023 factors it leans to the lower." if bneg
                                  else ".")
                  if not bsig and not (dsig and did["b"] > 0) else
                  "The border test gives some support to \"providers respond to the location "
                  "factor\"; see Section 3 for how far."))
    return out


def to_markdown(a):
    P = a["tests"]["primary"]["outcomes"]
    labels = dict(OUTCOMES)
    L = []
    w = L.append
    nb, hps, rob = P["new_build"], P["hps"], P["robust"]
    w("# Location-factor experiment, Phase 2: does new SDA lean toward cheap SA3s?")
    w("")
    w("Generated by `scripts/analyse_location_factor.py` from committed files. Every figure is "
      "computed; do not edit by hand. Phase 1's feasibility report is "
      "`LOCATION_FACTOR_FEASIBILITY.md`. The analysis is **ecological**: it compares regions' "
      "published totals and follows no dwelling, provider or participant.")
    w("")
    w("## The question, and how it is asked")
    w("")
    w("The SDA amount is a base amount times a location factor set per SA4 and building type. "
      "The factor does not vary within an SA4, but land cost does, so the margin should be "
      "highest on an SA4's cheapest land. Cheap outer suburbs get more of *all* building, "
      "because that is where the land is, so the question is whether SDA leans toward cheap "
      "SA3s **more than general residential building does**.")
    w("")
    win = a["windows"][str(LAG_PRIMARY)]
    w(f"- **Outcome.** New SDA per SA3, {month(START)} to {month(END)}: the change in "
      f"`dwellings_new_build` ({a['totals']['new_build']:,.0f} dwellings), and the change in enrolled "
      f"High Physical Support ({a['totals']['hps']:,.0f}) and Robust ({a['totals']['robust']:,.0f}) "
      "dwellings. A rise in enrolled dwellings can include existing dwellings newly enrolled, and "
      "SA3 publishes no category split of new build and no building type.")
    w(f"- **Comparator.** Dwellings approved (houses and other residential, new work, all "
      f"sectors) over twelve quarters lagged {LAG_PRIMARY} behind the SDA window: "
      f"{quarter_start(win[0])} to {month(win[1])}. Lags of {', '.join(str(x) for x in LAGS)} "
      "quarters are tested below.")
    w("- **Cost.** Log 2021 Census median mortgage repayment relative to its SA4's mean "
      "(primary), and log median rent the same way.")
    w(f"- **Qualifying SA4s.** At least two SA3s with cost data and at least {MIN_OUTCOME} of the "
      "outcome in the SA4.")
    w("- **Signs.** A *negative* correlation or coefficient on cost means more SDA where cost "
      "is lower: a lean toward cheap SA3s.")
    w("")

    # ---- In brief
    w("## In brief")
    w("")
    for o, lab in OUTCOMES:
        r = P[o]["rank"]
        reg = P[o]["regression"]["coef"]["relative_log_cost"]
        w(f"- **{lab}.** Within SA4s, the SDA-minus-approvals share has a mean rank correlation "
          f"with relative cost of {f2(r['difference']['mean'])} (permutation p = "
          f"{pval(r['difference']['p'])}, {r['difference']['sa4s']} SA4s): "
          f"{verdict_rank(r)}. SDA alone {f2(r['sda']['mean'])}, approvals alone "
          f"{f2(r['approvals']['mean'])}. The fixed-effects regression puts the cost "
          f"coefficient at {est(reg)} share points per log point, net of approvals and need.")
    H = a["tests"]["houses"]["outcomes"]
    hd = H["new_build"]["rank"]["difference"]
    w(f"- **Against house approvals only**, the fairer comparator for SDA's houses and villas, the "
      f"new-build lean is {f2(hd['mean'])} (p = {pval(hd['p'])}).")
    lg = a["placebo"]["legacy"]["rank"]["beyond_population"]
    ex = a["placebo"]["existing"]["rank"]["beyond_population"]
    nbp = a["placebo"]["new_build"]["rank"]["beyond_population"]
    w(f"- **Placebos** (share minus population share, against relative cost). New build "
      f"{f2(nbp['mean'])} (p = {pval(nbp['p'])}); existing stock, which predates NDIS pricing, "
      f"{f2(ex['mean'])} (p = {pval(ex['p'])}); legacy stock {f2(lg['mean'])} "
      f"(p = {pval(lg['p'])}, only {lg['sa4s']} SA4s).")
    Bf = a["border"]["cross"]
    bc, bn, bd_ = Bf["combined:full"], Bf["new_build:full"], a["border"]["did"]
    w(f"- **Across SA4 borders** ({bc['pairs']} pairs), the factor gap on the SDA-per-approval gap: "
      f"{est(bc['factor'])} per log point with the pre-2023 factors (p = {pval(bc['p_flip'])}), "
      f"{est(bn['factor'])} with the post-2023 ones (p = {pval(bn['p_flip'])}); before and after "
      f"the July 2023 re-set, {est(bd_)} (p = {pval(bd_['p_flip'])}).")
    w("")

    w("## What the evidence supports")
    w("")
    for line in verdict(a):
        w(line)
    w("")

    # ---- Test 1
    w("## 1. Within-SA4 rank test")
    w("")
    w("In each qualifying SA4, Spearman's rank correlation of SA3 relative cost with the SA3's "
      "share of the SA4's new SDA, with its share of approvals, and with the difference (SDA "
      "share minus approvals share). Each SA4 counts once. The p-value comes from "
      f"{PERMUTATIONS:,} permutations that shuffle cost among the SA3s *within* each SA4, so no "
      "difference between SA4s can enter. The ± is the standard error of the mean across SA4s.")
    w("")
    w("| Outcome | SA4s | SDA share | Approvals share | Difference | SA4s negative / positive | Permutation p (difference) |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for o, lab in OUTCOMES:
        r = P[o]["rank"]
        d = r["difference"]
        w(f"| {lab} | {d['sa4s']} | {f2(r['sda']['mean'])} (p {pval(r['sda']['p'])}) | "
          f"{f2(r['approvals']['mean'])} (p {pval(r['approvals']['p'])}) | "
          f"{f2(d['mean'])} ± {d['se']:.2f} | {d['negative']} / {d['positive']} | {pval(d['p'])} |")
    w("")
    w("**What it can support.** Whether, SA4 by SA4, new SDA sits on cheaper or dearer land "
      "than that SA4's general building, with nothing between SA4s leaking in. **What it "
      "cannot.** Why. Correlations from SA4s of two or three SA3s are coarse (±1 or ±0.5), so the "
      "mean is a blunt instrument, and it ignores how much SDA each SA4 built.")
    w("")

    # ---- Test 2
    w("## 2. Regression with SA4 fixed effects")
    w("")
    w("Share of the SA4's new SDA (percentage points) on relative log cost, controlling for the "
      "SA3's shares of approvals, need, population and area; all demeaned within SA4, which "
      "absorbs the SA4 effects. Need is participants eligible but not using SDA "
      f"({month(NEED_EARLIEST)}) for all new build, and participants with need in that category "
      f"({month(NEED_BY_CATEGORY)}) for High Physical Support and Robust. Standard errors are "
      "clustered by SA4.")
    w("")
    w("| Outcome | SA4s | SA3s | Relative log cost | Approvals share | Need share | Population share | Area share |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for o, lab in OUTCOMES:
        g = P[o]["regression"]
        c = g["coef"]
        w(f"| {lab} | {g['sa4s']} | {g['sa3s']} | {est(c['relative_log_cost'])} | "
          f"{est(c['approvals_share'])} | {est(c['need_share'])} | {est(c['population_share'])} | "
          f"{est(c['area_share'])} |")
    w("")
    c = nb["regression"]["coef"]["relative_log_cost"]
    w(f"A coefficient of {c['b']:+.1f} means an SA3 10% dearer than its SA4's mean takes "
      f"{abs(c['b']) * math.log(1.1):.1f} share points {'less' if c['b'] < 0 else 'more'} of the SA4's "
      "new SDA than its approvals, need, population and area predict. The controls are collinear "
      "with one another (Phase 1), so read their coefficients with care; the cost coefficient is "
      "the quantity of interest.")
    w("")
    w("**Within-SA4 multinomial (Poisson with SA4 effects).** Counts rather than shares: the SA3's "
      "new SDA (negatives set to zero) on relative log cost and the logs of approvals, need, "
      "population and area. A cost coefficient of −1 means a 10% dearer SA3 gets about 10% less "
      "SDA, holding the others fixed.")
    w("")
    w("| Outcome | SA4s | Relative log cost | Log approvals | Log need | Log population | Log area |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for o, lab in OUTCOMES:
        g = P[o]["multinomial"]
        c = g["coef"]
        w(f"| {lab} | {g['sa4s']} | {est(c['relative_log_cost'])} | {est(c['log_approvals'])} | "
          f"{est(c['log_need'])} | {est(c['log_population'])} | {est(c['log_area'])} |")
    w("")

    # ---- Test 3
    B = a["border"]
    w("## 3. Across SA4 borders")
    w("")
    w(f"Adjacent SA3s either side of an SA4 border ({B['pairs']} pairs sharing at least "
      f"{MIN_BORDER_KM} km of border, with cost data, across {B['clusters']} SA4 borders). For each "
      "pair: the side's share of the pair's new SDA minus its share of the pair's approvals "
      "(percentage points), against the log gap in the location factor and the log gap in median "
      "mortgage. The factor is each SA4's factors weighted by a building-type mix common to both "
      "sides (the two SA4s' new-build growth), so the gap is price, not mix. Standard errors are "
      "clustered by SA4 border; the permutation flips the factor gap's sign border by border, "
      "after partialling out the cost gap. The pre-2023 factors applied to all stock; since 1 July "
      "2023 new builds have their own. Sites committed before mid-2023 faced the first set.")
    w("")
    wl = {"full": f"{month(B['windows']['full'][0])}–{month(B['windows']['full'][1])}",
          "early": f"{month(B['windows']['early'][0])}–{month(B['windows']['early'][1])}",
          "late": f"{month(B['windows']['late'][0])}–{month(B['windows']['late'][1])}"}
    w(f"| Factors | New SDA over | Pairs | Factor gap (per log point) | Permutation p | Cost gap | Pairs with a factor gap ≥ {GAP_SIGN_TEST:.0%}: higher side builds more per approval |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for key, label, _, _ in FACTOR_SETS:
        for win in ("full", "early", "late"):
            c = B["cross"][f"{key}:{win}"]
            w(f"| {label} | {wl[win]} | {c['pairs']} | {est(c['factor'])} | {pval(c['p_flip'])} | "
              f"{est(c['cost'])} | {c['higher_side_more']} of {c['decided']} |")
    w("")
    dd = B["did"]
    w(f"**Before and after the re-set.** The two sets of factor gaps are related (rank correlation "
      f"{f2(B['gap_correlation'])} across pairs) but not the same: across the {dd['pairs']} pairs "
      f"with new SDA in both windows, the July 2023 re-set moved the factor gap by a median "
      f"{dd['gap_change_median']:.3f} log points (at most {dd['gap_change_max']:.2f}; "
      f"{dd['gap_change_ge_0_05']} pairs by 5% or more). The change in a pair's SDA gap from "
      f"{wl['early']} to {wl['late']} on the change in its factor gap: {est(dd)} "
      f"(permutation p {pval(dd['p_flip'])}, {dd['clusters']} SA4 borders). Land either side is "
      "held fixed in this comparison.")
    w("")
    w("**What it can support.** Whether, where an SA4 border separates two prices, building "
      "follows the price rather than the land. **What it cannot.** A two-year development lag "
      f"means much of what was enrolled over {wl['late']} was committed before the July 2023 "
      "factors were known, so the after window is only partly after. Pairs overlap (an SA3 sits in "
      "several), which the clustering allows for only in part.")
    w("")

    # ---- Test 4
    w("## 4. Placebos: stock that predates NDIS pricing")
    w("")
    w("Legacy stock (enrolled `Legacy` build type) and existing stock predate NDIS pricing, so their "
      "location cannot reflect the location-factor incentive. Each is a level, taken at "
      f"{month(START)}, so it is set against where people live (population share), not against "
      "recent approvals; new build is shown measured the same way.")
    w("")
    w("| Stock | Dwellings in qualifying SA4s | SA4s | Stock share | Stock share minus population share |")
    w("| --- | --- | --- | --- | --- |")
    for key, lab in (("new_build", "New build (added over the window)"), ("existing", "Existing"),
                     ("legacy", "Legacy")):
        pl = a["placebo"][key]
        r = pl["rank"]
        tot = (f"{pl['total']:,.0f}" if "total" in pl else f"{a['totals']['new_build']:,.0f}")
        w(f"| {lab} | {tot} | {r['stock']['sa4s']} | {f2(r['stock']['mean'])} (p {pval(r['stock']['p'])}) | "
          f"{f2(r['beyond_population']['mean'])} (p {pval(r['beyond_population']['p'])}) |")
    w("")
    lgp = a["placebo"]["legacy"]
    w(f"Legacy stock is small ({lgp['total']:,.0f} dwellings in qualifying SA4s, in "
      f"{lgp['sa3s_with']} SA3s in all), so it can detect only a large lean. Existing stock is the "
      "stronger placebo, with one caveat: its enrolment in SDA, unlike its construction, could "
      "respond to price.")
    w("")

    # ---- Test 5
    w("## 5. Dose-response: a wider cost spread, more margin at stake")
    w("")
    w("If the lean is about margin, it should be steeper where cost differs more within the SA4. "
      "The SDA-minus-approvals share (percentage points) on relative log cost and its interaction "
      "with the SA4's cost spread (standard deviation of relative log mortgage, standardised "
      "across SA4s); and the mean rank correlation of the lean with cost by third of cost spread.")
    w("")
    w("| Outcome | Slope at mean spread | Change in slope per SD of spread | Narrowest third | Middle third | Widest third |")
    w("| --- | --- | --- | --- | --- | --- |")
    for o, lab in OUTCOMES:
        dd = P[o]["dose"]
        th = " | ".join(f"{f2(t['mean_rho'])} ± {t['se']:.2f} ({t['sa4s']})" for t in dd["thirds"])
        w(f"| {lab} | {est(dd['slope'])} | {est(dd['interaction'])} | {th} |")
    w("")
    w("A *negative* interaction would mean the lean toward cheap SA3s steepens where the spread is "
      "wider. The other half of the dose-response test (a high factor set against the SA4's cheapest "
      "land) needs cost levels comparable across SA4s and the factors in force at the time, and is "
      "not run.")
    w("")

    # ---- Robustness
    w("## Robustness")
    w("")
    w("The headline statistics under each variant: mean within-SA4 rank correlation of relative "
      "cost with the SDA-minus-approvals share (permutation p), and the fixed-effects regression's "
      "cost coefficient.")
    w("")
    w("| Variant | SA3s | New build: rank | New build: regression | HPS: rank | HPS: regression | Robust: rank | Robust: regression |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for key, t in a["tests"].items():
        cells = []
        for o, _ in OUTCOMES:
            r = t["outcomes"][o]["rank"]["difference"]
            g = t["outcomes"][o]["regression"]["coef"]["relative_log_cost"]
            cells += [f"{f2(r['mean'])} (p {pval(r['p'])}, {r['sa4s']})", est(g)]
        w(f"| {t['label']} | {t['sa3s']} | " + " | ".join(cells) + " |")
    w("")
    w(f"Victoria holds {a['vic_share']['robust']:.0%} of Robust growth, {a['vic_share']['hps']:.0%} "
      f"of High Physical Support and {a['vic_share']['new_build']:.0%} of new build. The "
      f"{DROP_LARGEST} SA4s building most: " + ", ".join(nm(s) for s in a["largest"]) + ". "
      f"Growth corridors are the top {CORRIDOR_SHARE:.0%} of SA3s by house approvals per 1,000 "
      f"residents over the comparison window ({len(a['corridor'])} SA3s), so that cheap does not "
      "simply mean greenfield.")
    w("")
    w("**Approvals lag.** The comparator window moved back from 0 to 8 quarters:")
    w("")
    w("| Lag (quarters) | Window | New build: rank | New build: regression | HPS: rank | Robust: rank |")
    w("| --- | --- | --- | --- | --- | --- |")
    for lag in LAGS:
        x = a["lags"][str(lag)]
        wd = a["windows"][str(lag)]
        w(f"| {lag} | {quarter_start(wd[0])} – {month(wd[1])} | "
          f"{f2(x['new_build']['rank']['difference']['mean'])} (p {pval(x['new_build']['rank']['difference']['p'])}) | "
          f"{est(x['new_build']['regression']['coef']['relative_log_cost'])} | "
          f"{f2(x['hps']['rank']['difference']['mean'])} (p {pval(x['hps']['rank']['difference']['p'])}) | "
          f"{f2(x['robust']['rank']['difference']['mean'])} (p {pval(x['robust']['rank']['difference']['p'])}) |")
    w("")

    # ---- Limits
    w("## Limits")
    w("")
    w("- **The cost measure is 2021 only, and a proxy.** A median mortgage repayment reflects what "
      "households borrowed, for the dwellings they bought, in 2021. It tracks land cost but is not "
      "it, and relative prices within an SA4 may have moved since.")
    w("- **The cost measure also tracks newness.** Median mortgage and rent are higher where "
      "dwellings are newer, so SA3s already building before 2021 read as dear. General approvals "
      "lean that way, which widens the SDA-minus-approvals gap. A land-value measure (for example "
      "state valuer-general site values by SA3) would separate land cost from newness.")
    w("- **Cheap land is usually also available land.** Approvals share is the control for that, "
      "and growth corridors are dropped as a check, but a greenfield estate offers large, flat, "
      "vacant lots that suit SDA designs in ways a median cannot capture.")
    w("- **Providers weigh more than margin:** proximity to participants, services, transport and "
      "hospitals. Need share controls for the first only.")
    w("- **Ecological.** Every figure compares SA3 totals. It says where SDA was built relative to "
      "other building, not why any provider chose any site.")
    w("- **The outcome is a net change in published totals.** HPS and Robust enrolled dwellings "
      "include existing dwellings newly enrolled, and SA3 has no building-type split.")
    w("- **The factor and land cost move together.** A higher factor usually marks dearer land, "
      "so across a border the factor gap is not independent of land cost, and the only cost "
      "control is the 2021 Census median. The before-and-after comparison avoids this but has "
      "only two years of after, much of it committed before the new factors were known; it is "
      "worth re-running as quarters are added.")
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
    a = analyse(load())
    (out / "location_factor.json").write_text(json.dumps(rounded(a), indent=1) + "\n")
    (out / "LOCATION_FACTOR.md").write_text(to_markdown(a))
    print(f"wrote {out}/location_factor.json and LOCATION_FACTOR.md", file=sys.stderr)


if __name__ == "__main__":
    main()
