"""Tests for resolution status (writer decisions) and conflict detection
(reviewer disagreements) wired into storage and the dashboard.

Uses fake AI implementations -- no real, paid API calls."""

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.ai.base import Classification, Classifier, ConflictDetector, ConflictPair
from app.database import get_connection, get_db
from app.main import app
from app.routers.dashboard import get_classifier, get_conflict_detector

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"


class FakeClassifier(Classifier):
    model_name = "fake-classifier-v1"

    def classify(self, comment) -> Classification:
        # Comment "3" plays the role of a comment that genuinely needs
        # someone else's sign-off, matching the real prompt's intent.
        category = "Decision Required" if comment.id == "3" else "Other"
        return Classification(category=category, rationale=f"fake rationale for {comment.id}")


class FakeConflictDetector(ConflictDetector):
    model_name = "fake-conflict-model-v1"

    def __init__(self, pairs=None):
        self._pairs = pairs if pairs is not None else [
            ConflictPair(comment_id="4", conflicts_with_id="8", reason="They disagree about the causality assessment.")
        ]
        self.call_count = 0

    def detect_conflicts(self, comments):
        self.call_count += 1
        return self._pairs


class BrokenConflictDetector(ConflictDetector):
    model_name = "fake-conflict-model-v1"

    def detect_conflicts(self, comments):
        raise RuntimeError("simulated API failure")


class ResolutionAndConflictTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test.db"

        def override_get_db():
            conn = get_connection(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

        self.fake_detector = FakeConflictDetector()
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_classifier] = lambda: FakeClassifier()
        app.dependency_overrides[get_conflict_detector] = lambda: self.fake_detector
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

    # --- Resolution status -------------------------------------------------

    def test_comment_starts_with_no_resolution(self):
        self._upload_sample()
        resp = self.client.get("/documents/1")
        self.assertIn("No decision yet", resp.text)

    def test_setting_a_resolution_status(self):
        self._upload_sample()
        comment_id = self._db_id_for_external_id("0")

        resp = self.client.post(
            f"/documents/1/comments/{comment_id}/resolution",
            data={"status": "accepted", "next": "/documents/1"},
        )
        self.assertEqual(resp.status_code, 303)

        page = self.client.get("/documents/1")
        self.assertIn("Accepted", page.text)

    def test_clearing_a_resolution_status(self):
        self._upload_sample()
        comment_id = self._db_id_for_external_id("0")
        self.client.post(f"/documents/1/comments/{comment_id}/resolution", data={"status": "crm"})
        comments = self.client.get("/api/documents/1/comments").json()
        self.assertEqual(next(c for c in comments if c["id"] == comment_id)["resolution_status"], "crm")

        self.client.post(f"/documents/1/comments/{comment_id}/resolution", data={"status": ""})
        comments = self.client.get("/api/documents/1/comments").json()
        self.assertIsNone(next(c for c in comments if c["id"] == comment_id)["resolution_status"])

    def test_rejects_unknown_resolution_status(self):
        self._upload_sample()
        comment_id = self._db_id_for_external_id("0")
        resp = self.client.post(f"/documents/1/comments/{comment_id}/resolution", data={"status": "maybe"})
        self.assertEqual(resp.status_code, 400)

    # --- Conflict detection --------------------------------------------------

    def test_detect_conflicts_flags_both_sides_of_a_pair(self):
        self._upload_sample()
        resp = self.client.post("/documents/1/detect-conflicts")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(self.fake_detector.call_count, 1)

        page = self.client.get("/documents/1")
        self.assertIn("Disagrees with another reviewer", page.text)
        # Comment "4" is Dr. Sarah Chen, comment "8" is James Okafor -- each
        # should show up as the *other* side of the other's conflict box.
        self.assertIn("Dr. Sarah Chen (Medical Monitor)", page.text)
        self.assertIn("James Okafor (Regulatory Affairs)", page.text)

    def test_detect_conflicts_always_reruns_fully(self):
        self._upload_sample()
        self.client.post("/documents/1/detect-conflicts")
        self.client.post("/documents/1/detect-conflicts")
        self.assertEqual(self.fake_detector.call_count, 2, "conflict detection has no skip-already-done logic")

    def test_conflict_failure_shows_friendly_error_not_a_500(self):
        app.dependency_overrides[get_conflict_detector] = lambda: BrokenConflictDetector()
        self._upload_sample()

        resp = self.client.post("/documents/1/detect-conflicts")

        self.assertEqual(resp.status_code, 502)
        self.assertIn("Conflict check failed", resp.text)

    # --- Priority (Decision Required category, or flagged as conflicting) ----

    def test_default_sort_is_document_order_and_unaffected_by_classification(self):
        # Priority used to be the default sort, which meant a comment could
        # physically jump to the top of the list the moment classification
        # flagged it as Decision Required -- disruptive mid-review. Document
        # order is stable regardless of what classification/conflict
        # detection find, so it's the default now; Priority is still an
        # explicit sort choice (see test below).
        #
        # Comment "1" precedes comment "3" in the document; classification
        # makes comment "3" a priority comment (Decision Required). If
        # default sort were still priority, "3" would jump ahead of "1".
        self._upload_sample()
        before = self.client.get("/documents/1").text
        pos_plain_before = before.find("Is this treatment-related headache")  # comment 1
        pos_priority_before = before.find("We need to decide whether to list")  # comment 3
        self.assertLess(pos_plain_before, pos_priority_before, "should already be in document order")

        self.client.post("/documents/1/classify")  # comment "3" -> Decision Required
        self.client.post("/documents/1/detect-conflicts")

        after = self.client.get("/documents/1").text
        pos_plain_after = after.find("Is this treatment-related headache")
        pos_priority_after = after.find("We need to decide whether to list")
        self.assertLess(pos_plain_after, pos_priority_after, "comment 3 must not jump ahead of comment 1")

    def test_priority_sort_still_available_explicitly(self):
        self._upload_sample()
        self.client.post("/documents/1/classify")   # comment "3" -> Decision Required
        self.client.post("/documents/1/detect-conflicts")  # comments "4" and "8" flagged

        page = self.client.get("/documents/1", params={"sort": "priority"})
        text = page.text

        # comment "3"'s text should appear before a comment with neither
        # signal, e.g. comment "1" (classified "Other", no conflict)
        pos_priority = text.find("We need to decide whether to list")  # comment 3
        pos_conflict = text.find("Recommend leaving as-is")  # comment 8 (apostrophes get HTML-escaped, avoid them)
        pos_plain = text.find("Is this treatment-related headache")  # comment 1

        self.assertNotEqual(pos_priority, -1)
        self.assertNotEqual(pos_conflict, -1)
        self.assertNotEqual(pos_plain, -1)
        self.assertLess(pos_priority, pos_plain)
        self.assertLess(pos_conflict, pos_plain)

    def test_classify_preserves_the_currently_selected_sort(self):
        self._upload_sample()
        resp = self.client.post(
            "/documents/1/classify",
            data={"next": "/documents/1?sort=reviewer"},
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/documents/1?sort=reviewer")

    def test_detect_conflicts_preserves_the_currently_selected_sort(self):
        self._upload_sample()
        resp = self.client.post(
            "/documents/1/detect-conflicts",
            data={"next": "/documents/1?sort=date"},
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/documents/1?sort=date")

    def test_priority_badge_shown_on_flagged_comments(self):
        self._upload_sample()
        self.client.post("/documents/1/classify")
        page = self.client.get("/documents/1")
        self.assertIn("Priority", page.text)


if __name__ == "__main__":
    unittest.main()
