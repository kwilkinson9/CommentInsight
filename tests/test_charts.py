"""Tests for the category-breakdown chart data (app/charts.py) -- plain
dicts in, plain numbers out, no DB/HTTP involved."""

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


if __name__ == "__main__":
    unittest.main()
