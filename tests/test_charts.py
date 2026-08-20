"""Tests for the chart data functions in app/charts.py -- plain dicts in,
plain numbers out, no DB/HTTP involved."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import charts
from app.ai.base import CATEGORIES


class CategoryBreakdownTests(unittest.TestCase):
    def test_counts_each_category_and_not_classified(self):
        comments = [
            {"category": "Editorial"},
            {"category": "Editorial"},
            {"category": "Scientific/Content"},
            {"category": None},
        ]
        rows = charts.category_breakdown(comments)
        by_label = {row["label"]: row["count"] for row in rows}

        self.assertEqual(by_label["Editorial"], 2)
        self.assertEqual(by_label["Scientific/Content"], 1)
        self.assertEqual(by_label["Not classified"], 1)
        # every real category shows up even at zero, so the chart shape is stable
        for category in CATEGORIES:
            self.assertIn(category, by_label)

    def test_not_classified_row_omitted_when_everything_is_classified(self):
        comments = [{"category": "Editorial"}, {"category": "Other"}]
        rows = charts.category_breakdown(comments)
        labels = [row["label"] for row in rows]
        self.assertNotIn("Not classified", labels)

    def test_bar_width_scales_against_the_largest_bucket(self):
        comments = [{"category": "Editorial"}] * 4 + [{"category": "Other"}] * 2
        rows = charts.category_breakdown(comments)
        by_label = {row["label"]: row for row in rows}

        self.assertEqual(by_label["Editorial"]["bar_width"], charts.CHART_BAR_MAX_WIDTH)
        self.assertAlmostEqual(by_label["Other"]["bar_width"], charts.CHART_BAR_MAX_WIDTH / 2)
        self.assertEqual(by_label["Decision Required"]["bar_width"], 0)

    def test_sorted_by_count_descending(self):
        comments = [{"category": "Other"}] * 3 + [{"category": "Editorial"}] * 5
        rows = charts.category_breakdown(comments)
        counts = [row["count"] for row in rows]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_empty_document_has_every_category_at_zero_no_crash(self):
        rows = charts.category_breakdown([])
        self.assertEqual(len(rows), len(CATEGORIES))
        self.assertTrue(all(row["count"] == 0 and row["bar_width"] == 0 for row in rows))

    def test_each_category_keeps_its_own_color_regardless_of_rank(self):
        # Color follows the entity, not its sort position: run the same
        # category-label data twice with different mixes and confirm each
        # label's color never changes.
        rows_a = charts.category_breakdown([{"category": "Editorial"}] * 5 + [{"category": "Other"}])
        rows_b = charts.category_breakdown([{"category": "Editorial"}] + [{"category": "Other"}] * 5)
        color_a = {r["label"]: r["color"] for r in rows_a}
        color_b = {r["label"]: r["color"] for r in rows_b}
        self.assertEqual(color_a["Editorial"], color_b["Editorial"])
        self.assertEqual(color_a["Other"], color_b["Other"])


class ResolutionBreakdownTests(unittest.TestCase):
    def test_counts_each_status_and_no_decision(self):
        comments = [
            {"resolution_status": "accepted"},
            {"resolution_status": "accepted"},
            {"resolution_status": "crm"},
            {"resolution_status": None},
        ]
        rows = charts.resolution_breakdown(comments)
        by_label = {row["label"]: row["count"] for row in rows}

        self.assertEqual(by_label["Accepted"], 2)
        self.assertEqual(by_label["CRM (needs meeting)"], 1)
        self.assertEqual(by_label["No decision yet"], 1)
        self.assertEqual(by_label["Rejected"], 0)

    def test_no_decision_row_omitted_when_everything_is_resolved(self):
        comments = [{"resolution_status": "accepted"}, {"resolution_status": "rejected"}]
        rows = charts.resolution_breakdown(comments)
        labels = [row["label"] for row in rows]
        self.assertNotIn("No decision yet", labels)

    def test_empty_document_has_every_status_at_zero_no_crash(self):
        rows = charts.resolution_breakdown([])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["count"] == 0 and row["bar_width"] == 0 for row in rows))

    def test_sorted_by_count_descending(self):
        comments = [{"resolution_status": "crm"}] * 2 + [{"resolution_status": "accepted"}] * 5
        rows = charts.resolution_breakdown(comments)
        counts = [row["count"] for row in rows]
        self.assertEqual(counts, sorted(counts, reverse=True))


class SectionHotspotsTests(unittest.TestCase):
    def test_section_in_multiple_documents_is_included(self):
        comments = [
            {"section": "5.3.2 Deaths", "document_id": 1},
            {"section": "5.3.2 Deaths", "document_id": 2},
        ]
        rows = charts.section_hotspots(comments)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["section"], "5.3.2 Deaths")
        self.assertEqual(rows[0]["document_count"], 2)
        self.assertEqual(rows[0]["count"], 2)

    def test_section_in_only_one_document_is_excluded(self):
        comments = [
            {"section": "5.3.2 Deaths", "document_id": 1},
            {"section": "5.3.2 Deaths", "document_id": 1},
            {"section": "9.1 Primary Endpoint", "document_id": 1},
        ]
        rows = charts.section_hotspots(comments)
        self.assertEqual(rows, [])

    def test_comments_without_a_section_are_ignored(self):
        comments = [
            {"section": None, "document_id": 1},
            {"section": "", "document_id": 2},
        ]
        rows = charts.section_hotspots(comments)
        self.assertEqual(rows, [])

    def test_sorted_by_total_comment_count_descending(self):
        comments = (
            [{"section": "A", "document_id": 1}, {"section": "A", "document_id": 2}] * 3
            + [{"section": "B", "document_id": 1}, {"section": "B", "document_id": 2}]
        )
        rows = charts.section_hotspots(comments)
        counts = [row["count"] for row in rows]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(rows[0]["section"], "A")

    def test_capped_at_max_rows(self):
        comments = []
        for i in range(15):
            section = f"Section {i}"
            comments.append({"section": section, "document_id": 1})
            comments.append({"section": section, "document_id": 2})
        rows = charts.section_hotspots(comments, max_rows=5)
        self.assertEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
