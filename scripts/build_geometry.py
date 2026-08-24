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
DEFAULT_SHP = os.path.join(HERE, "data", "boundaries", "SA4_small.shp")
SDA_JSON = os.path.join(HERE, "data", "sda.json")
OUT_JSON = os.path.join(HERE, "data", "sa4-geometry.json")

# GDA94 Australian Albers. The source is GDA2020, but both sit on GRS80 and the
# datum shift is about 1.8 m -- far below the resolution of a simplified
# national map. Equal-area is the point: it stops the outback SA4s reading as
# more important than they are simply for being enormous.
PROJECTION = "EPSG:3577"

# Share of vertices kept, relative to whatever comes in. Insets keep far more:
# they cover a tiny area where the national setting would reduce a whole
# suburb to a triangle. Retune these if the input is pre-simplified -- the
# percentages are relative to the source, not to ABS full detail.
SIMPLIFY_NATIONAL = "2%"
SIMPLIFY_INSET = "12%"

# Coordinate decimal places. The national map is 960 units wide and never
# drawn larger, so whole units are already sub-pixel; insets keep a decimal
# because a few hundred units have to hold a whole city. Neighbours round
# identically, so shared borders stay welded either way.
DECIMALS_NATIONAL = 0
DECIMALS_INSET = 1

WIDTH_NATIONAL = 960

# Insets are fitted inside a fixed square and centred rather than scaled to a
# fixed width. Greater Perth and Greater Brisbane are long north-south strips
# while Greater Sydney is wider than tall; fitting each to its own bounds gave
# panels between 0.88 and 1.68 times as tall as they were wide, which cannot
# tile a row. A common box costs a little size on the tall ones and makes the
# five directly comparable.
INSET_BOX = 460

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
    """Reproject, simplify and export one view as fills plus a border mesh.

    Both layers come out of the same simplification pass, so they cannot
    disagree by a pixel. Fills are drawn unstroked with the mesh over them --
    pre-baked path strings overlap on every shared border, so stroking each
    region individually would double-draw every internal boundary.

    There is deliberately no separate coastline layer. The fills tile the
    continent, so their outer edge already is the coast; exporting it again
    cost a quarter of the file for a line the fills imply.
    """
    base = [shp, "-filter", where]
    regions = os.path.join(tmp, tag + "-regions.json")
    mesh = os.path.join(tmp, tag + "-mesh.json")

    mapshaper(base + [
        "-proj", PROJECTION,
        "-simplify", "visvalingam", "weighted", simplify, "keep-shapes",
        "-clean",
        "-o", regions, "format=geojson",
        "-innerlines",
        "-o", mesh, "format=geojson",
    ])
    return json.load(open(regions)), json.load(open(mesh))


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


def geometries(obj):
    """Every geometry in a GeoJSON document, whatever wrapper it arrived in.

    mapshaper returns a FeatureCollection while a layer still carries
    attributes, but -innerlines drops them and emits a bare
    GeometryCollection, so both have to be handled.
    """
    t = obj.get("type")
    if t == "FeatureCollection":
        return [f["geometry"] for f in obj["features"] if f.get("geometry")]
    if t == "GeometryCollection":
        return [g for g in obj["geometries"] if g]
    if t == "Feature":
        return [obj["geometry"]] if obj.get("geometry") else []
    return [obj] if t else []


def bounds(geoms):
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for g in geoms:
        for ring in rings(g):
            for x, y in ring:
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
    return x0, y0, x1, y1


def make_fit(box, width, height, decimals):
    """Projected metres to SVG pixels, y flipped (SVG counts down).

    With no height the shape fills the width; with one it is scaled to fit
    inside the box and centred, so several views share a panel size.
    """
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if height is None:
        scale = width / bw
        height = round(bh * scale, 1)
        ox = oy = 0.0
    else:
        scale = min(width / bw, height / bh)
        ox, oy = (width - bw * scale) / 2, (height - bh * scale) / 2
    fmt = "%s%." + str(decimals) + "f,%." + str(decimals) + "f"

    def path(geom, close):
        out = []
        for ring in rings(geom):
            pts, prev = [], None
            for i, (x, y) in enumerate(ring):
                px, py = ox + (x - x0) * scale, oy + (y1 - y) * scale
                pt = fmt % ("M" if i == 0 else "L", px, py)
                # Rounding collapses neighbouring vertices onto each other;
                # keeping the duplicates would just pad the file.
                if pt[1:] != prev:
                    pts.append(pt)
                prev = pt[1:]
            if len(pts) > 2:
                out.append("".join(pts) + ("Z" if close else ""))
        return "".join(out)

    return path, height


def build_view(shp, tmp, tag, where, simplify, width, decimals, height=None):
    regions, mesh = run_view(shp, tmp, tag, where, simplify)
    feats = [f for f in regions.get("features", []) if f.get("geometry")]
    if not feats:
        die("no features for view " + tag)

    path, height = make_fit(bounds(f["geometry"] for f in feats), width,
                            height, decimals)
    ids = {}
    for f in feats:
        p = f["properties"]
        state = STATE_ABBR.get(p["STE_NAME26"])
        if state is None:
            die("unmapped state name %r" % p["STE_NAME26"])
        ids["sa4:%s - %s" % (state, p["SA4_NAME26"])] = path(f["geometry"], True)

    return {
        "width": width,
        "height": height,
        "regions": ids,
        "mesh": "".join(path(g, False) for g in geometries(mesh)),
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
                                        SIMPLIFY_NATIONAL, WIDTH_NATIONAL,
                                        DECIMALS_NATIONAL)}
        for gcc in INSETS:
            where = '%s && GCC_NAME26 === "%s"' % (REAL_SA4, gcc)
            views["gccsa:" + gcc] = build_view(
                shp, tmp, gcc.replace(" ", "-"), where,
                SIMPLIFY_INSET, INSET_BOX, DECIMALS_INSET, INSET_BOX)

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
