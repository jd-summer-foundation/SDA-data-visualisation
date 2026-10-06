#!/usr/bin/env python3
"""Victoria: the within-SA4 tests again, with vacant-land prices as the cost measure.

The Phase 2 tests (analyse_location_factor.py) measure cost by the 2021 Census
median mortgage repayment, which is high where housing is new, so it tracks
newness as well as land cost. Valuer-General Victoria publishes annual median
sale prices of vacant residential land by locality, which is land cost itself.
This carries them to SA3 and re-runs the within-SA4 tests for Victoria with
each cost measure on exactly the same SA3s, so any difference comes from the
measure, not the sample.

Medians VGV marks '*' were carried forward from a year with no sales, so they
are never used; '^' (fewer than 10 sales that year) is used in the primary run
and dropped in a sensitivity check.

SA3 land price: each locality's mean log median over LAND_YEARS, averaged over
the localities in the SA3 weighted by their 2021 dwellings in it
(data/abs/sal_sa3_dwellings.csv). An SA3 is used when localities with a median
hold at least MIN_COVERAGE of its dwellings.

Reads committed files only; writes data/panel/land_value_vic.json and
LAND_VALUE_VIC.md. Every figure in the Markdown is computed here.

Usage:  python3 scripts/analyse_land_value.py [-o data/panel]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyse_location_factor import (  # noqa: E402
    LAG_PRIMARY, MIN_BORDER_KM, OUTCOMES, PERMUTATIONS, border_test, build_frame, dose_response, est,
    f2, groups_of, month, multinomial, outcome_series, pval, rank_test, rounded, share_regression,
    shares, variants)
from analyse_panel import spearman  # noqa: E402
from feasibility_location_factor import DATA, END, START, load  # noqa: E402

SEED = 20260930
LAND_YEARS = (2021, 2023)   # calendar years; when the SDA enrolled Jun 2023 - Jun 2026 was committed
MIN_COVERAGE = 0.25
MIN_SA4S_MODEL = 8          # fewer SA4s than this cannot carry a five-covariate model
COVERAGE_CHECK = 0.5
NSW_BASE_DATES = (2021, 2023)   # 1 July valuations, matching Victoria's 2021-2023 window
NSW_SPECS = [  # name, measure in land_value_by_locality.csv, coverage threshold
    ("primary", "urban", MIN_COVERAGE),
    ("per_lot", "urban_lot", MIN_COVERAGE),
    ("plain_basis", "urban_plain", MIN_COVERAGE),
    ("wider_zones", "wider", MIN_COVERAGE),
    ("coverage_half", "urban", COVERAGE_CHECK),
]


def land_prices(unflagged=False):
    """SAL code -> mean log median vacant-land price over LAND_YEARS.

    '*' medians repeat an earlier year's and are always dropped; with
    `unflagged`, '^' medians (fewer than 10 sales) are dropped too.
    """
    logs = defaultdict(list)
    with open(DATA / "vgv" / "vacant_land_by_locality.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["flag"] == "*" or (unflagged and r["flag"]):
                continue
            if LAND_YEARS[0] <= int(r["year"]) <= LAND_YEARS[1]:
                logs[r["sal_code_2021"]].append(math.log(float(r["median_price"])))
    return {k: statistics.fmean(v) for k, v in logs.items()}


def nsw_land_prices(measure="urban"):
    """SAL code -> mean log median NSW land value over NSW_BASE_DATES.

    `measure` is a column group of data/nsw_vg/land_value_by_locality.csv
    (see reduce_nsw_vg.py); base dates without a median are skipped.
    """
    logs = defaultdict(list)
    with open(DATA / "nsw_vg" / "land_value_by_locality.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            year = int(r["base_date"][:4])
            if NSW_BASE_DATES[0] <= year <= NSW_BASE_DATES[1] and r[f"{measure}_median"]:
                logs[r["sal_code_2021"]].append(math.log(float(r[f"{measure}_median"])))
    return {k: statistics.fmean(v) for k, v in logs.items()}


def sa3_land(d, prices, state="VIC"):
    """SA3 code -> (log land price, dwelling coverage) for the state's SA3s."""
    num, cov, tot = defaultdict(float), defaultdict(float), defaultdict(float)
    with open(DATA / "abs" / "sal_sa3_dwellings.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["state"] != state:
                continue
            dw = float(r["dwellings"])
            tot[r["sa3_code"]] += dw
            if r["sal_code"] in prices:
                num[r["sa3_code"]] += dw * prices[r["sal_code"]]
                cov[r["sa3_code"]] += dw
    return {c: (num[c] / cov[c], cov[c] / tot[c]) for c in tot if cov[c] > 0}


def within(frame, members, key):
    """Relative log values within SA4, over the given SA3s."""
    by = defaultdict(list)
    for g in members:
        by[frame[g]["sa4"]].append(g)
    out = {}
    for gs in by.values():
        if len(gs) < 2:
            continue
        mu = statistics.fmean(math.log(frame[g][key]) for g in gs)
        for g in gs:
            out[g] = math.log(frame[g][key]) - mu
    return out


def model(fn, frame, groups, outcome, cost):
    """A model's result, or None where too few SA4s identify it."""
    if len(groups) < MIN_SA4S_MODEL:
        return None
    try:
        return fn(frame, groups, outcome, cost)
    except ZeroDivisionError:  # singular: the covariates are not identified
        return None


def coef(m):
    return "—" if m is None else est(m["coef"]["relative_log_cost"])


def run(frame, members, rng):
    """Every test on one SA3 set, with each cost measure."""
    res = {}
    for cost in ("land", "mortgage"):
        block = {}
        for outcome, _ in OUTCOMES:
            groups = groups_of(frame, members, outcome, cost)
            if len(groups) < 3:
                block[outcome] = None
                continue
            block[outcome] = {
                "rank": rank_test(frame, groups, cost, outcome_series(outcome), rng),
                "rank_houses": rank_test(frame, groups, cost,
                                         outcome_series(outcome, comparator="houses"), rng)["approvals"],
                "regression": model(share_regression, frame, groups, outcome, cost),
                "multinomial": model(multinomial, frame, groups, outcome, cost),
            }
        groups = groups_of(frame, members, "existing", cost)
        block["existing"] = rank_test(frame, groups, cost, {
            "beyond_population": lambda fr, gs: [a - b for a, b in zip(
                shares(fr, gs, "existing"), shares(fr, gs, "persons"))]}, rng)["beyond_population"]
        groups = groups_of(frame, members, "new_build", cost)
        block["new_vs_population"] = rank_test(frame, groups, cost, {
            "beyond_population": lambda fr, gs: [a - b for a, b in zip(
                shares(fr, gs, "new_build"), shares(fr, gs, "persons"))]}, rng)["beyond_population"]
        res[cost] = block
    return res


def analyse(d):
    frame, _ = build_frame(d)
    rng = random.Random(SEED)
    _, _, corridor = variants(frame)
    code_of = {g: r["sa3_code"] for g, r in d["sa3"].items()}
    vic = sorted(g for g, r in frame.items() if r["state"] == "VIC")
    specs = {}
    for name, unflagged, min_cov in (("primary", False, MIN_COVERAGE),
                                     ("unflagged", True, MIN_COVERAGE),
                                     ("coverage_half", False, COVERAGE_CHECK)):
        land = sa3_land(d, land_prices(unflagged))
        for g in vic:
            v = land.get(code_of[g])
            frame[g]["land"] = math.exp(v[0]) if v and v[1] >= min_cov else None
            frame[g]["coverage"] = v[1] if v else 0.0
        members = [g for g in vic if frame[g]["land"] is not None and frame[g]["mortgage"] is not None]
        rel_land, rel_mort = within(frame, members, "land"), within(frame, members, "mortgage")
        both = sorted(set(rel_land) & set(rel_mort))
        spec = {"sa3s": len(members), "excluded": sorted(set(vic) - set(members)),
                "sa4s_two": len({frame[g]["sa4"] for g in both}),
                "land_vs_mortgage": spearman([rel_land[g] for g in both], [rel_mort[g] for g in both]),
                "sd_land": statistics.pstdev([rel_land[g] for g in both]),
                "sd_mortgage": statistics.pstdev([rel_mort[g] for g in both]),
                "tests": run(frame, members, rng)}
        cor = [g for g in both if g in corridor]
        spec["corridor"] = {"sa3s": len(cor),
                            "mean_rel_land": statistics.fmean(rel_land[g] for g in cor) if cor else None,
                            "mean_rel_mortgage": statistics.fmean(rel_mort[g] for g in cor) if cor else None}
        if name == "primary":
            spec["new_sda_covered"] = (sum(frame[g]["new_build"] for g in members)
                                       / sum(frame[g]["new_build"] for g in vic))
            spec["new_sda_vic"] = sum(frame[g]["new_build"] for g in vic)
            spec["vic_sa3s"] = len(vic)
        specs[name] = spec
    return {"land_years": list(LAND_YEARS), "min_coverage": MIN_COVERAGE, "specs": specs}


def evaluate(d, frame, state, prices, min_cov, rng, corridor):
    """One NSW specification: the SA3s it covers, and every test on them."""
    code_of = {g: r["sa3_code"] for g, r in d["sa3"].items()}
    members_all = sorted(g for g, r in frame.items() if r["state"] == state)
    land = sa3_land(d, prices, state)
    for g in members_all:
        v = land.get(code_of[g])
        frame[g]["land"] = math.exp(v[0]) if v and v[1] >= min_cov else None
    members = [g for g in members_all if frame[g]["land"] is not None and frame[g]["mortgage"] is not None]
    rel_land, rel_mort = within(frame, members, "land"), within(frame, members, "mortgage")
    both = sorted(set(rel_land) & set(rel_mort))
    cor = [g for g in both if g in corridor]
    dwellings = defaultdict(float)
    with open(DATA / "abs" / "sal_sa3_dwellings.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["state"] == state:
                dwellings[r["sa3_code"]] += float(r["dwellings"])
    return members, {
        "sa3s": len(members), "state_sa3s": len(members_all),
        "excluded": sorted(set(members_all) - set(members)),
        "localities": len(prices),
        "dwellings_covered": (sum(dwellings[code_of[g]] for g in members)
                              / sum(dwellings[code_of[g]] for g in members_all)),
        "new_sda_covered": (sum(frame[g]["new_build"] for g in members)
                            / sum(frame[g]["new_build"] for g in members_all)),
        "new_sda_state": sum(frame[g]["new_build"] for g in members_all),
        "sa4s_two": len({frame[g]["sa4"] for g in both}),
        "land_vs_mortgage": spearman([rel_land[g] for g in both], [rel_mort[g] for g in both]),
        "sd_land": statistics.pstdev([rel_land[g] for g in both]),
        "sd_mortgage": statistics.pstdev([rel_mort[g] for g in both]),
        "corridor": {"sa3s": len(cor),
                     "mean_rel_land": statistics.fmean(rel_land[g] for g in cor) if cor else None,
                     "mean_rel_mortgage": statistics.fmean(rel_mort[g] for g in cor) if cor else None},
        "tests": run(frame, members, rng)}


def standardise(d, frame, plans):
    """Set frame land to each state's primary price over its within-SA4 SD.

    `plans` is [(state, SAL prices, SD)]. SA4s never cross a state border, so
    every SA3's land relative to its SA4 becomes relative log price in that
    state's within-SA4 standard deviations: comparable across the two states'
    measures (NSW per m2, Victoria per lot) for the pooled tests.
    """
    code_of = {g: r["sa3_code"] for g, r in d["sa3"].items()}
    members = []
    for state, prices, sd in plans:
        land = sa3_land(d, prices, state)
        for g in sorted(g for g, r in frame.items() if r["state"] == state):
            v = land.get(code_of[g])
            ok = v and v[1] >= MIN_COVERAGE and frame[g]["mortgage"] is not None
            frame[g]["land"] = math.exp(v[0] / sd) if ok else None
            if ok:
                members.append(g)
    return sorted(members)


def dose(frame, members):
    """Dose-response on the land price and on the mortgage, same SA3s."""
    out = {}
    for cost in ("land", "mortgage"):
        groups = groups_of(frame, members, "new_build", cost)
        out[cost] = dose_response(frame, groups, "new_build", cost) if len(groups) >= MIN_SA4S_MODEL else None
    return out


def analyse_nsw(d, vic):
    """NSW on its own, then NSW and Victoria pooled, then dose-response and borders."""
    frame, _ = build_frame(d)
    rng = random.Random(SEED)
    _, _, corridor = variants(frame)
    specs = {}
    members = {}
    for name, measure, min_cov in NSW_SPECS:
        members[name], specs[name] = evaluate(d, frame, "NSW", nsw_land_prices(measure),
                                              min_cov, rng, corridor)
    # Pooled: each state's primary measure, standardised within state.
    nsw_sd, vic_sd = specs["primary"]["sd_land"], vic["specs"]["primary"]["sd_land"]
    plans = [("NSW", nsw_land_prices("urban"), nsw_sd), ("VIC", land_prices(), vic_sd)]
    pooled = standardise(d, frame, plans)
    nsw_m = [g for g in pooled if frame[g]["state"] == "NSW"]
    vic_m = [g for g in pooled if frame[g]["state"] == "VIC"]
    if nsw_m != members["primary"] or len(vic_m) != vic["specs"]["primary"]["sa3s"]:
        raise ValueError("pooled SA3s differ from each state's primary set")
    pooled_tests = run(frame, pooled, rng)
    doses = {"NSW": dose(frame, nsw_m), "VIC": dose(frame, vic_m), "pooled": dose(frame, pooled)}

    # Borders: pairs with a land price on both sides, within one state.
    def same_state(a, b):
        return frame[a]["state"] == frame[b]["state"]
    border = {"land": border_test(d, frame, rng, "land", same_state)}

    def priced(a, b):
        return same_state(a, b) and frame[a].get("land") is not None and frame[b].get("land") is not None
    border["mortgage"] = border_test(d, frame, rng, "mortgage", priced)
    pairs_by_state = defaultdict(int)
    for p in d["adjacency"]:
        a, b = p["sa3_a"], p["sa3_b"]
        if (p["cross_sa4"] == "yes" and float(p["shared_km"]) >= MIN_BORDER_KM
                and frame[a]["mortgage"] is not None and frame[b]["mortgage"] is not None and priced(a, b)):
            pairs_by_state[frame[a]["state"]] += 1
    return {"base_dates": list(NSW_BASE_DATES), "min_coverage": MIN_COVERAGE, "specs": specs,
            "pooled": {"sa3s": len(pooled), "nsw_sa3s": len(nsw_m), "vic_sa3s": len(vic_m),
                       "sd": {"NSW": nsw_sd, "VIC": vic_sd}, "tests": pooled_tests},
            "dose": doses, "border": border, "border_pairs_by_state": dict(sorted(pairs_by_state.items()))}


def cell(t, key="difference"):
    if t is None:
        return "—"
    r = t["rank"][key]
    return f"{f2(r['mean'])} (p {pval(r['p'])}, {r['sa4s']})"


def to_markdown(a):
    P = a["specs"]["primary"]
    T = P["tests"]
    L = []
    w = L.append
    y0, y1 = a["land_years"]
    w("# Victoria: the within-SA4 tests with vacant-land prices")
    w("")
    w("Generated by `scripts/analyse_land_value.py` from committed files. Every figure is "
      "computed; do not edit by hand. The Phase 2 tests are in `LOCATION_FACTOR.md`; this re-runs "
      "them for Victoria with land cost measured directly. Region-level and ecological throughout.")
    w("")
    w("## Why")
    w("")
    w("Phase 2 measured cost by the 2021 Census median mortgage repayment. That is high where "
      "housing is new, because recent buyers carry larger loans, so growth areas read as dear. "
      "Valuer-General Victoria publishes the median sale price of vacant residential land by "
      "locality, which is land cost itself: the median sale of a vacant residential home site "
      "or surveyed lot under 4,000 m², by calendar year.")
    w("")
    w("## The land measure")
    w("")
    w("Medians VGV marks `*` repeat the previous year's for want of any sales and are not used; "
      "`^` marks a year with fewer than 10 sales and is used here, then dropped under Sensitivity "
      "(definitions from VGV's *A Guide to Property Values 2025*, p. 10).")
    w("")
    w(f"Each locality's mean log median, {y0}–{y1} (VGV's 2015–2025 time series), carried to SA3 by "
      "the locality's 2021 dwellings in each SA3 (ABS Mesh Blocks). An SA3 is used when localities "
      f"with a median hold at least {a['min_coverage']:.0%} of its dwellings: {P['sa3s']} of "
      f"{P['vic_sa3s']} Victorian SA3s, holding {P['new_sda_covered']:.0%} of Victoria's "
      f"{P['new_sda_vic']:,.0f} new-build SDA dwellings. The rest are almost all inner and middle "
      "Melbourne, which is built out and sells little vacant land: "
      + ", ".join(g.split(" - ", 1)[1] for g in P["excluded"]) + ".")
    w("")
    w(f"Within SA4s, relative land price and relative mortgage agree in rank "
      f"({f2(P['land_vs_mortgage'])}), but land spreads much wider: a within-SA4 standard deviation "
      f"of {P['sd_land']:.2f} log points against {P['sd_mortgage']:.2f}. Growth corridors "
      f"({P['corridor']['sa3s']} of these SA3s) sit {f2(P['corridor']['mean_rel_land'])} log points "
      f"from their SA4's mean on land price and {f2(P['corridor']['mean_rel_mortgage'])} on mortgage.")
    w("")
    w("## Results, same SA3s, each cost measure")
    w("")
    w("Mean within-SA4 rank correlation of relative cost with each share (permutation p within SA4, "
      f"{PERMUTATIONS:,} shuffles; number of SA4s). Negative means more where cost is lower. "
      f"Regressions need at least {MIN_SA4S_MODEL} SA4s and are shown as — below that.")
    w("")
    w("| Outcome | Cost measure | SDA share | All approvals share | House approvals share | SDA minus approvals | Regression cost coefficient | Multinomial cost coefficient |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    labels = dict(OUTCOMES)
    for o, lab in OUTCOMES:
        for cost, cl in (("land", "Vacant land"), ("mortgage", "Census mortgage")):
            t = T[cost][o]
            if t is None:
                w(f"| {lab} | {cl} | — | — | — | too few SA4s | — | — |")
                continue
            h = t["rank_houses"]
            w(f"| {lab} | {cl} | {cell(t, 'sda')} | {cell(t, 'approvals')} | "
              f"{f2(h['mean'])} (p {pval(h['p'])}) | {cell(t)} | "
              f"{coef(t['regression'])} | {coef(t['multinomial'])} |")
    w("")
    w("**Placebo** (share minus population share): ")
    w("")
    w("| Cost measure | New build | Existing stock (pre-NDIS) |")
    w("| --- | --- | --- |")
    for cost, cl in (("land", "Vacant land"), ("mortgage", "Census mortgage")):
        nb, ex = T[cost]["new_vs_population"], T[cost]["existing"]
        w(f"| {cl} | {f2(nb['mean'])} (p {pval(nb['p'])}, {nb['sa4s']}) | "
          f"{f2(ex['mean'])} (p {pval(ex['p'])}, {ex['sa4s']}) |")
    w("")
    w("## Sensitivity")
    w("")
    w("| Specification | SA3s | New build: SDA share | New build: approvals share | New build: SDA minus approvals | Regression |")
    w("| --- | --- | --- | --- | --- | --- |")
    for name, lab in (("primary", f"Primary (coverage ≥ {a['min_coverage']:.0%}, without * medians)"),
                      ("unflagged", "Also without ^ (fewer than 10 sales)"),
                      ("coverage_half", "Coverage ≥ 50%")):
        s = a["specs"][name]
        t = s["tests"]["land"]["new_build"]
        if t is None:
            w(f"| {lab} | {s['sa3s']} | — | — | — | — |")
            continue
        w(f"| {lab} | {s['sa3s']} | {cell(t, 'sda')} | {cell(t, 'approvals')} | {cell(t)} | "
          f"{coef(t['regression'])} |")
    w("")
    w("## What it can and cannot support")
    w("")
    nbL, nbM = T["land"]["new_build"], T["mortgage"]["new_build"]
    apL, apM = nbL["rank"]["approvals"], nbM["rank"]["approvals"]
    NEUTRAL = 0.1

    def lean(v):
        return "about neutral" if abs(v) < NEUTRAL else ("toward cheaper SA3s" if v < 0 else "toward dearer SA3s")
    w(f"- **Does general building lean dear on land price?** All approvals here lean "
      f"{f2(apM['mean'])} with the Census mortgage ({lean(apM['mean'])}) but {f2(apL['mean'])} with "
      f"vacant-land price ({lean(apL['mean'])}). "
      + ("So the apparent lean of general building toward dear SA3s comes from the mortgage "
         "measure, which reads new housing as dear, not from land."
         if abs(apL["mean"]) < NEUTRAL <= apM["mean"] else ""))
    sdL = nbL["rank"]["sda"]
    reg = nbL["regression"]
    w(f"- **Does SDA lean cheap on land price?** SDA share against relative land price: "
      f"{f2(sdL['mean'])} (p {pval(sdL['p'])}). Net of approvals, need, population and area, the "
      f"regression gives {coef(reg)} share points per log point and the multinomial "
      f"{coef(nbL['multinomial'])}; the rank difference from approvals is "
      f"{f2(nbL['rank']['difference']['mean'])} (p {pval(nbL['rank']['difference']['p'])}).")
    pn, pe = T["land"]["new_vs_population"], T["land"]["existing"]
    w(f"- **The placebo, on land.** Against population, new build leans {f2(pn['mean'])} "
      f"(p {pval(pn['p'])}) with land price; existing pre-NDIS stock {f2(pe['mean'])} "
      f"(p {pval(pe['p'])}). "
      + ("On the Census mortgage the two looked alike; on land they do not: pre-NDIS stock "
         "shows no lean toward cheap land, new SDA does."
         if pn["p"] < 0.05 and pe["p"] >= 0.05 and abs(pe["mean"]) < abs(pn["mean"]) / 2 else ""))
    w(f"- **Small sample.** {nbL['rank']['difference']['sa4s']} Victorian SA4s qualify; inner "
      "Melbourne is missing because it sells no vacant land, so these are comparisons among "
      "fringe, middle-ring and regional SA3s only.")
    w("- **Per lot, not per square metre.** VGV's vacant-land class is home sites under 4,000 m², "
      "which excludes lifestyle and acreage blocks, but lots within it still vary (a 2,000–3,999 m² "
      "regional site against a 400 m² estate lot), so a median lot price is not a price per "
      "square metre. VGV does not state the workbook's class in words; its quarterly report titles "
      "the same table \"median vacant residential land prices\".")
    w("- **Victoria and NSW only.** NSW, with Valuer General land values, is in `LAND_VALUE_NSW.md`; "
      "Queensland, South Australia and Western Australia publish no comparable free series.")
    return "\n".join(L) + "\n"


ATTRIBUTION = "© State of New South Wales through Valuer General NSW"
LICENCE_URL = "https://creativecommons.org/licenses/by/3.0/au/"


def per_sd(m, sd):
    """A regression's land coefficient per within-state SD of land price."""
    c = m["coef"]["relative_log_cost"]
    return {"b": c["b"] * sd, "se": c["se"] * sd}


def agree(a, b):
    """Same sign, and no more apart than their combined standard error allows."""
    return a["b"] * b["b"] > 0 and abs(a["b"] - b["b"]) < 1.96 * (a["se"] ** 2 + b["se"] ** 2) ** 0.5


def beyond(c):
    return abs(c["b"]) > 1.96 * c["se"]


def to_markdown_nsw(a, vic):
    P = a["specs"]["primary"]
    T = P["tests"]
    V = vic["specs"]["primary"]
    y0, y1 = a["base_dates"]
    L = []
    w = L.append
    w("# NSW: the within-SA4 tests with Valuer General land values")
    w("")
    w("Generated by `scripts/analyse_land_value.py` from committed files. Every figure is computed; "
      "do not edit by hand. `LAND_VALUE_VIC.md` ran these tests for Victoria with vacant-land sale "
      "prices; this runs them for NSW with the NSW Valuer General's land values, then for both "
      "states together, then the dose-response and border tests with land price as the cost "
      "measure. Region-level and ecological throughout: it compares regions' published totals and "
      "follows no dwelling, provider or participant.")
    w("")
    w("## The data")
    w("")
    w(f"NSW Valuer General bulk land values, snapshot of 1 September 2026, supplied on request: a "
      f"land value for every property in NSW at each 1 July base date from 2021 to 2025. "
      f"{ATTRIBUTION}, licensed under [CC BY 3.0 AU]({LICENCE_URL}). **Changed from the original:** "
      "the property records are not published; `data/nsw_vg/land_value_by_locality.csv` holds only "
      "locality medians, and this report SA3 averages of them (`scripts/reduce_nsw_vg.py`).")
    w("")
    w("These are **valuations, not sales**: the Valuer General's estimate of each parcel's land "
      "value, unimproved, at 1 July, made for rating and land tax. Unlike Victoria's sales they "
      "cover every parcel, so inner Sydney, which sells almost no vacant land, is measured too.")
    w("")
    w("## The land measure")
    w("")
    w(f"For each locality and base date, the median land value per m² of parcels zoned R1–R4 "
      f"(general, low, medium and high density residential) of 100 to 3,999 m², strata schemes "
      f"included (the Valuer General values a strata scheme once, for the whole site). A median "
      f"needs at least 10 parcels. Each locality's mean log median over 1 July {y0}–{y1}, to match "
      f"Victoria's {vic['land_years'][0]}–{vic['land_years'][1]}, is carried to SA3 by the "
      f"locality's 2021 dwellings in each SA3 (ABS Mesh Blocks), and an SA3 is used when localities "
      f"with a median hold at least {a['min_coverage']:.0%} of its dwellings: {P['sa3s']} of "
      f"{P['state_sa3s']} NSW SA3s, holding {P['dwellings_covered']:.1%} of NSW's 2021 dwellings and "
      f"{P['new_sda_covered']:.1%} of its {P['new_sda_state']:,.0f} new-build SDA dwellings. "
      "Left out: " + ", ".join(g.split(" - ", 1)[1] for g in P["excluded"]) + ".")
    w("")
    w(f"Within SA4s ({P['sa4s_two']} with two or more priced SA3s, against Victoria's "
      f"{V['sa4s_two']}), relative land price and relative mortgage agree in rank "
      f"({f2(P['land_vs_mortgage'])}; Victoria {f2(V['land_vs_mortgage'])}), and land spreads much "
      f"wider: a within-SA4 standard deviation of {P['sd_land']:.2f} log points against "
      f"{P['sd_mortgage']:.2f} (Victoria, per lot: {V['sd_land']:.2f} against {V['sd_mortgage']:.2f}). "
      f"Per m² separates small inner lots from large outer ones more than a per-lot price does. "
      f"Growth corridors ({P['corridor']['sa3s']} of these SA3s) sit "
      f"{f2(P['corridor']['mean_rel_land'])} log points from their SA4's mean on land price and "
      f"{f2(P['corridor']['mean_rel_mortgage'])} on mortgage.")
    w("")
    w("## NSW results, same SA3s, each cost measure")
    w("")
    w("Mean within-SA4 rank correlation of relative cost with each share (permutation p within SA4, "
      f"{PERMUTATIONS:,} shuffles; number of SA4s). Negative means more where cost is lower. "
      f"Regressions need at least {MIN_SA4S_MODEL} SA4s and are shown as — below that; their cost "
      "coefficient is in share points per log point of relative cost.")
    w("")
    w("| Outcome | Cost measure | SDA share | All approvals share | House approvals share | SDA minus approvals | Regression cost coefficient | Multinomial cost coefficient |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for o, lab in OUTCOMES:
        for cost, cl in (("land", "Land value per m²"), ("mortgage", "Census mortgage")):
            t = T[cost][o]
            if t is None:
                w(f"| {lab} | {cl} | — | — | — | too few SA4s | — | — |")
                continue
            h = t["rank_houses"]
            w(f"| {lab} | {cl} | {cell(t, 'sda')} | {cell(t, 'approvals')} | "
              f"{f2(h['mean'])} (p {pval(h['p'])}) | {cell(t)} | "
              f"{coef(t['regression'])} | {coef(t['multinomial'])} |")
    w("")
    w("**Placebo** (share minus population share):")
    w("")
    w("| Cost measure | New build | Existing stock (pre-NDIS) |")
    w("| --- | --- | --- |")
    for cost, cl in (("land", "Land value per m²"), ("mortgage", "Census mortgage")):
        nb, ex = T[cost]["new_vs_population"], T[cost]["existing"]
        w(f"| {cl} | {f2(nb['mean'])} (p {pval(nb['p'])}, {nb['sa4s']}) | "
          f"{f2(ex['mean'])} (p {pval(ex['p'])}, {ex['sa4s']}) |")
    w("")
    w("## Sensitivity")
    w("")
    w("| Specification | SA3s | New build: SDA share | New build: approvals share | New build: SDA minus approvals | Regression | Placebo: new build | Placebo: pre-NDIS stock |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    labels = {"primary": "Primary (R1–R4 per m², every valuation basis)",
              "per_lot": "Per parcel, not per m² (strata schemes left out)",
              "plain_basis": "Only values on basis 6A(1), the ordinary land value",
              "wider_zones": "R5 large-lot and RU5 village zones added, no area limit",
              "coverage_half": "Coverage ≥ 50%"}
    for name, lab in labels.items():
        sp = a["specs"][name]
        t = sp["tests"]["land"]
        nb = t["new_build"]
        pn, pe = t["new_vs_population"], t["existing"]
        w(f"| {lab} | {sp['sa3s']} | {cell(nb, 'sda')} | {cell(nb, 'approvals')} | {cell(nb)} | "
          f"{coef(nb['regression'])} | {f2(pn['mean'])} (p {pval(pn['p'])}) | "
          f"{f2(pe['mean'])} (p {pval(pe['p'])}) |")
    w("")
    w("Every record carries a *basis*: the section of the Valuation of Land Act 1916 the value was "
      "made under. Most are 6A(1), the ordinary land value; the documentation supplied does not "
      "explain the others, so the primary run keeps them and this check drops them. Almost all of "
      "Broken Hill is valued on another basis, which is why it drops out here.")
    w("")

    # ---- Both states
    Q = a["pooled"]
    QT = Q["tests"]
    w("## NSW and Victoria together")
    w("")
    w(f"The two states measure land differently (NSW per m² of valued land, Victoria per lot sold), "
      f"so for the pooled tests each SA3's land price relative to its SA4 is divided by its own "
      f"state's within-SA4 standard deviation ({Q['sd']['NSW']:.2f} log points for NSW, "
      f"{Q['sd']['VIC']:.2f} for Victoria). No SA4 crosses a state border, so this only rescales. "
      f"The rank tests are unaffected by it; the regressions are then in share points per within-state "
      f"standard deviation of land price. {Q['sa3s']} SA3s ({Q['nsw_sa3s']} NSW, {Q['vic_sa3s']} "
      "Victorian).")
    w("")
    nswT, vicT = T["land"]["new_build"], V["tests"]["land"]["new_build"]
    poolT = QT["land"]["new_build"]
    w("| New build, land price | NSW | Victoria | Pooled |")
    w("| --- | --- | --- | --- |")
    w(f"| SDA share | {cell(nswT, 'sda')} | {cell(vicT, 'sda')} | {cell(poolT, 'sda')} |")
    w(f"| All approvals share | {cell(nswT, 'approvals')} | {cell(vicT, 'approvals')} | {cell(poolT, 'approvals')} |")
    w(f"| SDA minus approvals | {cell(nswT)} | {cell(vicT)} | {cell(poolT)} |")
    w(f"| Regression, per log point | {coef(nswT['regression'])} | {coef(vicT['regression'])} | — |")
    rn, rv = per_sd(nswT["regression"], Q["sd"]["NSW"]), per_sd(vicT["regression"], Q["sd"]["VIC"])
    rp = poolT["regression"]["coef"]["relative_log_cost"]
    w(f"| Regression, per within-state SD | {est(rn)} | {est(rv)} | {est(rp)} |")
    mn = per_sd(nswT["multinomial"], Q["sd"]["NSW"])
    mv = per_sd(vicT["multinomial"], Q["sd"]["VIC"])
    mp = poolT["multinomial"]["coef"]["relative_log_cost"]
    w(f"| Multinomial, per within-state SD | {est(mn)} | {est(mv)} | {est(mp)} |")
    pl = {k: (T["land"][k], V["tests"]["land"][k], QT["land"][k]) for k in ("new_vs_population", "existing")}
    for k, lab in (("new_vs_population", "Placebo: new build minus population"),
                   ("existing", "Placebo: pre-NDIS stock minus population")):
        w(f"| {lab} | " + " | ".join(f"{f2(x['mean'])} (p {pval(x['p'])}, {x['sa4s']})" for x in pl[k]) + " |")
    w("")
    hs = QT["land"]["hps"]
    w(f"High Physical Support, pooled: SDA minus approvals {cell(hs)}, regression "
      f"{coef(hs['regression'])} per SD. Robust, pooled: {cell(QT['land']['robust'])}, regression "
      f"{coef(QT['land']['robust']['regression'])}.")
    w("")

    # ---- Dose-response and borders
    D = a["dose"]
    w("## Dose-response: is the lean steeper where land prices spread wider?")
    w("")
    w("If the margin drove the lean, new SDA should lean harder toward cheap SA3s in SA4s whose land "
      "prices spread widest. The interaction of relative cost with the SA4's spread (in SDs of "
      "spread across SA4s), on the SDA-minus-approvals share, and the mean within-SA4 rank "
      "correlation of that lean with cost in each third of SA4s by spread (narrowest first). Land "
      "is per within-state SD, as above. Negative means a steeper lean toward cheap land.")
    w("")
    w("| SA3s | Cost measure | SA4s | Interaction (per SD of spread) | Narrowest third | Middle third | Widest third |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for k, lab in (("NSW", "NSW"), ("VIC", "Victoria"), ("pooled", "Both states")):
        for cost, cl in (("land", "Land price"), ("mortgage", "Census mortgage")):
            x = D[k][cost]
            if x is None:
                w(f"| {lab} | {cl} | too few | — | — | — | — |")
                continue
            th = x["thirds"]
            w(f"| {lab} | {cl} | {sum(t['sa4s'] for t in th)} | {est(x['interaction'])} | "
              + " | ".join(f"{f2(t['mean_rho'])} (± {t['se']:.2f})" for t in th) + " |")
    w("")
    B = a["border"]
    BL, BM = B["land"], B["mortgage"]
    bp = a["border_pairs_by_state"]
    w("## Border test with land price as the cost control")
    w("")
    w(f"Adjacent SA3s either side of an SA4 border, both priced, within one state: {BL['pairs']} "
      f"pairs ({bp.get('NSW', 0)} NSW, {bp.get('VIC', 0)} Victorian) in {BL['clusters']} SA4-pair "
      "clusters. The SDA-per-approval gap between the two sides on the factor gap (log), with the "
      "land-price gap (per within-state SD) as the cost control, and then the Census mortgage gap on "
      "the same pairs. Permutation p flips each cluster's sign.")
    w("")
    w("| Factors | Window | Factor gap, land control | p | Land gap | Factor gap, mortgage control | p | Mortgage gap |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for key, fl in (("combined", "Combined table (to June 2023)"), ("new_build", "New-build table (from July 2023)")):
        for win, wl in (("full", "Jun 2023–Jun 2026"), ("early", "to Jun 2024"), ("late", "from Jun 2024")):
            c, m = BL["cross"][f"{key}:{win}"], BM["cross"][f"{key}:{win}"]
            w(f"| {fl} | {wl} | {est(c['factor'])} | {pval(c['p_flip'])} | {est(c['cost'])} | "
              f"{est(m['factor'])} | {pval(m['p_flip'])} | {est(m['cost'])} |")
    w("")
    w(f"Before and after the July 2023 re-set (land held fixed, so the cost control does not "
      f"enter): {est(BL['did'])} (p {pval(BL['did']['p_flip'])}), {BL['did']['pairs']} pairs.")
    w("")

    # ---- What it supports
    w("## What it can and cannot support")
    w("")
    apL, hoL = nswT["rank"]["approvals"], nswT["rank_houses"]
    w(f"- **General building in NSW leans {'dear' if apL['mean'] > 0 else 'cheap'} on land** "
      f"({f2(apL['mean'])}, p {pval(apL['p'])}); house approvals alone {f2(hoL['mean'])} "
      f"(p {pval(hoL['p'])}). "
      + ("So the lean is other residential building (townhouses, units and apartments) going to "
         "the dearer SA3s, as density follows land value. Victoria's general building was neutral on land "
         f"({f2(vicT['rank']['approvals']['mean'])})."
         if apL["mean"] > 0 and apL["p"] < 0.05 <= hoL["p"] else ""))
    sd_, df_ = nswT["rank"]["sda"], nswT["rank"]["difference"]
    nreg = nswT["regression"]["coef"]["relative_log_cost"]
    confirm = df_["mean"] < 0 and df_["p"] < 0.05 and nreg["b"] < 0 and beyond(nreg)
    w(f"- **Does NSW confirm that new SDA leans toward cheaper land?** "
      + ("Yes. " if confirm else "No, not on its own. ")
      + f"New SDA's share against relative land price is {f2(sd_['mean'])} (p {pval(sd_['p'])}) and "
      f"its difference from approvals {f2(df_['mean'])} (p {pval(df_['p'])}), on "
      f"{df_['sa4s']} SA4s. Net of approvals, need, population and area the regression gives "
      f"{est(nreg)} per log point and the multinomial "
      f"{est(nswT['multinomial']['coef']['relative_log_cost'])}: "
      + ("the same sign as Victoria's, " if nreg["b"] < 0 else "the opposite sign to Victoria's, ")
      + ("but within two standard errors of zero." if not beyond(nreg) else "beyond two standard errors."))
    pn, pe = T["land"]["new_vs_population"], T["land"]["existing"]
    w(f"- **The placebo does {'not ' if not (pn['p'] < 0.05 <= pe['p']) else ''}separate in NSW.** "
      f"Against population, new build {f2(pn['mean'])} (p {pval(pn['p'])}); pre-NDIS stock "
      f"{f2(pe['mean'])} (p {pval(pe['p'])}). In Victoria it did: new SDA "
      f"{f2(V['tests']['land']['new_vs_population']['mean'])}, pre-NDIS stock "
      f"{f2(V['tests']['land']['existing']['mean'])}.")
    w(f"- **Scale for scale, the regressions agree.** Per within-state SD of land price, NSW gives "
      f"{est(rn)} and Victoria {est(rv)}; "
      + ("within sampling error of each other: on this test NSW is too imprecise to confirm "
         "Victoria's estimate, not evidence against it. " if agree(rn, rv) else
         "these differ by more than sampling error. ")
      + f"Pooled, {est(rp)} (multinomial {est(mp)}), "
      + ("beyond two standard errors" if beyond(rp) else "within two standard errors")
      + f". The pooled rank difference is {f2(poolT['rank']['difference']['mean'])} "
      f"(p {pval(poolT['rank']['difference']['p'])}) and the pooled placebo gives new build "
      f"{f2(QT['land']['new_vs_population']['mean'])} against pre-NDIS stock "
      f"{f2(QT['land']['existing']['mean'])}"
      + (": in the pooled data only the regressions, which hold approvals, need, population and "
         "area fixed, point toward cheaper land."
         if poolT["rank"]["difference"]["p"] >= 0.05 and not (
             QT["land"]["new_vs_population"]["p"] < 0.05 <= QT["land"]["existing"]["p"]) else "."))
    lot = a["specs"]["per_lot"]["tests"]["land"]["new_build"]
    ld = lot["rank"]["difference"]
    w(f"- **Per parcel{', NSW leans the other way' if ld['mean'] > 0 and ld['p'] < 0.05 else ''}.** "
      f"On the per-parcel measure new SDA's difference "
      f"from approvals is {f2(ld['mean'])} (p {pval(ld['p'])}): "
      + ("toward the *dearer* SA3s, " if ld["mean"] > 0 else "toward the cheaper SA3s, ")
      + ("beyond" if ld["p"] < 0.05 else "within")
      + f" sampling error, while its regression is {coef(lot['regression'])}. The rank tests compare "
      "shares alone; the regressions also hold each SA3's approvals, need, population and area "
      "fixed.")
    dz = D["pooled"]["land"]["interaction"]
    w(f"- **No dose-response on land either.** Pooled, the interaction is {est(dz)} per SD of spread, "
      + ("within" if not beyond(dz) else "beyond")
      + " two standard errors of zero: the lean does not steepen where land prices spread wider.")
    bf = BL["cross"]
    pulls = [k for k, c in bf.items() if c["p_flip"] < 0.05 and c["factor"]["b"] > 0]
    landc = bf["combined:full"]["cost"]
    w(f"- **Borders, with land as the control.** "
      + ("No factor-by-window combination shows building following the higher factor at p < 0.05. "
         if not pulls else f"{len(pulls)} factor-by-window combinations show building following the higher factor at p < 0.05. ")
      + f"The land-price gap itself enters at {est(landc)} share points per SD over the whole window "
      "(pre-2023 factors): "
      + ("the cheaper side of a border gets more SDA per approval, " if landc["b"] < 0 else
         "the dearer side of a border gets more SDA per approval, ")
      + ("beyond" if beyond(landc) else "within") + " two standard errors.")
    w("- **Limits.** Valuations are an estimate of each parcel's unimproved land value, not a price "
      "anyone paid. Per m² is not per lot: small inner lots carry the highest values per m², which "
      "is why the per-parcel measure is shown alongside. SA3 prices weight localities by their 2021 "
      "dwellings, before any of the SDA in question was built. Zones are as at the 2026 snapshot, "
      "and parcels created since 2021 carry no 2021 value. Every comparison is between regions.")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", default=str(DATA / "panel"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    d = load()
    a = analyse(d)
    # Six decimals: LOCATION_FACTOR.md quotes these figures from the JSON, and at
    # four a value on a rounding boundary could print differently from here.
    (out / "land_value_vic.json").write_text(json.dumps(rounded(a, 6), indent=1) + "\n")
    (out / "LAND_VALUE_VIC.md").write_text(to_markdown(a))
    n = analyse_nsw(d, a)
    (out / "land_value_nsw.json").write_text(json.dumps(rounded(n, 6), indent=1) + "\n")
    (out / "LAND_VALUE_NSW.md").write_text(to_markdown_nsw(n, a))
    print(f"wrote {out}/land_value_vic.json, LAND_VALUE_VIC.md, land_value_nsw.json and "
          "LAND_VALUE_NSW.md", file=sys.stderr)


if __name__ == "__main__":
    main()
