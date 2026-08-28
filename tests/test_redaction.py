"""Tests for the "scrub likely patient identifiers before sending to
Claude" workflow: the opt-in checkbox on classify/detect-conflicts/insights,
the review-and-confirm screen app.deidentify findings trigger, and that the
AI actually receives redacted text once confirmed -- not just that a
screen shows up."""

import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from docx import Document as DocxDocument

from app.ai.base import AnalysisInsights, Classification, Classifier, ConflictDetector, InsightsGenerator
from app.main import app
from app.routers.dashboard import get_classifier, get_conflict_detector, get_insights_generator
from tests.auth_helpers import AuthenticatedTestCase


def _build_docx(comments: list[tuple[str, str]]) -> bytes:
    doc = DocxDocument()
    for i, (author, text) in enumerate(comments):
        paragraph = doc.add_paragraph(f"Paragraph {i} body text.")
        initials = "".join(w[0] for w in author.split())[:3].upper()
        doc.add_comment(paragraph.runs[0], text=text, author=author, initials=initials)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# One comment with an obvious identifier (email), one perfectly clean.
WITH_IDENTIFIER = _build_docx([
    ("Priya Patel", "Reach the subject's caregiver at jane.smith@example.com for follow-up."),
    ("Tom Reyes", "This wording is unclear, please rephrase for clarity."),
])
CLEAN_ONLY = _build_docx([
    ("Priya Patel", "This wording is unclear, please rephrase for clarity."),
])


class FakeClassifier(Classifier):
    model_name = "fake-classifier-v1"

    def __init__(self):
        self.received_texts: list[str] = []

    def classify(self, comment) -> Classification:
        self.received_texts.append(comment.text)
        return Classification(category="Other", rationale="fake")


class FakeConflictDetector(ConflictDetector):
    model_name = "fake-conflict-v1"

    def __init__(self):
        self.received_texts: list[str] = []

    def detect_conflicts(self, comments):
        self.received_texts.extend(c.text for c in comments)
        return []


class FakeInsightsGenerator(InsightsGenerator):
    model_name = "fake-insights-v1"

    def __init__(self):
        self.received_texts: list[str] = []

    def generate_insights(self, comments):
        self.received_texts.extend(c.text for c in comments)
        return AnalysisInsights(overview="fake overview", themes=[])


class RedactionWorkflowTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.fake_classifier = FakeClassifier()
        self.fake_detector = FakeConflictDetector()
        self.fake_insights = FakeInsightsGenerator()
        app.dependency_overrides[get_classifier] = lambda: self.fake_classifier
        app.dependency_overrides[get_conflict_detector] = lambda: self.fake_detector
        app.dependency_overrides[get_insights_generator] = lambda: self.fake_insights

    def _upload(self, content, name="doc.docx"):
        resp = self.client.post(
            "/upload",
            files={"file": (name, io.BytesIO(content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert resp.status_code == 303
        return int(resp.headers["location"].rsplit("/", 1)[-1])

    # --- classify ---------------------------------------------------------

    def test_classify_without_scrub_sends_raw_text_no_review_screen(self):
        doc_id = self._upload(WITH_IDENTIFIER)
        resp = self.client.post(f"/documents/{doc_id}/classify")
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(any("jane.smith@example.com" in t for t in self.fake_classifier.received_texts))

    def test_classify_with_scrub_shows_review_screen_before_calling_ai(self):
        doc_id = self._upload(WITH_IDENTIFIER)
        resp = self.client.post(f"/documents/{doc_id}/classify", data={"scrub": "on"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Review before sending to Claude", resp.text)
        self.assertIn("jane.smith@example.com", resp.text)
        self.assertEqual(self.fake_classifier.received_texts, [])

    def test_confirming_review_screen_sends_redacted_text(self):
        doc_id = self._upload(WITH_IDENTIFIER)
        resp = self.client.post(f"/documents/{doc_id}/classify", data={"scrub": "on", "confirmed": "1"})
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(any("[EMAIL]" in t for t in self.fake_classifier.received_texts))
        self.assertFalse(any("jane.smith@example.com" in t for t in self.fake_classifier.received_texts))

    def test_scrub_with_no_findings_skips_the_review_screen(self):
        doc_id = self._upload(CLEAN_ONLY)
        resp = self.client.post(f"/documents/{doc_id}/classify", data={"scrub": "on"})
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(len(self.fake_classifier.received_texts), 1)

    # --- detect-conflicts ---------------------------------------------------

    def test_detect_conflicts_with_scrub_shows_review_screen(self):
        doc_id = self._upload(WITH_IDENTIFIER)
        resp = self.client.post(f"/documents/{doc_id}/detect-conflicts", data={"scrub": "on"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Review before sending to Claude", resp.text)
        self.assertEqual(self.fake_detector.received_texts, [])

    def test_confirming_detect_conflicts_review_sends_redacted_text(self):
        doc_id = self._upload(WITH_IDENTIFIER)
        resp = self.client.post(
            f"/documents/{doc_id}/detect-conflicts", data={"scrub": "on", "confirmed": "1"}
        )
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(any("[EMAIL]" in t for t in self.fake_detector.received_texts))

    # --- analysis insights ---------------------------------------------------

    def test_insights_with_scrub_shows_review_screen(self):
        self._upload(WITH_IDENTIFIER)
        resp = self.client.post("/analysis/insights", data={"scrub": "on"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Review before sending to Claude", resp.text)
        self.assertEqual(self.fake_insights.received_texts, [])

    def test_confirming_insights_review_sends_redacted_text(self):
        self._upload(WITH_IDENTIFIER)
        resp = self.client.post("/analysis/insights", data={"scrub": "on", "confirmed": "1"})
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(any("[EMAIL]" in t for t in self.fake_insights.received_texts))

    def test_insights_without_scrub_is_unaffected(self):
        self._upload(WITH_IDENTIFIER)
        resp = self.client.post("/analysis/insights")
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(any("jane.smith@example.com" in t for t in self.fake_insights.received_texts))

    # --- review screen basics ---------------------------------------------------

    def test_review_screen_cancel_link_returns_to_the_document(self):
        doc_id = self._upload(WITH_IDENTIFIER)
        resp = self.client.post(f"/documents/{doc_id}/classify", data={"scrub": "on"})
        self.assertIn(f'href="/documents/{doc_id}', resp.text)


if __name__ == "__main__":
    unittest.main()
