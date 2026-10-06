"""Checks on the location-factor experiment's inputs, Phase 1 report and Phase 2 analysis.

Run from the repository root:  python3 -m unittest discover tests

Pricing, the P.11 building-type detail, the feasibility report and the
Phase 2 analysis rebuild
from committed files and are compared byte for byte (the P.11 rebuild needs
openpyxl). The ABS reductions rebuild from raw/, which is not committed, so
those rebuilds are skipped unless raw/ is present; the committed reduced files
are checked on their own terms instead.
"""
import csv
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = ROOT / "raw" / "abs"

try:
    import openpyxl  # noqa: F401
    HAVE_OPENPYXL = True
except ImportError:
    HAVE_OPENPYXL = False


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True, capture_output=True, text=True)


def sa4_ids():
    return {r["sa4"] for r in read(DATA / "panel" / "sa3_sa4.csv")}


class Rebuilds(unittest.TestCase):

    def same(self, tmp, committed_dir, names, script):
        for name in names:
            self.assertEqual((Path(tmp) / name).read_bytes(), (committed_dir / name).read_bytes(),
                             f"{committed_dir.relative_to(ROOT)}/{name} is stale: re-run {script}")

    def test_pricing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/extract_pricing.py", "data/pricing", "-o", tmp)
            self.same(tmp, DATA / "pricing", ["location_factors.csv", "base_amounts.csv"],
                      "extract_pricing.py")

    def test_feasibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/feasibility_location_factor.py", "-o", tmp)
            self.same(tmp, DATA / "panel", ["location_factor_feasibility.json",
                                            "LOCATION_FACTOR_FEASIBILITY.md",
                                            "location_factor_pairs.csv"],
                      "feasibility_location_factor.py")

    def test_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/analyse_location_factor.py", "-o", tmp)
            self.same(tmp, DATA / "panel", ["location_factor.json", "LOCATION_FACTOR.md"],
                      "analyse_location_factor.py")

    @unittest.skipUnless(HAVE_OPENPYXL, "openpyxl not installed")
    def test_newbuild_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/extract_newbuild_types.py", "data/supplements", "-o", tmp)
            self.same(tmp, DATA / "panel", ["newbuild_types_sa4.csv"], "extract_newbuild_types.py")

    @unittest.skipUnless(RAW.exists(), "raw/abs not downloaded (see raw/MANIFEST.md)")
    def test_abs_reductions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/reduce_abs.py", str(RAW), "-o", tmp)
            self.same(tmp, DATA / "abs", ["building_approvals_sa2.csv", "census_2021_sa3.csv",
                                          "census_2021_sa2.csv", "sal_sa3_dwellings.csv"],
                      "reduce_abs.py")

    @unittest.skipUnless((ROOT / "raw" / "vgv").exists(), "raw/vgv not downloaded")
    def test_vgv_reduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/reduce_vgv.py", str(ROOT / "raw" / "vgv"), "-o", tmp)
            self.same(tmp, DATA / "vgv", ["vacant_land_by_locality.csv"], "reduce_vgv.py")

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/summarise_location_factor.py", "-o", tmp)
            self.same(tmp, DATA / "panel", ["LOCATION_FACTOR_SUMMARY.md"],
                      "summarise_location_factor.py")

    def test_land_value_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/analyse_land_value.py", "-o", tmp)
            self.same(tmp, DATA / "panel", ["land_value_vic.json", "LAND_VALUE_VIC.md",
                                            "land_value_nsw.json", "LAND_VALUE_NSW.md"],
                      "analyse_land_value.py")

    @unittest.skipUnless((ROOT / "raw" / "nsw_vg" / "LV_20260901").exists(),
                         "raw/nsw_vg not present (property-level; see raw/MANIFEST.md)")
    def test_nsw_vg_reduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/reduce_nsw_vg.py", str(ROOT / "raw" / "nsw_vg"), "-o", tmp)
            self.same(tmp, DATA / "nsw_vg", ["land_value_by_locality.csv"], "reduce_nsw_vg.py")

    @unittest.skipUnless((RAW / "asgs").exists(), "raw/abs/asgs not downloaded")
    def test_adjacency(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/build_sa3_adjacency.py", "-o", tmp)
            self.same(tmp, DATA / "abs", ["sa3_adjacency.csv"], "build_sa3_adjacency.py")


class Pricing(unittest.TestCase):

    def test_every_sa4_in_every_table(self):
        cells = defaultdict(set)
        for r in read(DATA / "pricing" / "location_factors.csv"):
            cells[(r["edition"], r["stock_type"], r["building_type"])].add(r["sa4"])
        ids = sa4_ids()
        self.assertEqual(len(ids), 88)
        for key, found in cells.items():
            self.assertEqual(found, ids, key)
        per_stock = defaultdict(set)
        for (_, stock, btype) in cells:
            per_stock[stock].add(btype)
        self.assertEqual(len(per_stock["New build"]), 11)
        self.assertEqual(len(per_stock["Existing"]), 11)
        self.assertEqual(per_stock["Legacy"], {"Legacy"})

    def test_building_types_join_p11(self):
        p11 = {r["building_type"] for r in read(DATA / "panel" / "newbuild_types_sa4.csv")}
        priced = {r["building_type"] for r in read(DATA / "pricing" / "location_factors.csv")
                  if r["stock_type"] == "New build"}
        self.assertEqual(p11 - priced, set(), "P.11 building types without a factor")


class NewbuildTypes(unittest.TestCase):

    def test_sums_to_panel(self):
        """Summed over building types, P.11 detail equals panel.csv's P.11 sums."""
        detail = defaultdict(float)
        for r in read(DATA / "panel" / "newbuild_types_sa4.csv"):
            detail[(r["as_at"], r["sa4"], r["design_category"])] += float(r["dwellings"] or 0)
        checked = 0
        for r in read(DATA / "panel" / "panel.csv"):
            if (r["measure"] == "newbuild_dwellings" and r["level"] == "SA4"
                    and r["source"].endswith("sum") and r["value"] != ""):
                self.assertAlmostEqual(detail[(r["as_at"], r["geography"], r["category"])],
                                       float(r["value"]), msg=str(r))
                checked += 1
        self.assertGreater(checked, 5000)


class AbsReductions(unittest.TestCase):

    def test_approvals_sum_to_state_and_nation(self):
        per = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        for r in read(DATA / "abs" / "building_approvals_sa2.csv"):
            per[r["quarter"]][r["region"]] = [float(r["houses"]), float(r["other_residential"])]
        self.assertGreaterEqual(len(per), 20)
        for q, regions in per.items():
            states = defaultdict(lambda: [0.0, 0.0])
            for code, vals in regions.items():
                if len(code) == 9:
                    for i in (0, 1):
                        states[code[0]][i] += vals[i]
            for i in (0, 1):
                for s in "12345678":
                    self.assertAlmostEqual(states[s][i], regions[s][i], msg=f"{q} state {s}")
                self.assertAlmostEqual(sum(regions[s][i] for s in "12345678"), regions["0"][i],
                                       msg=f"{q} national")

    def test_every_sa2_known(self):
        known = {r["SA2_CODE_2021"] for r in read(DATA / "asgs_2021_sa2.csv")}
        codes = {r["region"] for r in read(DATA / "abs" / "building_approvals_sa2.csv")
                 if len(r["region"]) == 9}
        self.assertEqual(codes - known, set())

    def test_census_covers_every_sa3(self):
        census = {r["sa3_code_2021"] for r in read(DATA / "abs" / "census_2021_sa3.csv")}
        panel = {r["sa3_code"] for r in read(DATA / "panel" / "sa3_sa4.csv")}
        self.assertEqual(panel - census, set())

    def test_localities_join(self):
        """Every VGV locality is a Victorian SAL, and every SAL x SA3 cell a known SA3."""
        sal = read(DATA / "abs" / "sal_sa3_dwellings.csv")
        vic = {r["sal_code"] for r in sal if r["state"] == "VIC"}
        vgv = {r["sal_code_2021"] for r in read(DATA / "vgv" / "vacant_land_by_locality.csv")}
        self.assertEqual(vgv - vic, set())
        nsw = {r["sal_code"] for r in sal if r["state"] == "NSW"}
        vg = {r["sal_code_2021"] for r in read(DATA / "nsw_vg" / "land_value_by_locality.csv")}
        self.assertEqual(vg - nsw, set())
        sa3 = {r["SA3_CODE_2021"] for r in read(DATA / "asgs_2021_sa2.csv")}
        self.assertEqual({r["sa3_code"] for r in sal} - sa3, set())
        panel = {r["sa3_code"] for r in read(DATA / "panel" / "sa3_sa4.csv")}
        self.assertEqual(panel - {r["sa3_code"] for r in sal}, set())

    def test_adjacency_pairs(self):
        mapping = {r["sa3"]: r for r in read(DATA / "panel" / "sa3_sa4.csv")}
        pairs = read(DATA / "abs" / "sa3_adjacency.csv")
        seen = set()
        for p in pairs:
            a, b = p["sa3_a"], p["sa3_b"]
            self.assertLess(p["sa3_code_a"], p["sa3_code_b"])
            self.assertNotIn((a, b), seen)
            seen.add((a, b))
            self.assertEqual(mapping[a]["sa4"], p["sa4_a"])
            self.assertEqual(mapping[b]["sa4"], p["sa4_b"])
            self.assertEqual(p["cross_sa4"], "yes" if p["sa4_a"] != p["sa4_b"] else "no")
            self.assertGreater(float(p["shared_km"]), 0)
        # Every SA3 but island ones has a neighbour.
        touched = {g for p in pairs for g in (p["sa3_a"], p["sa3_b"])}
        self.assertGreater(len(touched), 320)


if __name__ == "__main__":
    unittest.main()


class NswLandValues(unittest.TestCase):
    """The committed NSW file holds locality aggregates only."""

    def test_aggregates_only(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from reduce_nsw_vg import MEASURES, MIN_PARCELS
        rows = read(DATA / "nsw_vg" / "land_value_by_locality.csv")
        expected = ["sal_code_2021", "sal_name_2021", "base_date"]
        for m in MEASURES:
            expected += [f"{m}_parcels", f"{m}_median"]
        self.assertEqual(list(rows[0]), expected, "unexpected columns: nothing property-level may be added")
        seen = set()
        for r in rows:
            key = (r["sal_code_2021"], r["base_date"])
            self.assertNotIn(key, seen)
            seen.add(key)
            self.assertIn(r["base_date"], {f"{y}-07-01" for y in range(2021, 2026)})
            medians = 0
            for m in MEASURES:
                n = int(r[f"{m}_parcels"])
                if r[f"{m}_median"]:
                    self.assertGreaterEqual(n, MIN_PARCELS, f"{key} {m}: median from too few parcels")
                    self.assertGreater(float(r[f"{m}_median"]), 0)
                    medians += 1
            self.assertGreater(medians, 0, key)

    def test_readme_counts_match_reducer(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from reduce_nsw_vg import NOT_LOCALITIES, PLACED
        text = (DATA / "README.md").read_text()
        self.assertIn(f"`PLACED` ({len(PLACED)})", text)
        self.assertIn(f"`NOT_LOCALITIES` ({len(NOT_LOCALITIES)})", text)
