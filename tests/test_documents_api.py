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


class DocumentsApiTests(unittest.TestCase):
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
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _upload_sample(self):
        with open(SAMPLE, "rb") as f:
            return self.client.post(
                "/api/documents",
                files={"file": ("comment_insight_synthetic_sample.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

    def test_upload_extracts_and_stores_comments(self):
        resp = self._upload_sample()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["comment_count"], 9)

    def test_stored_comments_are_retrievable_and_match_extraction(self):
        upload_resp = self._upload_sample()
        document_id = upload_resp.json()["id"]

        resp = self.client.get(f"/api/documents/{document_id}/comments")
        self.assertEqual(resp.status_code, 200)
        comments = resp.json()
        self.assertEqual(len(comments), 9)

        by_external = {c["external_id"]: c for c in comments}
        self.assertEqual(by_external["0"]["anchor_text"], "67.6%")
        self.assertEqual(by_external["0"]["author"], "Priya Patel (Biostatistics)")

    def test_reply_thread_survives_round_trip_through_the_database(self):
        upload_resp = self._upload_sample()
        document_id = upload_resp.json()["id"]
        comments = self.client.get(f"/api/documents/{document_id}/comments").json()

        by_external = {c["external_id"]: c for c in comments}
        parent = by_external["4"]
        reply = by_external["8"]
        self.assertIsNone(parent["parent_comment_id"])
        self.assertEqual(reply["parent_comment_id"], parent["id"])

    def test_document_shows_up_in_document_list_with_comment_count(self):
        self._upload_sample()
        resp = self.client.get("/api/documents")
        self.assertEqual(resp.status_code, 200)
        docs = resp.json()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["comment_count"], 9)

    def test_rejects_non_docx_upload(self):
        resp = self.client.post(
            "/api/documents", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_document_returns_404(self):
        resp = self.client.get("/api/documents/999/comments")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
