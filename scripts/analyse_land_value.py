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
    LAG_PRIMARY, OUTCOMES, PERMUTATIONS, build_frame, est, f2, groups_of, month, multinomial,
    outcome_series, pval, rank_test, rounded, share_regression, shares, variants)
from analyse_panel import spearman  # noqa: E402
from feasibility_location_factor import DATA, END, START, load  # noqa: E402

SEED = 20260930
LAND_YEARS = (2021, 2023)   # calendar years; when the SDA enrolled Jun 2023 - Jun 2026 was committed
MIN_COVERAGE = 0.25
MIN_SA4S_MODEL = 8          # fewer SA4s than this cannot carry a five-covariate model
COVERAGE_CHECK = 0.5


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


def sa3_land(d, prices):
    """SA3 code -> (log land price, dwelling coverage) for Victorian SA3s."""
    num, cov, tot = defaultdict(float), defaultdict(float), defaultdict(float)
    with open(DATA / "abs" / "sal_sa3_dwellings.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["state"] != "VIC":
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
    w("- **Victoria only.** NSW bulk land values are available only on request; Queensland, South "
      "Australia and Western Australia publish no comparable free series.")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", default=str(DATA / "panel"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    a = analyse(load())
    (out / "land_value_vic.json").write_text(json.dumps(rounded(a), indent=1) + "\n")
    (out / "LAND_VALUE_VIC.md").write_text(to_markdown(a))
    print(f"wrote {out}/land_value_vic.json and LAND_VALUE_VIC.md", file=sys.stderr)


if __name__ == "__main__":
    main()
