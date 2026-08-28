"""Tests for AI-generated cross-document pattern insights (app/ai/base.py's
InsightsGenerator, storage.save_insights/get_latest_insights, the
/analysis/insights route, and the insights section of the .docx export).

Uses a fake AI implementation -- no real, paid API calls."""

import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from docx import Document as DocxDocument

from app.ai.base import AnalysisInsights, InsightsGenerator, InsightTheme
from app.main import app
from app.routers.dashboard import get_insights_generator
from tests.auth_helpers import AuthenticatedTestCase

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"


class FakeInsightsGenerator(InsightsGenerator):
    model_name = "fake-insights-model-v1"

    def __init__(self, result=None):
        self._result = result or AnalysisInsights(
            overview="Reviewers across both documents repeatedly flag unresolved statistical questions.",
            themes=[
                InsightTheme(
                    title="Statistical sign-off pending",
                    description="Several comments in both documents are waiting on the biostatistics lead.",
                )
            ],
        )
        self.call_count = 0
        self.last_comments = None

    def generate_insights(self, comments):
        self.call_count += 1
        self.last_comments = comments
        return self._result


class BrokenInsightsGenerator(InsightsGenerator):
    model_name = "fake-insights-model-v1"

    def generate_insights(self, comments):
        raise RuntimeError("simulated API failure")


class InsightsTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.fake_generator = FakeInsightsGenerator()
        app.dependency_overrides[get_insights_generator] = lambda: self.fake_generator

    def _upload(self, name="a.docx"):
        with open(SAMPLE, "rb") as f:
            return self.client.post(
                "/upload",
                files={"file": (name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

    def test_no_insights_generated_yet(self):
        self._upload()
        resp = self.client.get("/analysis")
        self.assertIn("No AI insights generated yet", resp.text)

    def test_generate_insights_shows_overview_and_themes(self):
        self._upload()
        resp = self.client.post("/analysis/insights")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/analysis")
        self.assertEqual(self.fake_generator.call_count, 1)

        page = self.client.get("/analysis")
        self.assertIn("Reviewers across both documents repeatedly flag unresolved statistical questions.", page.text)
        self.assertIn("Statistical sign-off pending", page.text)

    def test_generator_receives_comments_tagged_with_document_and_category(self):
        self._upload("a.docx")
        self.client.post("/documents/1/classify")
        self.client.post("/analysis/insights")

        comments = self.fake_generator.last_comments
        self.assertTrue(all(c.document_filename == "a.docx" for c in comments))

    def test_regenerate_button_shown_once_insights_exist(self):
        self._upload()
        self.client.post("/analysis/insights")
        page = self.client.get("/analysis")
        self.assertIn("Regenerate insights", page.text)

    def test_regenerating_replaces_the_previous_insights(self):
        self._upload()
        self.client.post("/analysis/insights")

        self.fake_generator._result = AnalysisInsights(overview="A completely different finding.", themes=[])
        self.client.post("/analysis/insights")
        self.assertEqual(self.fake_generator.call_count, 2)

        page = self.client.get("/analysis")
        self.assertIn("A completely different finding.", page.text)
        self.assertNotIn("Statistical sign-off pending", page.text)

    def test_stale_flag_shown_after_uploading_another_document(self):
        self._upload("a.docx")
        self.client.post("/analysis/insights")
        self._upload("b.docx")

        page = self.client.get("/analysis")
        self.assertIn("documents have changed since", page.text)

    def test_insights_failure_shows_friendly_error_not_a_500(self):
        app.dependency_overrides[get_insights_generator] = lambda: BrokenInsightsGenerator()
        self._upload()

        resp = self.client.post("/analysis/insights")

        self.assertEqual(resp.status_code, 502)
        self.assertIn("Insight generation failed", resp.text)

    def test_docx_export_includes_insights_section_once_generated(self):
        self._upload()
        self.client.post("/analysis/insights")

        resp = self.client.get("/analysis/export.docx")
        self.assertEqual(resp.status_code, 200)
        doc = DocxDocument(io.BytesIO(resp.content))
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("AI Insights", text)
        self.assertIn("Reviewers across both documents repeatedly flag unresolved statistical questions.", text)
        self.assertIn("Statistical sign-off pending", text)

    def test_docx_export_omits_insights_section_when_none_generated(self):
        self._upload()
        resp = self.client.get("/analysis/export.docx")
        doc = DocxDocument(io.BytesIO(resp.content))
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertNotIn("AI Insights", text)


if __name__ == "__main__":
    unittest.main()
