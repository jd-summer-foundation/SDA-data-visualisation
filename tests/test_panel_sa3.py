"""Checks on the SA3 panel built alongside the SA4 one.

Run from the repository root:  python3 -m unittest discover tests

The SA3 panel is rebuilt from the committed workbooks and compared byte for
byte (skipped without openpyxl). The rest read only committed files: every
SA3 must sit in one SA4, SA3 figures must sum to the SA4 panel in every
quarter, and the latest quarter must agree with sda.json's SA3 rows.
"""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "data" / "panel"
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import openpyxl  # noqa: F401
    HAVE_OPENPYXL = True
except ImportError:
    HAVE_OPENPYXL = False

OUTPUTS = ["panel_sa3.csv", "sa3_sa4.csv", "validation_sa3.json", "VALIDATION_SA3.md"]


def read(name):
    with open(PANEL / name, newline="") as fh:
        return list(csv.DictReader(fh))


def values(name):
    return {(r["as_at"], r["geography"], r["category"], r["measure"]): float(r["value"])
            for r in read(name) if r["value"] != ""}


class Sa3PanelIsCurrent(unittest.TestCase):

    @unittest.skipUnless(HAVE_OPENPYXL, "openpyxl not installed")
    def test_rebuilds_from_workbooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "scripts/extract_panel_sa3.py", "data/supplements",
                            "-o", tmp], cwd=ROOT, check=True, capture_output=True, text=True)
            for name in OUTPUTS:
                self.assertEqual((Path(tmp) / name).read_bytes(), (PANEL / name).read_bytes(),
                                 f"data/panel/{name} is stale: re-run extract_panel_sa3.py")


class Sa3Mapping(unittest.TestCase):

    def test_every_sa3_in_one_known_sa4(self):
        mapping = read("sa3_sa4.csv")
        sa4 = {r["geography"] for r in read("panel.csv") if r["level"] == "SA4"}
        self.assertEqual(len(mapping), 336)
        self.assertEqual(len({r["sa3"] for r in mapping}), 336)
        for r in mapping:
            self.assertIn(r["sa4"], sa4, r)
            self.assertTrue(r["sa4"].startswith(f"sa4:{r['state']} - "), r)
        self.assertEqual({r["sa4"] for r in mapping}, sa4)

    def test_same_sa3_as_sda_json(self):
        sda = json.loads((ROOT / "data" / "sda.json").read_text())
        ids = {g["id"] for g in sda["geographies"]
               if g["level"] == "SA3" and not g["id"].endswith(" - Other")}
        self.assertEqual(ids, {r["sa3"] for r in read("sa3_sa4.csv")})


class Sa3Reconciles(unittest.TestCase):

    def test_report_has_no_mismatch(self):
        report = json.loads((PANEL / "validation_sa3.json").read_text())
        self.assertEqual(len(report["editions"]), 13)
        for e in report["editions"]:
            self.assertEqual(e["sa3_regions"], 336, e["edition"])
            for check in e["checks"]:
                self.assertGreater(check["compared"], 100, (e["edition"], check["check"]))
                self.assertEqual(check["mismatched"], 0, (e["edition"], check["check"],
                                                          check["examples"]))

    def test_sums_to_the_committed_sa4_panel(self):
        # Independent of the report: re-add the committed CSVs here.
        parent = {r["sa3"]: r["sa4"] for r in read("sa3_sa4.csv")}
        sums = defaultdict(float)
        for (as_at, geo, category, measure), v in values("panel_sa3.csv").items():
            if geo in parent:
                sums[(as_at, parent[geo], category, measure)] += v
        sa4 = values("panel.csv")
        compared = 0
        for key, total in sums.items():
            if key in sa4:
                compared += 1
                self.assertEqual(total, sa4[key], key)
        self.assertGreater(compared, 25000)

    def test_sa3_does_not_claim_places_it_cannot_derive(self):
        measures = {r["measure"] for r in read("panel_sa3.csv")}
        for absent in ("enrolled_places", "places_not_in_use", "newbuild_places",
                       "pipeline_dwellings", "pipeline_places"):
            self.assertNotIn(absent, measures)
        self.assertIn("places_from_max_residents", measures)

    def test_in_use_from_december_2023(self):
        in_use = sorted({r["as_at"] for r in read("panel_sa3.csv")
                         if r["measure"] == "participants_sda_in_use"})
        self.assertEqual((in_use[0], len(in_use)), ("2023-12-31", 11))


class Sa3AgreesWithSdaJson(unittest.TestCase):

    def test_latest_quarter_matches(self):
        panel = values("panel_sa3.csv")
        sda = json.loads((ROOT / "data" / "sda.json").read_text())
        as_at, compared = "2026-06-30", 0
        for g in sda["geographies"]:
            if g["level"] != "SA3" or g["id"].endswith(" - Other"):
                continue
            for category, cell in g["categories"].items():
                for measure in ("enrolled_dwellings", "participants_with_need"):
                    want = cell.get(measure)
                    if want is None:
                        continue
                    compared += 1
                    self.assertEqual(panel.get((as_at, g["id"], category, measure)), want,
                                     (g["id"], category, measure))
            for measure in ("participants_sda_in_use", "participants_eligible_not_using"):
                compared += 1
                self.assertEqual(panel.get((as_at, g["id"], "Total", measure)),
                                 g["totals"][measure], (g["id"], measure))
        self.assertGreater(compared, 3000)


class Sa3Units(unittest.TestCase):

    def test_unplaced_sa3_fails(self):
        import extract_panel_sa3 as x
        sa4 = {r["sa4"] for r in read("sa3_sa4.csv")}
        labels = list(x.ASGS_2021_SA3)
        self.assertEqual(len(x.sa3_parents(labels, {}, sa4)), 31)
        with self.assertRaisesRegex(ValueError, "VIC - Nowhere"):
            x.sa3_parents(labels + ["VIC - Nowhere"], {}, sa4)
        # A concordance that puts an SA3 in two SA4s is not guessed between.
        two = {"Geelong": {"sa4:VIC - Geelong", "sa4:VIC - Ballarat"}}
        with self.assertRaisesRegex(ValueError, "VIC - Geelong"):
            x.sa3_parents(labels + ["VIC - Geelong"], two, sa4)

    def test_geography_keeps_sa4_ids_by_default(self):
        import extract_panel
        self.assertEqual(extract_panel.geography("VIC - Geelong"),
                         ("sa4:VIC - Geelong", "SA4", "VIC"))
        self.assertEqual(extract_panel.geography("VIC - Geelong", "SA3"),
                         ("sa3:VIC - Geelong", "SA3", "VIC"))
        self.assertEqual(extract_panel.geography("VIC - Other", "SA3"),
                         ("other:VIC", "Other", "VIC"))


if __name__ == "__main__":
    unittest.main()
