"""Tests for classification wired into storage and the dashboard.

Uses a fake Classifier (dependency-injected the same way the fake DB
connection is) so this never makes a real, paid API call."""

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.ai.base import Classification, Classifier
from app.database import get_connection, get_db
from app.main import app
from app.routers.dashboard import get_classifier

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"


class FakeClassifier(Classifier):
    """Classifies everything as "Other" and counts how many times it's called,
    so tests can verify already-classified comments aren't re-sent."""

    model_name = "fake-model-v1"

    def __init__(self):
        self.call_count = 0

    def classify(self, comment) -> Classification:
        self.call_count += 1
        return Classification(category="Other", rationale=f"fake rationale for {comment.id}")


class BrokenClassifier(Classifier):
    model_name = "fake-model-v1"

    def classify(self, comment) -> Classification:
        raise RuntimeError("simulated API failure")


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test.db"

        def override_get_db():
            conn = get_connection(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

        self.fake_classifier = FakeClassifier()
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_classifier] = lambda: self.fake_classifier
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _upload_sample(self):
        with open(SAMPLE, "rb") as f:
            return self.client.post(
                "/upload",
                files={"file": ("comment_insight_synthetic_sample.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

    def _db_id_for_external_id(self, external_id: str) -> int:
        comments = self.client.get("/api/documents/1/comments").json()
        return next(c["id"] for c in comments if c["external_id"] == external_id)

    def test_document_starts_unclassified(self):
        self._upload_sample()
        resp = self.client.get("/documents/1")
        self.assertIn("Classify 9 remaining comments", resp.text)
        self.assertIn("Not classified", resp.text)

    def test_classify_button_classifies_every_comment(self):
        self._upload_sample()
        resp = self.client.post("/documents/1/classify")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(self.fake_classifier.call_count, 9)

        page = self.client.get("/documents/1")
        self.assertIn("All 9 comments classified", page.text)
        self.assertIn("category-tag", page.text)
        # The category-override dropdown always includes a "Not classified"
        # *option* (to allow clearing a category by hand) -- what shouldn't
        # appear once everything's classified is the muted placeholder text
        # shown in place of a category tag for an unclassified comment.
        self.assertNotIn('<span class="muted">Not classified</span>', page.text)

    def test_reclassifying_skips_already_classified_comments(self):
        self._upload_sample()
        self.client.post("/documents/1/classify")
        self.assertEqual(self.fake_classifier.call_count, 9)

        self.client.post("/documents/1/classify")
        self.assertEqual(self.fake_classifier.call_count, 9, "should not re-classify comments that already have a result")

    def test_category_filter(self):
        self._upload_sample()
        self.client.post("/documents/1/classify")

        resp = self.client.get("/documents/1", params={"category": "Other"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Showing 9 of 9 comments", resp.text)

        resp = self.client.get("/documents/1", params={"category": "Editorial"})
        self.assertIn("No comments match this filter.", resp.text)

    def test_setting_a_category_manually_on_an_unclassified_comment(self):
        self._upload_sample()
        comment_id = self._db_id_for_external_id("0")

        resp = self.client.post(
            f"/documents/1/comments/{comment_id}/category",
            data={"category": "Editorial", "next": "/documents/1"},
        )
        self.assertEqual(resp.status_code, 303)

        comments = self.client.get("/api/documents/1/comments").json()
        comment = next(c for c in comments if c["id"] == comment_id)
        self.assertEqual(comment["category"], "Editorial")
        self.assertEqual(comment["rationale"], "Set manually by the writer.")

    def test_manual_category_overrides_ai_classification(self):
        self._upload_sample()
        self.client.post("/documents/1/classify")  # everything -> "Other" via FakeClassifier
        comment_id = self._db_id_for_external_id("0")

        self.client.post(f"/documents/1/comments/{comment_id}/category", data={"category": "Decision Required"})

        comments = self.client.get("/api/documents/1/comments").json()
        comment = next(c for c in comments if c["id"] == comment_id)
        self.assertEqual(comment["category"], "Decision Required")

    def test_clearing_a_category_manually(self):
        self._upload_sample()
        comment_id = self._db_id_for_external_id("0")
        self.client.post(f"/documents/1/comments/{comment_id}/category", data={"category": "Editorial"})

        self.client.post(f"/documents/1/comments/{comment_id}/category", data={"category": ""})

        comments = self.client.get("/api/documents/1/comments").json()
        comment = next(c for c in comments if c["id"] == comment_id)
        self.assertIsNone(comment["category"])

    def test_rejects_unknown_category(self):
        self._upload_sample()
        comment_id = self._db_id_for_external_id("0")
        resp = self.client.post(f"/documents/1/comments/{comment_id}/category", data={"category": "Made Up Category"})
        self.assertEqual(resp.status_code, 400)

    def test_classifier_failure_shows_friendly_error_not_a_500(self):
        app.dependency_overrides[get_classifier] = lambda: BrokenClassifier()
        self._upload_sample()

        resp = self.client.post("/documents/1/classify")

        self.assertEqual(resp.status_code, 502)
        self.assertIn("Classification failed", resp.text)


if __name__ == "__main__":
    unittest.main()
