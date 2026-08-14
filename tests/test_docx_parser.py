import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.ingestion.docx_parser import extract_comments

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"


class ExtractCommentsTests(unittest.TestCase):
    def setUp(self):
        self.comments = extract_comments(SAMPLE)
        self.by_id = {c.id: c for c in self.comments}

    def test_finds_every_comment(self):
        self.assertEqual(len(self.comments), 9)

    def test_anchor_text_is_exact(self):
        self.assertEqual(self.by_id["0"].anchor_text, "67.6%")
        self.assertEqual(self.by_id["6"].anchor_text, "No clinically significant trends were observed")

    def test_paragraph_context_is_captured(self):
        self.assertIn("142 of 210 subjects", self.by_id["0"].paragraph_text)
        self.assertIn("headache (18.1%)", self.by_id["0"].paragraph_text)

    def test_section_breadcrumb(self):
        self.assertEqual(
            self.by_id["6"].section,
            "5.3 Summary of Clinical Safety Findings > 5.3.3 Laboratory Findings",
        )

    def test_reply_thread_is_linked_to_parent(self):
        self.assertIsNone(self.by_id["4"].parent_id)
        self.assertEqual(self.by_id["8"].parent_id, "4")

    def test_author_and_date_preserved(self):
        self.assertEqual(self.by_id["0"].author, "Priya Patel (Biostatistics)")
        self.assertEqual(self.by_id["0"].date, "2026-07-28T14:12:00Z")

    def test_comments_sorted_by_id(self):
        self.assertEqual([c.id for c in self.comments], [str(i) for i in range(9)])


if __name__ == "__main__":
    unittest.main()
