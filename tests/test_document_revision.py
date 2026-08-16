"""Tests for uploading a revised version of an already-worked-on document
(app/storage.py's replace_document_with_revision() + the
/documents/{id}/revise route) -- carrying forward classification/resolution
decisions for comments that match one from before by (reviewer, text)."""

import io
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.database import get_connection, get_db
from app.main import app


def _build_docx(comments: list[tuple[str, str]]) -> bytes:
    """Builds a minimal .docx with one paragraph + comment per (author, text)
    pair -- enough for extract_comments() without generate_synthetic_doc.py's
    reply-thread machinery, which this doesn't need."""
    doc = DocxDocument()
    for i, (author, text) in enumerate(comments):
        paragraph = doc.add_paragraph(f"Paragraph {i} body text.")
        initials = "".join(w[0] for w in author.split())[:3].upper()
        doc.add_comment(paragraph.runs[0], text=text, author=author, initials=initials)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


ORIGINAL = _build_docx([
    ("Alice", "Please clarify this sentence."),
    ("Bob", "Typo here."),
    ("Carol", "Needs SME review."),
])

REVISED = _build_docx([
    ("Alice", "Please clarify this sentence."),   # unchanged -> should carry forward
    ("Bob", "Typo here -- is this fixed now?"),    # text changed -> treated as new
    ("Dave", "New comment from a new reviewer."),  # brand new
    # Carol's comment is gone entirely -> removed
])


class DocumentRevisionTests(unittest.TestCase):
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

    def _upload_original(self):
        return self.client.post(
            "/upload",
            files={"file": ("original.docx", io.BytesIO(ORIGINAL), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    def _upload_revision(self, content=REVISED, filename="revised.docx"):
        return self.client.post(
            "/documents/1/revise",
            files={"file": (filename, io.BytesIO(content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    def _comment_id_by_text(self, text: str) -> int:
        comments = self.client.get("/api/documents/1/comments").json()
        return next(c["id"] for c in comments if c["text"] == text)

    def test_revision_carries_forward_matching_comment_decisions(self):
        self._upload_original()
        alice_id = self._comment_id_by_text("Please clarify this sentence.")
        bob_id = self._comment_id_by_text("Typo here.")
        self.client.post(f"/documents/1/comments/{alice_id}/category", data={"category": "Clarification Needed"})
        self.client.post(f"/documents/1/comments/{bob_id}/resolution", data={"status": "accepted", "note": "Fixed the typo."})

        resp = self._upload_revision()
        self.assertEqual(resp.status_code, 303)
        self.assertIn("revised_carried=1", resp.headers["location"])
        self.assertIn("revised_new=2", resp.headers["location"])
        self.assertIn("revised_removed=2", resp.headers["location"])

        comments = self.client.get("/api/documents/1/comments").json()
        self.assertEqual(len(comments), 3)  # Alice (carried), Bob-new-text, Dave

        alice = next(c for c in comments if c["text"] == "Please clarify this sentence.")
        self.assertEqual(alice["category"], "Clarification Needed")

        bob_new = next(c for c in comments if c["text"] == "Typo here -- is this fixed now?")
        self.assertIsNone(bob_new["category"])
        self.assertIsNone(bob_new["resolution_status"])

        dave = next(c for c in comments if c["author"] == "Dave")
        self.assertIsNone(dave["category"])

        self.assertFalse(any(c["author"] == "Carol" for c in comments))

    def test_revision_updates_filename_and_keeps_same_document_id(self):
        self._upload_original()
        self._upload_revision(filename="csr_v2.docx")

        doc = self.client.get("/api/documents/1").json()
        self.assertEqual(doc["id"], 1)
        self.assertEqual(doc["filename"], "csr_v2.docx")

    def test_revision_success_banner_shown_on_document_page(self):
        self._upload_original()
        alice_id = self._comment_id_by_text("Please clarify this sentence.")
        self.client.post(f"/documents/1/comments/{alice_id}/category", data={"category": "Editorial"})
        self._upload_revision()

        page = self.client.get(f"/documents/1?revised_carried=1&revised_new=2&revised_removed=2")
        self.assertIn("Revised version uploaded", page.text)
        self.assertIn("1 comment kept their category/resolution", page.text)
        self.assertIn("2 new comments added", page.text)
        self.assertIn("2 no longer in the document", page.text)

    def test_revising_with_a_non_docx_file_shows_friendly_error(self):
        self._upload_original()
        resp = self._upload_revision(content=b"not a docx", filename="revised.txt")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Only .docx files are supported", resp.text)

        # Original document/comments untouched.
        comments = self.client.get("/api/documents/1/comments").json()
        self.assertEqual(len(comments), 3)

    def test_revising_a_corrupt_docx_shows_friendly_error_not_a_500(self):
        self._upload_original()
        resp = self._upload_revision(content=b"PK\x03\x04not actually a zip", filename="revised.docx")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Could not read", resp.text)

    def test_revising_missing_file_field_shows_friendly_error(self):
        self._upload_original()
        resp = self.client.post("/documents/1/revise", data={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Please choose a", resp.text)

    def test_revising_unknown_document_is_404(self):
        resp = self.client.post(
            "/documents/999/revise",
            files={"file": ("revised.docx", io.BytesIO(REVISED), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
