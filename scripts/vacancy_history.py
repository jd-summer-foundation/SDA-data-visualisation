#!/usr/bin/env python3
"""Build a longitudinal vacancy store from repeated Housing Hub exports.

A single export is a stock, not a flow: it says 3,753 places are vacant today
but nothing about how long any of them has been vacant. Two or more exports of
the same platform, taken at different dates, do carry that information — if the
same dwelling can be recognised across them. This module does the recognising,
and derives vacancy *spells* from the result.

Identity is the hard part, and it is resolved at two levels because no single
key works for every row:

1. **Listing.** The Housing Hub property URL ends in a per-listing token
   (`.../clyde-vic/14732/34l2q`). Where present — 86-88% of rows — it is the
   natural longitudinal unit. It is *not* durable: a provider who unpublishes
   and relists the same dwelling gets a new token, which reads as an exit
   followed by an arrival. `link_relisting` repairs that.
2. **Cluster.** Provider, location, building type and design category together
   identify a *set* of interchangeable dwellings — often exactly one, but up to
   14 where a provider holds many identical apartments in one block. Individual
   dwellings within a cluster cannot be told apart and are not tracked
   separately; the cluster's vacant-place count is tracked instead. This covers
   the rows that carry no token at all.

Spells are derived per listing. A spell is a maximal run of consecutive
snapshots in which the listing shows at least one vacant place. Spells are
marked left-censored when the listing is already vacant in the first snapshot
that observes it (its true start is unknown and earlier), and right-censored
when it is still vacant in the final snapshot. Both flags matter: analysing
uncensored spells alone would keep only vacancies that both began and ended
inside the observation window, which are systematically the short ones.

The store never rewrites history. Snapshots are append-only and each is derived
from the source export alone; `dwellings.csv` and `spells.csv` are recomputed
from the full snapshot set on every build, so improving the linkage logic
improves the past as well as the future.

Contact details are dropped at ingest. The source exports carry `Email`,
`Phone` and `Website 1`-`5`; only the URL token survives, as an opaque
identifier. See data/README.md — everything under data/ is published.

Usage:
    python3 scripts/vacancy_history.py ingest <export> --date YYYY-MM-DD [--store store/]
    python3 scripts/vacancy_history.py build [--store store/]
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

# The canonical snapshot columns. Source exports drift — the 2026-05 export
# carries `Capacity` and `% vacancy` that the 2026-08 one does not — so ingest
# normalises to this set and derives what a given export omits.
SNAPSHOT_FIELDS = [
    "snapshot_date",
    "token",
    "cluster_key",
    "provider",
    "provider_norm",
    "location",
    "state",
    "postcode",
    "suburb",
    "building_type",
    "design_category",
    "capacity",
    "vacancy",
    "whole_dwelling",
    "price",
    "fire_sprinklers",
    "breakout_room",
    "onsite_overnight",
]

# "House, 3 residents", "Apartment, 2 bedroom, 1 resident". Resident count is
# always last. Mirrors extract_vacancies.BUILDING_TYPE.
BUILDING_TYPE = re.compile(r"^(?P<form>[^,]+),.*?(?P<residents>\d+)\+?\s*residents?$")

# "Clyde VIC 3978".
LOCATION = re.compile(
    r"^(?P<suburb>.+?)\s+(?P<state>NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s+(?P<postcode>\d{4})$"
)

# Corporate groups that list under more than one legal entity. Matching is on
# an uppercased substring of the provider name. Kept deliberately short: only
# groups confirmed to be the same operator, not merely similar-sounding.
PROVIDER_GROUPS = {
    "ENLIVEN": "Enliven Housing",
    "SUMMER HOUSING": "Summer Housing",
    "HOUSING CHOICES": "Housing Choices",
    "ARUMA": "Aruma",
    "COMMUNITY HOUSING (VIC)": "Community Housing Ltd",
    "COMMUNITY HOUSING LTD": "Community Housing Ltd",
}

# Trailing legal-form words to strip before comparing provider names.
LEGAL_SUFFIX = re.compile(r"\s+(PTY LTD|PTY LIMITED|PTY|LTD|LIMITED|INC|INCORPORATED)$")

# Columns holding contact details. Dropped at ingest and never written.
CONTACT_COLUMNS = {"Email", "Phone", "Website 2", "Website 3", "Website 4", "Website 5"}


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def norm_text(value) -> str:
    """Uppercase, collapse whitespace. The basis of every comparison key."""
    return re.sub(r"\s+", " ", str(value or "").upper().strip())


def norm_provider(name) -> str:
    """Resolve a provider name to its corporate group, where one is known.

    Housing Hub records the listing account, which for a group that lists under
    several entities means the same operator appears under several names. The
    mapping is conservative; anything unmatched is merely cleaned.
    """
    text = norm_text(name)
    for needle, label in PROVIDER_GROUPS.items():
        if needle in text:
            return norm_text(label)
    text = re.sub(r"^[-\s]+", "", text)
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    previous = None
    while previous != text:
        previous = text
        text = LEGAL_SUFFIX.sub("", text)
    return text


def url_token(url) -> str:
    """Return the per-listing token ending a Housing Hub property URL.

    `https://www.housinghub.org.au/property-detail/sda/<provider>/<suburb>/<provider-id>/<token>`
    Returns "" for the 12-14% of rows that carry a provider's own site instead,
    or no URL at all.
    """
    text = str(url or "").split("?")[0].rstrip("/")
    if "housinghub.org.au/property-detail" not in text.lower():
        return ""
    segments = text.split("/property-detail/", 1)[1].split("/")
    return segments[-1].lower() if segments else ""


def parse_capacity(building_type) -> int:
    """Resident capacity named by the building type, or 0 when unparseable."""
    match = BUILDING_TYPE.match(str(building_type or "").strip())
    return int(match.group("residents")) if match else 0


def parse_number(value) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse_flag(value) -> int:
    text = str(value or "").strip().lower()
    return 1 if text in {"1", "true", "yes", "y"} else 0


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------


def read_export(path: Path) -> list[dict]:
    """Read a Housing Hub export, CSV or legacy .xls, as a list of dicts."""
    if path.suffix.lower() in {".csv", ".txt"}:
        with io.open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    try:
        import pandas
    except ImportError:
        sys.exit(
            f"{path.name} is a spreadsheet; reading it needs pandas and xlrd.\n"
            "Either `pip install pandas xlrd`, or save the file as CSV first."
        )
    frame = pandas.read_excel(path)
    return [
        {key: ("" if value != value else value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def normalise_row(row: dict, snapshot: str) -> dict | None:
    """Turn one export row into a canonical snapshot row.

    Returns None for rows with no usable vacancy, which the export occasionally
    carries. Contact columns are read but never written.
    """
    vacancy = int(parse_number(row.get("Vacancy")))
    if vacancy <= 0:
        return None

    location = str(row.get("Location") or "").strip()
    match = LOCATION.match(location)
    suburb = match.group("suburb") if match else location
    state = match.group("state") if match else ""
    postcode = match.group("postcode") if match else ""

    building_type = str(row.get("Building Type") or "").strip()
    # The 2026-05 export states Capacity directly; the 2026-08 one does not, so
    # it is derived from the building type. Prefer the stated value where given.
    capacity = int(parse_number(row.get("Capacity"))) or parse_capacity(building_type)

    provider = str(row.get("Name") or "").strip()
    provider_norm = norm_provider(provider)
    design_category = str(row.get("SDA Design Category") or "").strip()

    # Identifies a set of interchangeable dwellings, not necessarily one.
    cluster_key = "|".join(
        (
            provider_norm,
            norm_text(location),
            norm_text(building_type),
            norm_text(design_category),
        )
    )

    return {
        "snapshot_date": snapshot,
        "token": url_token(row.get("Website 1")),
        "cluster_key": cluster_key,
        "provider": provider,
        "provider_norm": provider_norm,
        "location": location,
        "state": state,
        "postcode": postcode,
        "suburb": suburb,
        "building_type": building_type,
        "design_category": design_category,
        "capacity": capacity,
        "vacancy": vacancy,
        # The measure the export does not state, matching extract_vacancies.py:
        # whether the whole dwelling is empty or only a room within it.
        "whole_dwelling": 1 if capacity and vacancy >= capacity else 0,
        "price": round(parse_number(row.get("Max Price Per Room")), 2),
        "fire_sprinklers": parse_flag(row.get("Has Fire Sprinklers")),
        "breakout_room": parse_flag(row.get("Has Breakout Room")),
        "onsite_overnight": parse_flag(row.get("Onsite Overnight Assistance")),
    }


def ingest(source: Path, snapshot: str, store: Path) -> Path:
    """Write one normalised, contact-free snapshot into the store."""
    try:
        datetime.strptime(snapshot, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"--date must be YYYY-MM-DD, got {snapshot!r}")

    rows = read_export(source)
    dropped = set(rows[0]) & CONTACT_COLUMNS if rows else set()
    normalised = [r for r in (normalise_row(row, snapshot) for row in rows) if r]

    target = store / "snapshots" / f"{snapshot}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_FIELDS)
        writer.writeheader()
        writer.writerows(normalised)

    places = sum(r["vacancy"] for r in normalised)
    tokens = sum(1 for r in normalised if r["token"])
    print(f"{source.name} -> {target}")
    print(f"  {len(normalised)} listings, {places} vacant places")
    print(f"  {tokens} carry a Housing Hub token ({tokens / max(1, len(normalised)):.1%})")
    if dropped:
        print(f"  dropped contact columns: {', '.join(sorted(dropped))}")
    return target


# --------------------------------------------------------------------------
# Linkage
# --------------------------------------------------------------------------


def load_snapshots(store: Path) -> tuple[list[str], dict[str, list[dict]]]:
    """Load every snapshot in the store, oldest first."""
    files = sorted((store / "snapshots").glob("*.csv"))
    if not files:
        sys.exit(f"No snapshots in {store / 'snapshots'}. Run `ingest` first.")
    dates, by_date = [], {}
    for path in files:
        with io.open(path, encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            for key in ("capacity", "vacancy", "whole_dwelling",
                        "fire_sprinklers", "breakout_room", "onsite_overnight"):
                row[key] = int(row[key] or 0)
            row["price"] = float(row["price"] or 0)
        dates.append(path.stem)
        by_date[path.stem] = rows
    return dates, by_date


def link_relisting(dates: list[str], by_date: dict[str, list[dict]]) -> dict[str, str]:
    """Map each token to a durable listing id, merging relisted dwellings.

    A provider who unpublishes and republishes a dwelling gets a fresh token.
    Left alone that reads as one vacancy ending and an unrelated one starting,
    which shortens every spell it touches. The repair: when a token disappears
    between consecutive snapshots and a *new* token appears in the same cluster,
    treat the new token as a continuation of the old.

    Matching is within-cluster and count-limited — at most as many continuations
    as there were departures — so a cluster that genuinely lost two dwellings and
    gained five yields two continuations and three arrivals, not five.
    """
    parent: dict[str, str] = {}

    def find(token: str) -> str:
        parent.setdefault(token, token)
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    seen: dict[str, set[str]] = defaultdict(set)  # cluster -> tokens seen so far
    for index, snapshot in enumerate(dates):
        present: dict[str, set[str]] = defaultdict(set)
        for row in by_date[snapshot]:
            if row["token"]:
                present[row["cluster_key"]].add(row["token"])

        if index:
            for cluster, tokens in present.items():
                arrivals = sorted(tokens - seen[cluster])
                departures = sorted(seen[cluster] - tokens)
                # Pair them off deterministically. Any excess on either side is a
                # genuine arrival or departure and is left alone.
                for arrival, departure in zip(arrivals, departures):
                    union(departure, arrival)

        for cluster, tokens in present.items():
            seen[cluster] |= tokens

    return {token: find(token) for token in parent}


def build_series(
    dates: list[str],
    by_date: dict[str, list[dict]],
    listing_of: dict[str, str],
) -> dict[str, dict[str, dict]]:
    """Collapse snapshots into one observation per listing per date.

    Listings carrying a token become their own series. Listings without one are
    pooled into a cluster-level series — individually indistinguishable, but
    their combined vacant-place count is still a real time series.
    """
    series: dict[str, dict[str, dict]] = defaultdict(dict)
    for snapshot in dates:
        pooled: dict[str, dict] = {}
        for row in by_date[snapshot]:
            if row["token"]:
                key = "listing:" + listing_of.get(row["token"], row["token"])
                existing = series[key].get(snapshot)
                if existing:
                    existing["vacancy"] += row["vacancy"]
                else:
                    series[key][snapshot] = dict(row, tracked="listing")
                continue
            key = "cluster:" + row["cluster_key"]
            if key in pooled:
                pooled[key]["vacancy"] += row["vacancy"]
                pooled[key]["listings"] += 1
            else:
                pooled[key] = dict(row, tracked="cluster", listings=1)
        for key, row in pooled.items():
            series[key][snapshot] = row
    return series


def derive_spells(dates: list[str], series: dict[str, dict[str, dict]]) -> list[dict]:
    """Turn each listing's observation series into vacancy spells.

    A spell runs from the first snapshot showing a vacancy to the last
    consecutive one that still does. Because snapshots are periodic, a spell's
    true boundaries lie somewhere in the gaps either side: the observed duration
    is a lower bound, and `days_max` gives the upper one.
    """
    position = {snapshot: index for index, snapshot in enumerate(dates)}
    as_date = {s: datetime.strptime(s, "%Y-%m-%d").date() for s in dates}
    spells = []

    for key, observations in series.items():
        observed = sorted(observations, key=lambda s: position[s])
        run: list[str] = []
        for snapshot in observed + [None]:
            # A run breaks at the end, or when the next observation is not the
            # immediately following snapshot — a gap means the listing was absent.
            contiguous = (
                snapshot is not None
                and run
                and position[snapshot] == position[run[-1]] + 1
            )
            if snapshot is not None and (not run or contiguous):
                run.append(snapshot)
                continue
            if run:
                spells.append(close_spell(key, run, observations, dates, position, as_date))
            run = [snapshot] if snapshot is not None else []
    return spells


def close_spell(key, run, observations, dates, position, as_date) -> dict:
    """Assemble one spell record from a contiguous run of observations."""
    first, last = run[0], run[-1]
    row = observations[last]
    first_index, last_index = position[first], position[last]

    # Left-censored when the spell is already under way at the listing's first
    # appearance in the store: it may have begun long before.
    left_censored = first_index == 0
    # Right-censored when it is still open at the last snapshot.
    right_censored = last_index == len(dates) - 1

    observed_days = (as_date[last] - as_date[first]).days
    # The vacancy began after the previous snapshot and ended before the next,
    # so the true duration lies between these bounds.
    lower = as_date[dates[first_index - 1]] if first_index else None
    upper = as_date[dates[last_index + 1]] if not right_censored else None
    days_max = ((upper or as_date[last]) - (lower or as_date[first])).days

    return {
        "series_id": key,
        "tracked": row.get("tracked", "listing"),
        "provider": row["provider"],
        "provider_norm": row["provider_norm"],
        "location": row["location"],
        "state": row["state"],
        "postcode": row["postcode"],
        "suburb": row["suburb"],
        "design_category": row["design_category"],
        "building_type": row["building_type"],
        "capacity": row["capacity"],
        "whole_dwelling": row["whole_dwelling"],
        "price": row["price"],
        "fire_sprinklers": row["fire_sprinklers"],
        "breakout_room": row["breakout_room"],
        "onsite_overnight": row["onsite_overnight"],
        "vacancy_first": observations[first]["vacancy"],
        "vacancy_last": row["vacancy"],
        "first_seen": first,
        "last_seen": last,
        "snapshots": len(run),
        "days_observed": observed_days,
        "days_max": days_max,
        "left_censored": int(left_censored),
        "right_censored": int(right_censored),
        # Usable in a survival model without censoring adjustment only when both
        # ends fall inside the window. With few snapshots this will be near-zero,
        # which is the honest signal that duration estimates must wait.
        "complete": int(not left_censored and not right_censored),
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(store: Path) -> None:
    """Recompute listings and spells from every snapshot in the store."""
    dates, by_date = load_snapshots(store)
    listing_of = link_relisting(dates, by_date)
    series = build_series(dates, by_date, listing_of)
    spells = derive_spells(dates, series)

    spell_fields = list(spells[0]) if spells else []
    write_csv(store / "spells.csv", spells, spell_fields)

    dwellings = [
        {
            "series_id": key,
            "tracked": next(iter(obs.values())).get("tracked", "listing"),
            "provider_norm": next(iter(obs.values()))["provider_norm"],
            "location": next(iter(obs.values()))["location"],
            "first_seen": min(obs, key=lambda s: dates.index(s)),
            "last_seen": max(obs, key=lambda s: dates.index(s)),
            "observations": len(obs),
        }
        for key, obs in series.items()
    ]
    write_csv(
        store / "dwellings.csv",
        dwellings,
        ["series_id", "tracked", "provider_norm", "location",
         "first_seen", "last_seen", "observations"],
    )

    report(dates, by_date, series, spells, listing_of)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def report(dates, by_date, series, spells, listing_of) -> None:
    """Print what the store currently supports, and what it does not yet."""
    print(f"\nSnapshots: {len(dates)}  ({dates[0]} to {dates[-1]})")
    for snapshot in dates:
        rows = by_date[snapshot]
        print(f"  {snapshot}  {len(rows):>5} listings  "
              f"{sum(r['vacancy'] for r in rows):>5} vacant places")

    merged = len(listing_of) - len(set(listing_of.values()))
    tracked = Counter(s["tracked"] for s in spells)
    print(f"\nSeries: {len(series)}  "
          f"({tracked['listing']} listing-level spells, {tracked['cluster']} cluster-level)")
    print(f"Relisting repairs: {merged} tokens merged into an earlier listing")

    if len(dates) < 2:
        print("\nOne snapshot only — no spells can be measured yet.")
        return

    complete = [s for s in spells if s["complete"]]
    left = sum(1 for s in spells if s["left_censored"])
    right = sum(1 for s in spells if s["right_censored"])
    print(f"\nSpells: {len(spells)}")
    print(f"  left-censored (began before the window)  : {left}")
    print(f"  right-censored (still open at the end)   : {right}")
    print(f"  complete (both ends observed)            : {len(complete)}")

    # Exit rate between the first and last snapshot, which is what a two-snapshot
    # store can honestly support. A full survival curve needs more.
    first, last = dates[0], dates[-1]
    opening = [k for k, obs in series.items() if first in obs]
    survived = [k for k in opening if last in obs_of(series, k)]
    span = (datetime.strptime(last, "%Y-%m-%d") - datetime.strptime(first, "%Y-%m-%d")).days
    if opening:
        exit_rate = 1 - len(survived) / len(opening)
        print(f"\nOver {span} days, {len(opening)} series open at {first}:")
        print(f"  still open at {last}: {len(survived)} ({len(survived) / len(opening):.1%})")
        print(f"  exit rate: {exit_rate:.1%}")
        if 0 < exit_rate < 1:
            import math
            hazard = -math.log(1 - exit_rate) / span
            print(f"  implied median spell at constant hazard: "
                  f"{math.log(2) / hazard:,.0f} days (~{math.log(2) / hazard / 30.4:.1f} months)")
            print("  NB: a prevalent cohort over-samples long spells, so this is an"
                  "\n      upper bound. Treat it as indicative until incident spells accrue.")


def obs_of(series, key):
    return series[key]


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="add one export to the store")
    p_ingest.add_argument("source", type=Path)
    p_ingest.add_argument("--date", required=True, help="snapshot date, YYYY-MM-DD")
    p_ingest.add_argument("--store", type=Path, default=Path("store"))

    p_build = sub.add_parser("build", help="recompute listings and spells")
    p_build.add_argument("--store", type=Path, default=Path("store"))

    args = parser.parse_args()
    if args.command == "ingest":
        ingest(args.source, args.date, args.store)
    else:
        build(args.store)


if __name__ == "__main__":
    main()
