"""Checks that the committed data files are what the committed code produces.

Run from the repository root:  python3 -m unittest discover tests

sda.json is rebuilt from the committed June 2026 workbook and compared byte for
byte (skipped where openpyxl is not installed, since only that path opens a
workbook); its derived measures are also checked to be current on their own,
which needs no openpyxl. vacancies.json, whose inputs are all committed,
rebuilds byte for byte.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))

import extract_sda  # noqa: E402

try:
    import openpyxl  # noqa: F401
    HAVE_OPENPYXL = True
except ImportError:
    HAVE_OPENPYXL = False

WORKBOOK = DATA / "supplements" / "Supplement_P_SDA_2025-26_Q4.xlsx"


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


class CommittedDataIsCurrent(unittest.TestCase):

    def test_sda_derived_measures_are_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "sda.json"
            shutil.copy(DATA / "sda.json", copy)
            run("scripts/extract_sda.py", "--rederive", str(copy))
            self.assertEqual(copy.read_bytes(), (DATA / "sda.json").read_bytes(),
                             "sda.json is stale: run extract_sda.py --rederive data/sda.json")

    @unittest.skipUnless(HAVE_OPENPYXL, "openpyxl not installed")
    def test_sda_rebuilds_from_workbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            run("scripts/extract_sda.py", str(WORKBOOK.relative_to(ROOT)), "-o", tmp)
            self.assertEqual((Path(tmp) / "sda.json").read_bytes(),
                             (DATA / "sda.json").read_bytes(),
                             "sda.json does not match a fresh build from the workbook")

    def test_vacancies_rebuild_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(DATA / "sda.json", Path(tmp) / "sda.json")
            run("scripts/extract_vacancies.py", "data/List_SDA_20260824.csv",
                "--postcodes", "data/australian_postcodes.csv", "-o", tmp)
            self.assertEqual((Path(tmp) / "vacancies.json").read_bytes(),
                             (DATA / "vacancies.json").read_bytes(),
                             "vacancies.json is stale: re-run extract_vacancies.py")


class DerivedMeasures(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sda = json.loads((DATA / "sda.json").read_text())
        cls.vac = json.loads((DATA / "vacancies.json").read_text())
        cls.by_id = {g["id"]: g for g in cls.sda["geographies"]}

    def test_places_derivation_tracks_max_residents(self):
        # The one check of the derivation that covers existing and legacy stock.
        res = self.sda["meta"]["residents_calibration"]
        self.assertGreaterEqual(res["regions_checked"], 80)
        self.assertGreaterEqual(res["within_2_percent"] / res["regions_checked"], 0.95)
        nat = res["national"]
        self.assertLess(abs(nat["derived"] - nat["from_residents"]) / nat["from_residents"], 0.01)

    def test_places_not_in_use_reconciles(self):
        for g in self.sda["geographies"]:
            t = g["totals"]
            if t.get("places_not_in_use") is None:
                continue
            self.assertEqual(t["places_not_in_use"],
                             t["enrolled_places"] - t["participants_sda_in_use"], g["id"])
            # In use can never exceed what is enrolled; if it does, places are
            # being lost somewhere in the derivation.
            self.assertGreaterEqual(t["places_not_in_use"], 0, g["id"])

    def test_residents_places_skips_suppressed_rows(self):
        node = {"max_residents": {label: 1.0 for label in extract_sda.RESIDENT_COUNTS}}
        self.assertEqual(extract_sda.residents_places(node), 21.0)
        node["max_residents"]["3 Residents"] = None
        self.assertIsNone(extract_sda.residents_places(node))

    def test_bridge_statistics_are_in_range(self):
        corr = self.vac["meta"]["bridge_correlation"]
        wr = corr["within_region"]
        for r in (corr["spearman"], wr["r"], wr["newbuild"]["r"], wr["controlling_newbuild"]["r"]):
            self.assertTrue(-1 <= r <= 1)
        null = corr["shared_term_null"]
        # The shared term should manufacture next to nothing on its own.
        self.assertLess(abs(null["mean"]), 0.05)

    def test_model_reports_every_tested_term(self):
        model = self.vac["meta"]["whole_dwelling_model"]
        tested = {t["term"] for t in model["terms"] if t["kind"] != "control"}
        self.assertTrue({"Onsite overnight assistance", "Breakout room",
                         "Price per room (log)"} <= tested)
        self.assertGreater(model["n"], 1000)


if __name__ == "__main__":
    unittest.main()
