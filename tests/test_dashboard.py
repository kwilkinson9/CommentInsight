import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.auth_helpers import AuthenticatedTestCase

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"
NO_COMMENTS = pathlib.Path(__file__).parent / "sample_docs" / "no_comments.docx"


class DashboardTests(AuthenticatedTestCase):
    def _upload_sample(self):
        with open(SAMPLE, "rb") as f:
            return self.client.post(
                "/upload",
                files={"file": ("comment_insight_synthetic_sample.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

    def _upload_no_comments(self):
        with open(NO_COMMENTS, "rb") as f:
            return self.client.post(
                "/upload",
                files={"file": ("no_comments.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

    def test_index_loads_with_no_documents(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No documents uploaded yet", resp.text)

    def test_upload_redirects_to_document_view(self):
        resp = self._upload_sample()
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/documents/1")

    def test_document_view_shows_comments_and_reply_thread(self):
        self._upload_sample()
        resp = self.client.get("/documents/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("67.6%", resp.text)
        self.assertIn("reply to Dr. Sarah Chen (Medical Monitor)", resp.text)
        self.assertIn("9 comments total", resp.text)

    def test_search_filters_comments(self):
        self._upload_sample()
        resp = self.client.get("/documents/1", params={"q": "myocardial"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Showing 3 of 9 comments", resp.text)

    def test_author_filter(self):
        self._upload_sample()
        resp = self.client.get(
            "/documents/1", params={"author": "James Okafor (Regulatory Affairs)"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Showing 3 of 9 comments", resp.text)

    def test_unknown_document_view_returns_404(self):
        resp = self.client.get("/documents/999")
        self.assertEqual(resp.status_code, 404)

    def test_non_docx_upload_shows_error_on_index(self):
        resp = self.client.post(
            "/upload", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Only .docx files are supported", resp.text)

    def test_multiple_file_upload_redirects_to_index(self):
        with open(SAMPLE, "rb") as f1, open(NO_COMMENTS, "rb") as f2:
            resp = self.client.post(
                "/upload",
                files=[
                    ("file", ("comment_insight_synthetic_sample.docx", f1, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                    ("file", ("no_comments.docx", f2, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                ],
            )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/")

        index = self.client.get("/")
        self.assertIn("comment_insight_synthetic_sample.docx", index.text)
        self.assertIn("no_comments.docx", index.text)

    def test_multiple_file_upload_one_bad_file_reports_error_but_still_ingests_the_good_one(self):
        # Each file is processed independently -- a bad file among several
        # doesn't roll back the ones that already succeeded, it just surfaces
        # in the error message alongside them.
        with open(SAMPLE, "rb") as f1:
            resp = self.client.post(
                "/upload",
                files=[
                    ("file", ("comment_insight_synthetic_sample.docx", f1, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                    ("file", ("notes.txt", b"hello", "text/plain")),
                ],
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("notes.txt", resp.text)
        self.assertIn("Only .docx files are supported", resp.text)
        self.assertIn("comment_insight_synthetic_sample.docx", resp.text)

    def test_delete_document_removes_it_from_index(self):
        self._upload_sample()
        resp = self.client.post("/documents/1/delete")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/")

        index = self.client.get("/")
        self.assertIn("No documents uploaded yet", index.text)
        self.assertEqual(self.client.get("/documents/1").status_code, 404)

    def test_delete_unknown_document_is_404(self):
        resp = self.client.post("/documents/999/delete")
        self.assertEqual(resp.status_code, 404)

    def test_delete_button_present_on_index(self):
        self._upload_sample()
        resp = self.client.get("/")
        self.assertIn('action="/documents/1/delete"', resp.text)

    def test_document_with_zero_comments_shows_honest_empty_state(self):
        self._upload_no_comments()
        resp = self.client.get("/documents/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("This document has no comments.", resp.text)
        # the old message would have been misleading here since no filter is applied
        self.assertNotIn("No comments match this filter.", resp.text)
        # nothing to filter/sort, so the filter form shouldn't even be offered
        self.assertNotIn('name="sort"', resp.text)

    def test_dates_are_rendered_human_readable_not_as_raw_iso_strings(self):
        self._upload_sample()
        resp = self.client.get("/documents/1")
        self.assertNotIn("2026-07-28T14:12:00Z", resp.text)
        self.assertRegex(resp.text, r"[A-Z][a-z]{2} \d{1,2}, 2026")

    def test_sort_by_reviewer_groups_comments_alphabetically(self):
        self._upload_sample()
        resp = self.client.get("/documents/1", params={"sort": "reviewer"})
        text = resp.text
        # alphabetical: Dr. Sarah Chen < James Okafor < Lisa Wong < Priya Patel
        self.assertLess(text.find("Dr. Sarah Chen (Medical Monitor)"), text.find("James Okafor (Regulatory Affairs)"))
        self.assertLess(text.find("James Okafor (Regulatory Affairs)"), text.find("Lisa Wong (Medical Writer)"))
        self.assertLess(text.find("Lisa Wong (Medical Writer)"), text.find("Priya Patel (Biostatistics)"))

    def test_sort_by_date_differs_from_document_order(self):
        self._upload_sample()
        # comment #6 (James, dated Aug 1) sits earlier in the document than the
        # reply comment #8 (James, dated Jul 31) -- so date order should flip
        # their relative position compared to document order, proving the
        # sort actually changed something rather than being a no-op.
        document_order = self.client.get("/documents/1", params={"sort": "document"}).text
        self.assertLess(
            document_order.find("flagging for biostatistics sign-off"),
            document_order.find("Recommend leaving as-is"),
        )

        date_order = self.client.get("/documents/1", params={"sort": "date"}).text
        self.assertLess(
            date_order.find("Recommend leaving as-is"),
            date_order.find("flagging for biostatistics sign-off"),
        )


if __name__ == "__main__":
    unittest.main()
