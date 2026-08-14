import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.database import get_connection, get_db
from app.main import app

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test.db"

        def override_get_db():
            conn = get_connection(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

        app.dependency_overrides[get_db] = override_get_db
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


if __name__ == "__main__":
    unittest.main()
