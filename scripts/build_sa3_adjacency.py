#!/usr/bin/env python3
"""Derive which SA3s share a border, from the ABS ASGS 2021 SA3 shapefile.

The shapefile (raw/abs/asgs/, ~50 MB) is not committed; this writes the small
pair list that is. A plain-stdlib shapefile reader is enough: SA3s are built
from mesh blocks, so neighbours share their border vertices exactly, and two
SA3s are adjacent when they share at least one polygon *edge* -- the same pair
of consecutive vertices. SA3s that meet only at a corner point share no edge
and are not counted. Water is not land: SA3s facing each other across a bay
or harbour are not adjacent unless the boundary runs through it.

Usage:  python3 scripts/build_sa3_adjacency.py [SA3_2021_AUST_GDA2020.shp] [-o data/abs]

Writes sa3_adjacency.csv: one row per adjacent pair of the 336 Supplement P
SA3s (joined on ASGS 2021 codes via data/panel/sa3_sa4.csv), with each side's
SA4, whether the pair crosses an SA4 boundary, and the shared border length.
"""
from __future__ import annotations

import argparse
import csv
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHP = ROOT / "raw" / "abs" / "asgs" / "SA3_2021" / "SA3_2021_AUST_GDA2020.shp"
EARTH_KM = 6371.0088
# Vertices are compared after rounding to 1e-7 degrees (about 1 cm), which
# absorbs nothing but floating-point noise.
SCALE = 10_000_000


def read_dbf(path: Path):
    with open(path, "rb") as fh:
        head = fh.read(32)
        count, header_len, record_len = struct.unpack("<IHH", head[4:12])
        fields = []
        while True:
            d = fh.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].rstrip(b"\0").decode("ascii"), d[16]))
        fh.seek(header_len)
        rows = []
        for _ in range(count):
            rec = fh.read(record_len)
            pos, row = 1, {}
            for name, size in fields:
                row[name] = rec[pos:pos + size].decode("utf-8", "replace").strip()
                pos += size
            rows.append(row)
    return rows


def read_polygons(path: Path):
    """[[ring, ...] or None] per record; each ring a list of (x, y) ints."""
    out = []
    with open(path, "rb") as fh:
        fh.seek(100)
        while True:
            head = fh.read(8)
            if len(head) < 8:
                break
            _, length = struct.unpack(">ii", head)
            content = fh.read(length * 2)
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type == 0:
                out.append(None)
                continue
            if shape_type not in (5, 15, 25):
                raise ValueError(f"unexpected shape type {shape_type}")
            n_parts, n_points = struct.unpack("<ii", content[36:44])
            parts = list(struct.unpack(f"<{n_parts}i", content[44:44 + 4 * n_parts]))
            start = 44 + 4 * n_parts
            coords = struct.unpack(f"<{2 * n_points}d", content[start:start + 16 * n_points])
            pts = [(round(coords[2 * i] * SCALE), round(coords[2 * i + 1] * SCALE))
                   for i in range(n_points)]
            parts.append(n_points)
            out.append([pts[parts[i]:parts[i + 1]] for i in range(n_parts)])
    return out


def edge_km(a, b) -> float:
    lon1, lat1 = a[0] / SCALE, a[1] / SCALE
    lon2, lat2 = b[0] / SCALE, b[1] / SCALE
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return EARTH_KM * math.hypot(x, y)


def adjacency(shp: Path):
    records = read_dbf(shp.with_suffix(".dbf"))
    polygons = read_polygons(shp)
    if len(records) != len(polygons):
        raise ValueError("shapefile and dbf disagree on the record count")
    owners = {}  # edge -> first owner; a second owner makes a shared edge
    shared = defaultdict(float)
    for rec, rings in zip(records, polygons):
        if rings is None:
            continue
        code = rec["SA3_CODE21"]
        for ring in rings:
            for a, b in zip(ring, ring[1:]):
                if a == b:
                    continue
                edge = (a, b) if a < b else (b, a)
                other = owners.get(edge)
                if other is None:
                    owners[edge] = code
                elif other != code:
                    pair = (other, code) if other < code else (code, other)
                    shared[pair] += edge_km(a, b)
    return records, shared


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("shp", nargs="?", default=str(DEFAULT_SHP))
    ap.add_argument("-o", "--out", default=str(ROOT / "data" / "abs"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with open(ROOT / "data" / "panel" / "sa3_sa4.csv", newline="") as fh:
        panel = {r["sa3_code"]: r for r in csv.DictReader(fh)}
    records, shared = adjacency(Path(args.shp))
    by_code = {r["SA3_CODE21"]: r for r in records}
    missing = sorted(set(panel) - set(by_code))
    if missing:
        raise ValueError(f"panel SA3s with no boundary: {missing}")
    for code, row in panel.items():
        if by_code[code]["SA4_CODE21"] != row["sa4_code"]:
            raise ValueError(f"SA3 {code}: shapefile SA4 {by_code[code]['SA4_CODE21']} "
                             f"!= panel SA4 {row['sa4_code']}")

    kept = sorted(p for p in shared if p[0] in panel and p[1] in panel)
    with open(out / "sa3_adjacency.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sa3_a", "sa3_code_a", "sa4_a", "sa3_b", "sa3_code_b", "sa4_b",
                    "cross_sa4", "shared_km"])
        for a, b in kept:
            ra, rb = panel[a], panel[b]
            w.writerow([ra["sa3"], a, ra["sa4"], rb["sa3"], b, rb["sa4"],
                        "yes" if ra["sa4"] != rb["sa4"] else "no", f"{shared[(a, b)]:.2f}"])
    cross = sum(panel[a]["sa4"] != panel[b]["sa4"] for a, b in kept)
    print(f"{len(kept)} adjacent pairs among {len(panel)} SA3s, {cross} across SA4s; "
          f"{len(shared) - len(kept)} pairs involve SA3s outside Supplement P", file=sys.stderr)


if __name__ == "__main__":
    main()
