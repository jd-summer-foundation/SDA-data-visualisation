#!/usr/bin/env python3
"""Turn the ABS SA4 boundaries into the small pre-projected geometry the
explorer draws.

The site has no build step and no runtime dependencies, so the map cannot
project or decode anything in the browser. Everything expensive happens here:
the shapefile is reprojected to an equal-area conic, simplified with topology
preserved, fitted to a pixel box and written out as ready-to-draw SVG path
strings keyed by the same region ids `data/sda.json` already uses.

Two things are done rather than assumed:

* Simplification runs through mapshaper, not shapely. Shapely simplifies each
  polygon independently, so shared borders drift apart and leave slivers
  between neighbours. mapshaper simplifies the shared arcs instead.
* The join to the NDIA data is by region *name* -- Supplement P publishes no
  SA4 code -- so it is asserted exactly, in both directions, and the build
  fails rather than quietly dropping a region off the map.

    npm i mapshaper
    python3 scripts/build_geometry.py [SA4_....shp]
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SHP = os.path.join(HERE, "data", "boundaries", "SA4_2026_AUST_GDA2020.shp")
SDA_JSON = os.path.join(HERE, "data", "sda.json")
OUT_JSON = os.path.join(HERE, "data", "sa4-geometry.json")

# GDA94 Australian Albers. The source is GDA2020, but both sit on GRS80 and the
# datum shift is about 1.8 m -- far below the resolution of a simplified
# national map. Equal-area is the point: it stops the outback SA4s reading as
# more important than they are simply for being enormous.
PROJECTION = "EPSG:3577"

# Share of vertices kept. Insets keep more: they cover a tiny area where the
# national setting would reduce a suburb to a triangle.
SIMPLIFY_NATIONAL = "1.5%"
SIMPLIFY_INSET = "8%"

WIDTH_NATIONAL = 960
WIDTH_INSET = 430

# Greater Capital City areas worth an inset. The other three capitals
# (Hobart, Darwin, Canberra) are a single SA4 each, so an inset would show
# nothing the national map does not.
INSETS = ["Greater Sydney", "Greater Melbourne", "Greater Brisbane",
          "Greater Perth", "Greater Adelaide"]

# Codes ending 97/99 are Migratory - Offshore - Shipping and No usual address;
# 9xx is Other Territories and ZZZ is Outside Australia. None appear in
# Supplement P.
REAL_SA4 = "!/(97|99)$/.test(SA4_CODE26) && !/^(9|Z)/.test(SA4_CODE26)"

STATE_ABBR = {
    "New South Wales": "NSW", "Victoria": "VIC", "Queensland": "QLD",
    "South Australia": "SA", "Western Australia": "WA", "Tasmania": "TAS",
    "Northern Territory": "NT", "Australian Capital Territory": "ACT",
}
EXPECTED_PER_STATE = {"NSW": 28, "VIC": 17, "QLD": 19, "SA": 7,
                      "WA": 10, "TAS": 4, "NT": 2, "ACT": 1}


def die(msg):
    sys.exit("error: " + msg)


def mapshaper(args):
    exe = shutil.which("mapshaper") or shutil.which("npx")
    if exe is None:
        die("mapshaper not found. Run: npm i mapshaper")
    cmd = ([exe, "mapshaper"] if exe.endswith("npx") else [exe]) + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        die("mapshaper failed:\n" + (proc.stderr or proc.stdout))
    return proc.stderr


def run_view(shp, tmp, tag, where, simplify):
    """Reproject, simplify and export one view as three GeoJSON layers.

    The fills, the shared-border mesh and the coastline all come out of the
    same simplification pass, so they cannot disagree by a pixel. Fills are
    drawn unstroked with the mesh on top -- pre-baked path strings overlap on
    every shared border, and stroking them individually double-draws each one.
    """
    base = [shp, "-filter", where]
    regions = os.path.join(tmp, tag + "-regions.json")
    mesh = os.path.join(tmp, tag + "-mesh.json")
    outline = os.path.join(tmp, tag + "-outline.json")

    mapshaper(base + [
        "-proj", PROJECTION,
        "-simplify", "visvalingam", "weighted", simplify, "keep-shapes",
        "-clean",
        "-o", regions, "format=geojson",
        "-innerlines",
        "-o", mesh, "format=geojson",
    ])
    mapshaper(base + [
        "-proj", PROJECTION,
        "-simplify", "visvalingam", "weighted", simplify, "keep-shapes",
        "-clean", "-dissolve2",
        "-o", outline, "format=geojson",
    ])
    return (json.load(open(regions)), json.load(open(mesh)),
            json.load(open(outline)))


def rings(geom):
    """Every coordinate ring in a geometry, whatever its type."""
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return list(c)
    if t == "MultiPolygon":
        return [r for poly in c for r in poly]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    return []


def bounds(features):
    xs0 = ys0 = float("inf")
    xs1 = ys1 = float("-inf")
    for f in features:
        if not f.get("geometry"):
            continue
        for ring in rings(f["geometry"]):
            for x, y in ring:
                xs0, xs1 = min(xs0, x), max(xs1, x)
                ys0, ys1 = min(ys0, y), max(ys1, y)
    return xs0, ys0, xs1, ys1


def make_fit(box, width):
    """Projected metres to SVG pixels, y flipped (SVG counts down)."""
    x0, y0, x1, y1 = box
    scale = width / (x1 - x0)
    height = round((y1 - y0) * scale, 1)

    def path(geom, close):
        out = []
        for ring in rings(geom):
            pts = ["%s%.1f,%.1f" % ("M" if i == 0 else "L",
                                    (x - x0) * scale, (y1 - y) * scale)
                   for i, (x, y) in enumerate(ring)]
            if pts:
                out.append("".join(pts) + ("Z" if close else ""))
        return "".join(out)

    return path, height


def build_view(shp, tmp, tag, where, simplify, width):
    regions, mesh, outline = run_view(shp, tmp, tag, where, simplify)
    feats = [f for f in regions["features"] if f.get("geometry")]
    if not feats:
        die("no features for view " + tag)

    path, height = make_fit(bounds(feats), width)
    ids = {}
    for f in feats:
        p = f["properties"]
        state = STATE_ABBR.get(p["STE_NAME26"])
        if state is None:
            die("unmapped state name %r" % p["STE_NAME26"])
        ids["sa4:%s - %s" % (state, p["SA4_NAME26"])] = path(f["geometry"], True)

    join = lambda fc: "".join(path(f["geometry"], False)
                              for f in fc["features"] if f.get("geometry"))
    return {
        "width": width,
        "height": height,
        "regions": ids,
        "mesh": join(mesh),
        "outline": "".join(path(f["geometry"], True)
                           for f in outline["features"] if f.get("geometry")),
    }


def main():
    shp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SHP
    if not os.path.exists(shp):
        die("shapefile not found: %s\n"
            "       Place the ABS SA4 boundaries there, or pass a path.\n"
            "       A shapefile needs .shp, .shx, .dbf and .prj together." % shp)
    for ext in (".shx", ".dbf", ".prj"):
        side = re.sub(r"\.shp$", ext, shp)
        if not os.path.exists(side):
            die("missing sidecar %s -- a shapefile is not just the .shp" % side)

    sda = json.load(open(SDA_JSON))
    expected = {g["id"] for g in sda["geographies"]
                if g["level"] == "SA4" and g["name"] != "Other"}

    with tempfile.TemporaryDirectory() as tmp:
        views = {"national": build_view(shp, tmp, "national", REAL_SA4,
                                        SIMPLIFY_NATIONAL, WIDTH_NATIONAL)}
        for gcc in INSETS:
            where = '%s && GCC_NAME26 === "%s"' % (REAL_SA4, gcc)
            views["gccsa:" + gcc] = build_view(
                shp, tmp, gcc.replace(" ", "-"), where,
                SIMPLIFY_INSET, WIDTH_INSET)

    got = set(views["national"]["regions"])

    # The whole map hangs on this join, so prove it rather than trust it.
    missing, extra = sorted(expected - got), sorted(got - expected)
    if missing or extra:
        for i in missing:
            print("  in sda.json, no boundary: " + i, file=sys.stderr)
        for i in extra:
            print("  boundary with no sda.json row: " + i, file=sys.stderr)
        die("SA4 name join is not 1:1 (%d missing, %d extra)"
            % (len(missing), len(extra)))

    per_state = {}
    for i in got:
        per_state[i.split(":")[1].split(" - ")[0]] = \
            per_state.get(i.split(":")[1].split(" - ")[0], 0) + 1
    if per_state != EXPECTED_PER_STATE:
        die("per-state counts changed: %r" % per_state)

    out = {
        "meta": {
            "source": os.path.basename(shp),
            "edition": "ASGS Edition 4 (2026), GDA2020",
            "licence": "ABS, CC BY 4.0",
            "projection": PROJECTION,
            "simplify": {"national": SIMPLIFY_NATIONAL, "inset": SIMPLIFY_INSET},
            "sda_as_at": sda["meta"]["as_at"],
        },
        "views": views,
    }
    with open(OUT_JSON, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))

    size = os.path.getsize(OUT_JSON)
    print("wrote %s  %.0f KB" % (os.path.relpath(OUT_JSON, HERE), size / 1024))
    print("  join      88/88 SA4 regions matched, both directions")
    print("  national  %d regions, %dx%.0f" % (len(got), views["national"]["width"],
                                               views["national"]["height"]))
    for gcc in INSETS:
        v = views["gccsa:" + gcc]
        print("  inset     %-18s %d regions" % (gcc, len(v["regions"])))
    covered = sum(len(views["gccsa:" + g]["regions"]) for g in INSETS)
    print("  %d of %d regions appear in an inset" % (covered, len(got)))


if __name__ == "__main__":
    main()
