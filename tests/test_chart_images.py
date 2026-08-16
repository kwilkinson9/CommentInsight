"""Tests for the PNG chart renderer (app/chart_images.py) used to embed
charts in the multi-document Word export."""

import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PIL import Image

from app import chart_images, charts


class RenderBarChartPngTests(unittest.TestCase):
    def test_produces_a_valid_png(self):
        rows = charts.category_breakdown([{"category": "Editorial"}, {"category": "Other"}])
        png_bytes = chart_images.render_bar_chart_png("Comments by category", rows)

        self.assertGreater(len(png_bytes), 0)
        image = Image.open(io.BytesIO(png_bytes))
        image.load()  # forces full decode, catches truncated/corrupt output
        self.assertEqual(image.format, "PNG")

    def test_height_grows_with_row_count(self):
        few_rows = charts.category_breakdown([{"category": "Editorial"}])
        many_rows = charts.resolution_breakdown([])  # 3 rows, all zero
        self.assertEqual(len(few_rows), 5)
        self.assertEqual(len(many_rows), 3)

        few_png = Image.open(io.BytesIO(chart_images.render_bar_chart_png("A", few_rows)))
        many_png = Image.open(io.BytesIO(chart_images.render_bar_chart_png("B", many_rows)))
        # 5 rows should be taller than 3 rows
        self.assertGreater(few_png.height, many_png.height)

    def test_handles_all_zero_rows_without_crashing(self):
        rows = charts.category_breakdown([])
        png_bytes = chart_images.render_bar_chart_png("Comments by category", rows)
        image = Image.open(io.BytesIO(png_bytes))
        image.load()

    def test_handles_empty_row_list(self):
        png_bytes = chart_images.render_bar_chart_png("Nothing to show", [])
        image = Image.open(io.BytesIO(png_bytes))
        image.load()


if __name__ == "__main__":
    unittest.main()
