"""Tests for the cross-document analysis page (app/analysis.py + the
/analysis route) -- uses real uploaded fixtures and direct DB seeding for
classification/resolution data, same pattern as the other dashboard tests."""

import io
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.database import get_connection, get_db
from app.main import app

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"
NO_COMMENTS = pathlib.Path(__file__).parent / "sample_docs" / "no_comments.docx"


class AnalysisPageTests(unittest.TestCase):
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

    def _upload(self, path, name):
        with open(path, "rb") as f:
            return self.client.post(
                "/upload",
                files={"file": (name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

    def test_empty_state_with_no_documents(self):
        resp = self.client.get("/analysis")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No documents uploaded yet", resp.text)

    def test_totals_combine_across_documents(self):
        self._upload(SAMPLE, "a.docx")
        self._upload(SAMPLE, "b.docx")
        resp = self.client.get("/analysis")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("2 documents", resp.text)
        self.assertIn("18 comments total", resp.text)  # 9 + 9

    def test_per_document_table_lists_each_document(self):
        self._upload(SAMPLE, "a.docx")
        self._upload(NO_COMMENTS, "b.docx")
        resp = self.client.get("/analysis")
        self.assertIn("a.docx", resp.text)
        self.assertIn("b.docx", resp.text)

    def test_export_links_present_when_there_are_comments(self):
        self._upload(SAMPLE, "a.docx")
        resp = self.client.get("/analysis")
        self.assertIn("/analysis/export.xlsx", resp.text)
        self.assertIn("/analysis/export.docx", resp.text)

    def test_no_export_links_when_nothing_to_export(self):
        resp = self.client.get("/analysis")
        self.assertNotIn("/analysis/export.xlsx", resp.text)

    def test_docx_export_returns_a_valid_report(self):
        self._upload(SAMPLE, "a.docx")
        self._upload(SAMPLE, "b.docx")
        resp = self.client.get("/analysis/export.docx")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        doc = DocxDocument(io.BytesIO(resp.content))
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Multi-Document Analysis Report", text)
        self.assertIn("2 documents", text)
        self.assertEqual(len(doc.inline_shapes), 3)  # icon + 2 charts
        self.assertEqual(len(doc.tables[0].rows), 3)  # header + a.docx + b.docx

    def test_xlsx_export_returns_a_valid_workbook(self):
        self._upload(SAMPLE, "a.docx")
        self._upload(NO_COMMENTS, "b.docx")
        resp = self.client.get("/analysis/export.xlsx")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertIn("Summary", wb.sheetnames)
        self.assertIn("All Comments", wb.sheetnames)


if __name__ == "__main__":
    unittest.main()
