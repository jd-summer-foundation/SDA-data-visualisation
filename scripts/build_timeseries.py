#!/usr/bin/env python3
"""Build data/timeseries.json, the one file the time-based interface reads.

Reads data/panel/panel.csv and data/panel/analysis.json. Every series is
aligned to the panel's quarters, with null where a measure is not published
(participants in use start in December 2023, need by category in December
2024), so a chart can say where a series begins instead of drawing a zero.

Headlines state a conclusion, as agreed for the new interface. Each is chosen
here from the numbers and flips if they do: the wording is a function of the
data, never typed against it.

Usage:  python3 scripts/build_timeseries.py [data/panel] [-o data/timeseries.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyse_panel import BANDS, CATS, PIPELINE_BREAK, Panel, band, classify

POOLED = "HPS + FA"
SERIES = {
    "places": "enrolled_places",
    "in_use": "participants_sda_in_use",
    "waiting": "participants_eligible_not_using",
    "spare": "places_not_in_use",
    "pipeline_places": "pipeline_places",
    "pipeline_dwellings": "pipeline_dwellings",
    "dwellings": "enrolled_dwellings",
}


def num(v):
    if v is None:
        return None
    return int(v) if float(v).is_integer() else round(v, 3)


def month(q):
    y, m, _ = q.split("-")
    return f"{['Mar', 'Jun', 'Sep', 'Dec'][int(m) // 3 - 1]} {y}"


def n0(v):
    return f"{v:,.0f}"


def growth_words(start, end):
    """'doubled', 'nearly doubled', 'rose 40%', 'fell 12%'."""
    ratio = end / start
    if ratio >= 1.95:
        return "more than doubled" if ratio >= 2.05 else "doubled"
    if ratio >= 1.8:
        return "nearly doubled"
    return f"{'rose' if ratio > 1 else 'fell'} {abs(ratio - 1):.0%}"


def category_block(p, geo, quarters):
    """Places, need and need with Missing spread pro-rata, per category and for
    the pooled HPS + FA series the substitution toggle shows."""
    out = {}
    for c in CATS:
        places = [p.get(geo, c, "enrolled_places", q) for q in quarters]
        need = [p.get(geo, c, "participants_with_need", q) for q in quarters]
        out[c] = {"places": places, "need": need}
    missing = [p.get(geo, "Missing", "participants_with_need", q) for q in quarters]
    known = [None if any(out[c]["need"][i] is None for c in CATS)
             else sum(out[c]["need"][i] for c in CATS) for i in range(len(quarters))]
    for c in CATS:
        out[c]["need_pro_rata"] = [
            None if n is None or k is None or m is None
            else (n + m * n / k if k else n)
            for n, k, m in zip(out[c]["need"], known, missing)]
    hps, fa = out["High Physical Support"], out["Fully Accessible"]
    out[POOLED] = {
        key: [None if a is None or b is None else a + b for a, b in zip(hps[key], fa[key])]
        for key in ("places", "need", "need_pro_rata")}
    for block in out.values():
        block["status"] = status(block["places"], block["need"])
        for key in ("places", "need", "need_pro_rata"):
            block[key] = [num(v) for v in block[key]]
    return out


def status(places, need):
    pairs = [(a, b) for a, b in zip(places, need) if a is not None and b is not None]
    if not pairs or min(b for _, b in pairs) < 10:
        return "thin"
    return classify([band(a / b) for a, b in pairs])


def ratio_series(block, key="need"):
    return [None if pl is None or n in (None, 0) else round(pl / n, 3)
            for pl, n in zip(block["places"], block[key])]


def waiting_status(series):
    states = [w > s for w, s in zip(series["waiting"], series["spare"])
              if w is not None and s is not None]
    if not states:
        return None
    steps = [b - a for a, b in zip(states, states[1:]) if a != b]
    if not steps:
        return "always short" if states[0] else "always covered"
    if all(s < 0 for s in steps):
        return "short to covered"
    if all(s > 0 for s in steps):
        return "covered to short"
    return "reverses"


# --------------------------------------------------------------------------
# The national story: five sections, each a conclusion and its evidence
# --------------------------------------------------------------------------

def story(p, a, nat, quarters):
    q1, q2, q3 = a["q1"], a["q2"], a["q3"]
    n1 = q1["national"]
    first, last = month(q1["window"][0]), month(q1["window"][1])
    spare0, spare1 = n1["spare"]
    sections = []

    # 1. Supply against use.
    if spare1 > spare0 * 1.1:
        head = f"The surplus is growing: spare places {growth_words(spare0, spare1)} since {first}"
    elif spare1 < spare0 * 0.9:
        head = f"The surplus is shrinking: spare places {growth_words(spare0, spare1)} since {first}"
    else:
        head = f"The surplus is holding steady at about {n0(spare1)} places"
    sections.append({
        "id": "supply",
        "headline": head,
        "evidence": (f"From {first} to {last}, {n0(n1['places_added'])} places were added and "
                     f"{n0(n1['in_use_added'])} more people came to use SDA. "
                     f"{n0(spare1)} places ({n1['spare_share_last']:.0%}) now have no SDA-funded "
                     f"resident."),
        "caveat": "Places not in SDA use is an upper bound on vacancy: a place can be "
                  "occupied by someone not funded for SDA.",
    })

    # 2. Absorption.
    m = q1["models"]
    lo = min(v["sum"] for v in m.values())
    hi = max(v["sum"] for v in m.values())
    pooled = m["pooled"]
    tail = sum(abs(x) for x in pooled["lags"][3:])
    quiet = q1["quiet_regions"]["share_absorbed_in_a_year"]
    if hi < 0.5 and quiet < 0.1:
        head = "It is not a lease-up blip: most new places are not taken up"
    elif hi >= 0.8:
        head = "New places are being taken up: this looks like lease-up"
    else:
        head = "New places are only partly taken up"
    sections.append({
        "id": "absorption",
        "headline": head,
        "evidence": (f"Each new place brings about {pooled['sum']:.2f} people into use "
                     f"({lo:.2f}–{hi:.2f} across specifications), "
                     f"{'almost all within three quarters' if tail < 0.05 else 'spread over a year'}"
                     f". Regions that stopped building absorbed "
                     f"{'under 1%' if quiet < 0.005 else f'{quiet:.0%}'} of their spare places in "
                     f"a year."),
        "caveat": "Region-level: a net change in each region's totals, not dwellings "
                  "followed one by one.",
        "lags": pooled["lags"], "range": [lo, hi],
        "quarters_to_fill_median": q1["regions_summary"]["median_quarters_to_fill"],
    })

    # 3. Categories: as enrolled, and allowing substitution.
    cat_q = q1["category_quarters"]
    idx = [quarters.index(q) for q in cat_q]
    ratios = {c: [ratio_series(nat["categories"][c])[i] for i in idx]
              for c in CATS + [POOLED]}
    pro = {c: [ratio_series(nat["categories"][c], "need_pro_rata")[i] for i in idx]
           for c in CATS + [POOLED]}

    def verdict(c):
        r0, r1 = ratios[c][0], ratios[c][-1]
        b = BANDS[band(r1)]
        rising, falling = r1 > r0 + 0.03, r1 < r0 - 0.03
        if b == "long":
            return "increasingly oversupplied" if rising else "oversupplied"
        if b == "short":
            return "increasingly short" if falling else "short"
        if rising:
            return "balanced but rising"
        return "balanced but falling" if falling else "balanced"

    def cat_head(cats):
        parts = [f"{c} is {verdict(c)}" for c in cats]
        return parts[0] + (", " + ", ".join(parts[1:-1]) if len(parts) > 2 else "") + \
            ("; " + parts[-1] if len(parts) > 1 else "")

    def cat_evidence(cats):
        return "; ".join(f"{c} {ratios[c][0]:.2f} → {ratios[c][-1]:.2f}" for c in cats) + \
            f" places per participant with need, {month(cat_q[0])} to {month(cat_q[-1])}."
    by_ratio = sorted(CATS, key=lambda c: -ratios[c][-1])
    pooled_order = sorted(["Improved Liveability", "Robust", POOLED], key=lambda c: -ratios[c][-1])
    sections.append({
        "id": "categories",
        "headline": {"enrolled": cat_head([by_ratio[0], by_ratio[-1]]),
                     "substitution": cat_head([POOLED] + [c for c in (pooled_order[0],
                                                                  pooled_order[-1])
                                                          if c != POOLED][-1:])},
        "evidence": {"enrolled": cat_evidence(by_ratio),
                     "substitution": cat_evidence(pooled_order)},
        "caveat": (f"A fifth of need has no design category ({q1['missing_share'][-1]:.0%} in "
                   f"{month(cat_q[-1])}). The dashed line spreads it across categories in "
                   f"proportion; the solid line leaves it out."),
        "quarters": cat_q, "ratios": ratios, "ratios_pro_rata": pro,
    })

    # 4. Pipeline.
    rb = q2["removal_at_break"]["Total"]
    own = q2["same_category"]["own"]
    sections.append({
        "id": "pipeline",
        "headline": ("The pipeline overstates what is coming" if own < 0.6
                     else "Most of the pipeline is arriving"),
        "evidence": (f"About {own:.0%} of the pipeline turns into enrolled dwellings each year. "
                     f"The 36-month rule removed at least {n0(rb['lower_bound'])} dwellings in "
                     f"{month(PIPELINE_BREAK)}, {rb['lower_bound_share']:.0%}–"
                     f"{rb['central_share']:.0%} of the pipeline."),
        "caveat": f"Pipeline figures before and after {month(PIPELINE_BREAK)} are not comparable.",
        "flows": q2["flows"], "break": PIPELINE_BREAK,
    })

    # 5. The location mismatch.
    mm = q3["mismatch"]
    s0, s1 = mm[0], mm[-1]
    if s1["regions_short"] < s0["regions_short"] and \
            s1["spare_beyond_local_waiting"] > s1["waiting_beyond_local_spare"]:
        head = "The shortage is turning into an overhang"
    elif s1["regions_short"] > s0["regions_short"]:
        head = "The shortage is spreading"
    else:
        head = "The shortage persists"
    sections.append({
        "id": "mismatch",
        "headline": head,
        "evidence": (f"{s1['regions_short']} regions have more people waiting than spare places, "
                     f"down from {s0['regions_short']} in {month(s0['quarter'])}. Meanwhile "
                     f"{n0(s1['spare_beyond_local_waiting'])} spare places sit in regions that could "
                     f"already house everyone waiting locally, up from "
                     f"{n0(s0['spare_beyond_local_waiting'])}."),
        "caveat": "People waiting are counted where they live, not where they would accept "
                  "a place.",
        "series": mm,
    })
    return sections


def region_summary(record, labels, in_use_from):
    """A region page's headline and evidence, chosen from its own figures.

    The order of the tests is the order of what matters: people waiting beyond
    the spare places first, then which way the spare places are moving."""
    s = record["series"]
    spare, wait, places = s["spare"][-1], s["waiting"][-1], s["places"][-1]
    if not places:
        if wait:
            return {"headline": "There is no enrolled SDA here, and people are waiting",
                    "evidence": f"{wait:,} people are eligible but not yet using SDA, and the "
                                f"region has no enrolled places to offer them."}
        return {"headline": "There is no enrolled SDA here",
                "evidence": "The supplement reports no enrolled places in this region."}
    if spare is None or wait is None:
        return {"headline": "Too little data to measure here",
                "evidence": "Participant figures are not published for this region."}
    spare0 = s["spare"][-5]
    change = spare - spare0
    qtf = record.get("quarters_to_fill")
    since = labels[in_use_from]
    lines = []
    if wait > max(spare, 0):
        head = "More people are waiting here than there are spare places"
        lines.append(f"{wait:,} people are eligible but not yet using SDA, against {max(spare, 0):,} "
                     f"spare places: {wait - max(spare, 0):,} beyond local capacity.")
    else:
        if change > max(5, 0.05 * abs(spare0)):
            head = "The surplus here is growing"
        elif change < -max(5, 0.05 * abs(spare0)):
            head = "The surplus here is shrinking"
        else:
            head = "The surplus here is holding steady"
        lines.append(f"{spare:,} places ({spare / places:.0%}) have no SDA-funded resident, "
                     f"{'up' if change >= 0 else 'down'} {abs(change):,} in a year, against "
                     f"{wait:,} people waiting.")
        if qtf:
            lines.append(f"At last year's take-up it would take {qtf:.0f} quarters to fill them.")
        elif spare > 0:
            lines.append("Nobody was added to SDA use here over the last year.")
    status = record.get("waiting_status")
    if status == "always short":
        lines.append(f"Waiting has exceeded spare places in every quarter since {since}.")
    elif status == "short to covered":
        lines.append(f"Waiting exceeded spare places earlier, but no longer; the series starts {since}.")
    elif status == "covered to short":
        lines.append("Spare places used to cover everyone waiting, and no longer do.")
    return {"headline": head, "evidence": " ".join(lines)}


def add_ranks(geos):
    """National position on spare places and on quarters to fill, 1 = most."""
    sa4 = [g for g, r in geos.items() if r["level"] == "SA4"]
    for key, get in (("spare", lambda r: r["series"]["spare"][-1]),
                     ("quarters_to_fill", lambda r: r.get("quarters_to_fill"))):
        ranked = sorted((g for g in sa4 if get(geos[g]) is not None),
                        key=lambda g: (-get(geos[g]), g))
        for i, g in enumerate(ranked, 1):
            geos[g].setdefault("rank", {})[key] = [i, len(ranked)]


def build(panel_dir: Path):
    p = Panel(panel_dir / "panel.csv")
    a = json.loads((panel_dir / "analysis.json").read_text())
    quarters = p.quarters
    per_region = {r["geography"]: r for r in a["q1"]["regions"]}

    geos = {}
    for geo, (level, state) in sorted(p.geos.items()):
        if level not in ("National", "State", "SA4"):
            continue
        series = {k: [num(p.total(geo, m, q)) for q in quarters] for k, m in SERIES.items()}
        record = {
            "level": level, "state": state or None,
            "name": "Australia" if geo == "national" else geo.split(":", 1)[1].split(" - ", 1)[-1],
            "series": series,
            "categories": category_block(p, geo, quarters),
            "waiting_status": waiting_status(series),
        }
        if geo in per_region:
            r = per_region[geo]
            record["quarters_to_fill"] = r["quarters_to_fill"]
            record["spare_change_per_quarter"] = r["spare_change_per_quarter"]
            record["absorbed_per_quarter"] = r["absorbed_per_quarter"]
        if level == "SA4":
            record.update(region_summary(record, [month(q) for q in quarters],
                                         quarters.index(a["q1"]["window"][0])))
        geos[geo] = record

    add_ranks(geos)
    nat = geos["national"]
    return {
        "meta": {
            "quarters": quarters,
            "labels": [month(q) for q in quarters],
            "in_use_from": a["q1"]["window"][0],
            "need_from": a["q1"]["category_quarters"][0],
            "pipeline_break": PIPELINE_BREAK,
            "categories": CATS, "pooled": POOLED,
            "source": "NDIA Supplement P, 13 editions; see data/panel/VALIDATION.md",
        },
        "story": story(p, a, nat, quarters),
        "geographies": geos,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("panel_dir", type=Path, nargs="?", default=Path("data/panel"))
    parser.add_argument("-o", "--out", type=Path, default=Path("data/timeseries.json"))
    args = parser.parse_args()
    bundle = build(args.panel_dir)
    args.out.write_text(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False))
    print(f"wrote {args.out}  ({args.out.stat().st_size / 1024:.0f} KB, "
          f"{len(bundle['geographies'])} geographies)")
    for s in bundle["story"]:
        head = s["headline"] if isinstance(s["headline"], str) else s["headline"]["enrolled"]
        print(f"  {s['id']:11} {head}")


if __name__ == "__main__":
    main()
