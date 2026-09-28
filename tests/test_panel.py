"""Checks on the quarterly panel built from every Supplement P edition.

Run from the repository root:  python3 -m unittest discover tests

The panel is rebuilt from the thirteen committed workbooks and compared byte
for byte (skipped without openpyxl). The rest read only the committed CSV and
validation report, so they run anywhere: the latest quarter must agree with
sda.json, every quarter must reconcile, and the breaks the report names must
stay where they are.
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

import extract_panel  # noqa: E402

try:
    import openpyxl  # noqa: F401
    HAVE_OPENPYXL = True
except ImportError:
    HAVE_OPENPYXL = False

OUTPUTS = ["panel.csv", "figure_p1.csv", "validation.json", "VALIDATION.md"]


def load_panel():
    values = {}
    with open(PANEL / "panel.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            v = float(row["value"]) if row["value"] else None
            values[(row["as_at"], row["geography"], row["category"], row["measure"])] = (v, row)
    return values


class PanelIsCurrent(unittest.TestCase):

    @unittest.skipUnless(HAVE_OPENPYXL, "openpyxl not installed")
    def test_panel_rebuilds_from_workbooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "scripts/extract_panel.py", "data/supplements",
                            "-o", tmp], cwd=ROOT, check=True, capture_output=True, text=True)
            for name in OUTPUTS:
                self.assertEqual((Path(tmp) / name).read_bytes(), (PANEL / name).read_bytes(),
                                 f"data/panel/{name} is stale: re-run extract_panel.py")


class PanelAgreesWithSdaJson(unittest.TestCase):
    """The latest quarter of the panel is the edition sda.json is built from,
    so the two must say the same thing wherever they overlap."""

    def test_latest_quarter_matches(self):
        panel = load_panel()
        sda = json.loads((ROOT / "data" / "sda.json").read_text())
        as_at = "2026-06-30"
        compared = 0
        for g in sda["geographies"]:
            if g["level"] == "SA3":
                continue
            geo = g["id"]
            # sda.json books its unplaced "- Other" rows as SA4s holding zero
            # stock; the panel leaves stock out for them, there being no row.
            unplaced = geo.endswith(" - Other")
            if unplaced:
                geo = "other:" + geo.split(":")[1].split(" - ")[0]
            for category, cell in g["categories"].items():
                for measure in ("enrolled_dwellings", "enrolled_places", "pipeline_dwellings",
                                "pipeline_places", "participants_with_need"):
                    if unplaced and measure != "participants_with_need":
                        continue
                    want = cell[measure]
                    got = panel.get((as_at, geo, category, measure), (None,))[0]
                    if want is None and got is None:
                        continue
                    compared += 1
                    self.assertEqual(got, want, f"{geo} {category} {measure}")
            for measure in ("enrolled_places", "places_not_in_use", "participants_sda_in_use",
                            "participants_eligible_not_using"):
                want = g["totals"].get(measure)
                if want is None or (unplaced and "places" in measure):
                    continue
                compared += 1
                self.assertEqual(panel[(as_at, geo, "Total", measure)][0], want, f"{geo} {measure}")
        self.assertGreater(compared, 2000)


class EveryQuarterReconciles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((PANEL / "validation.json").read_text())

    def test_thirteen_quarters(self):
        dates = [e["as_at"] for e in self.report["editions"]]
        self.assertEqual(len(dates), 13)
        self.assertEqual(dates[0], "2023-06-30")
        self.assertEqual(dates[-1], "2026-06-30")

    def test_hierarchy_and_identities_hold(self):
        for e in self.report["editions"]:
            for check in e["hierarchy"] + e["identities"]:
                self.assertGreater(check["compared"], 0, (e["edition"], check["check"]))
                self.assertEqual(check["mismatched"], 0, (e["edition"], check["check"],
                                                          check["examples"]))

    def test_same_88_regions_throughout(self):
        for r in self.report["regions"]:
            self.assertEqual(r["sa4_in_stock_tables"], 88, r["edition"])
            self.assertEqual(r["added"] + r["removed"], [], r["edition"])

    def test_derivation_calibrates_every_quarter(self):
        for e in self.report["editions"]:
            p7, p6 = e["calibration"]["p7"], e["calibration"]["p6"]
            self.assertGreaterEqual(p7["exact_share"], 0.95, e["edition"])
            self.assertLess(abs(p7["net_bias"]), 0.01, e["edition"])
            self.assertGreaterEqual(p6["within_2_percent"] / p6["regions_checked"], 0.95,
                                    e["edition"])
            nat = p6["national_derived"] / p6["national_from_max_residents"] - 1
            self.assertLess(abs(nat), 0.01, e["edition"])

    def test_figure_matches_its_own_tables(self):
        for e in self.report["editions"]:
            for f in e["figure_vs_tables"]:
                self.assertTrue(f["agrees"], (e["edition"], f))

    def test_breaks_are_where_the_report_says(self):
        usable = {row["measure"]: row["editions"] for row in self.report["usability"]}
        self.assertEqual(len(usable["enrolled_places"]), 13)
        self.assertEqual(usable["participants_sda_in_use"][0], "2023-24 Q2")
        self.assertEqual(usable["participants_with_need"][0], "2024-25 Q2")
        self.assertEqual(len(usable["participants_with_need"]), 7)
        self.assertEqual(usable["legacy_participants_seeking"], ["2022-23 Q4", "2023-24 Q1"])
        announced = {a["announcement"]: a["edition"] for a in self.report["announcements"]}
        self.assertEqual(announced["Basic decisions folded into 'Missing'"], "2024-25 Q3")


class Units(unittest.TestCase):

    def test_classify_reads_the_header_over_the_caption(self):
        # 2023-24 Q2 captions its SA3 not-in-use table as the old seeking table.
        role = extract_panel.classify(
            "Table P.18 Number of Participants seeking SDA dwelling SA3 Region and Design "
            "Category as at 31 December 2023",
            ["SA3 Region", "Participants with SDA Funding, SDA not in use",
             "Percentage of participants with SDA funding not in use"])
        self.assertEqual(role, ("not_using", "SA3", None))

    def test_excluding_in_kind_is_not_in_kind(self):
        role = extract_panel.classify(
            "Table P.5 Number of Enrolled SDA Dwellings by SA4 Region and Design Category "
            "as at 30 June 2023 (excluding in-kind arrangements)",
            ["SA4 Region", "Basic", "Total"])
        self.assertEqual(role[0], "stock_categories")

    def test_unknown_table_fails(self):
        with self.assertRaises(ValueError):
            extract_panel.classify("Table P.99 Something new", ["SA4 Region", "x"])

    def test_width_stops_at_placeholders(self):
        self.assertEqual(extract_panel.table_width(("SA4 Region", "a", "Total", "Column1", "Column2")), 3)
        self.assertEqual(extract_panel.table_width(("SA4 Region", "a", None, "b")), 2)

    def test_crosstab_never_sums_a_suppressed_cell(self):
        cells = extract_panel.crosstab(
            {"House, 3 residents - Robust": 2.0, "Group home, 5 residents - Robust": None,
             "Apartment, 2 bedrooms, 1 resident - Fully Accessible": 4.0, "Total": 6.0},
            {"Group home, 5 residents - Robust": "suppressed:<5"})
        self.assertIsNone(cells["Robust"]["places"])
        self.assertEqual(cells["Robust"]["flag"], "suppressed:<5")
        self.assertEqual(cells["Fully Accessible"]["places"], 4.0)

    def test_figure_prose_carries_both_participant_series(self):
        got = extract_panel.parse_figure_prose([
            " In June 2026 there were 16,644 active participants with SDA in use and 9,014 "
            "active participants eligible but not yet using SDA.\n"
            " In June 2026 there were $683m in annualised SDA supports.\n"])
        self.assertEqual(got[("participants_sda_in_use", "2026-06-30")], 16644)
        self.assertEqual(got[("participants_eligible_not_using", "2026-06-30")], 9014)
        self.assertEqual(got[("sda_annualised_m", "2026-06-30")], 683)

    def test_duplicate_rows_dropped_only_when_identical(self):
        class Sheet:
            title = "Table P.x"

            def __init__(self, rows):
                self.rows = rows

            def iter_rows(self, **_):
                return iter(self.rows)

        header = ["SA4 Region", "Robust"]
        rows, _, dupes = extract_panel.read_body(
            Sheet([("QLD - Wide Bay", 3), ("QLD - Wide Bay", 3)]), header)
        self.assertEqual(dupes, ["QLD - Wide Bay"])
        self.assertEqual(rows["QLD - Wide Bay"]["values"]["Robust"], 3.0)
        with self.assertRaises(ValueError):
            extract_panel.read_body(Sheet([("QLD - Wide Bay", 3), ("QLD - Wide Bay", 4)]), header)


class PanelShape(unittest.TestCase):

    def test_places_not_in_use_reconciles(self):
        panel = load_panel()
        by_geo = defaultdict(dict)
        for (as_at, geo, category, measure), (v, _) in panel.items():
            if category == "Total":
                by_geo[(as_at, geo)][measure] = v
        checked = 0
        for key, m in by_geo.items():
            if m.get("places_not_in_use") is None:
                continue
            checked += 1
            self.assertEqual(m["places_not_in_use"],
                             m["enrolled_places"] - m["participants_sda_in_use"], key)
        self.assertGreater(checked, 1000)


if __name__ == "__main__":
    unittest.main()
