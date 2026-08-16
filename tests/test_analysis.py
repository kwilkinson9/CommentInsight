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

    def test_needs_team_discussion_empty_state_when_nothing_flagged(self):
        self._upload(SAMPLE, "a.docx")
        resp = self.client.get("/analysis")
        self.assertIn("Needs team discussion (0)", resp.text)
        self.assertIn("Nothing flagged for discussion", resp.text)

    def test_needs_team_discussion_lists_priority_comments_across_documents_with_source_doc(self):
        self._upload(SAMPLE, "a.docx")
        self._upload(SAMPLE, "b.docx")
        comment_id_a = self._comment_id(1, "3")  # doc a, comment 3
        comment_id_b = self._comment_id(2, "3")  # doc b, comment 3
        self.client.post(f"/documents/1/comments/{comment_id_a}/category", data={"category": "Decision Required"})
        self.client.post(f"/documents/2/comments/{comment_id_b}/category", data={"category": "Decision Required"})

        resp = self.client.get("/analysis")
        self.assertIn("Needs team discussion (2)", resp.text)
        self.assertIn(">a.docx<", resp.text)
        self.assertIn(">b.docx<", resp.text)

    def test_resolution_can_be_set_from_the_analysis_page_and_redirects_back(self):
        self._upload(SAMPLE, "a.docx")
        comment_id = self._comment_id(1, "3")
        self.client.post(f"/documents/1/comments/{comment_id}/category", data={"category": "Decision Required"})

        resp = self.client.post(
            f"/documents/1/comments/{comment_id}/resolution",
            data={"status": "crm", "note": "Discuss at CRM.", "next": "/analysis"},
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/analysis")

        page = self.client.get("/analysis")
        self.assertIn("Discuss at CRM.", page.text)

    def _comment_id(self, document_id: int, external_id: str) -> int:
        comments = self.client.get(f"/api/documents/{document_id}/comments").json()
        return next(c["id"] for c in comments if c["external_id"] == external_id)

    def test_xlsx_all_comments_sheet_includes_resolution_note_column(self):
        self._upload(SAMPLE, "a.docx")
        comment_id = self.client.get("/api/documents/1/comments").json()[0]["id"]
        self.client.post(
            f"/documents/1/comments/{comment_id}/resolution",
            data={"status": "accepted", "note": "Edited directly in the document."},
        )

        resp = self.client.get("/analysis/export.xlsx")
        wb = load_workbook(io.BytesIO(resp.content))
        sheet = wb["All Comments"]
        headers = [cell.value for cell in sheet[1]]
        self.assertIn("Resolution Note", headers)
        note_col = headers.index("Resolution Note") + 1
        notes = [sheet.cell(row=r, column=note_col).value for r in range(2, sheet.max_row + 1)]
        self.assertIn("Edited directly in the document.", notes)


if __name__ == "__main__":
    unittest.main()
