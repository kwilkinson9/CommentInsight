"""Tests that opening a database created before a column existed picks up
the new column via _migrate(), without losing existing data -- covers the
resolutions.note column added for per-comment resolution notes."""

import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import get_connection


class MigrationTests(unittest.TestCase):
    def test_note_column_is_added_to_a_pre_existing_resolutions_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "old.db"

            # Simulate a database created before the `note` column existed.
            raw = sqlite3.connect(db_path)
            raw.executescript(
                """
                CREATE TABLE documents (id INTEGER PRIMARY KEY, filename TEXT NOT NULL, uploaded_at TEXT NOT NULL);
                CREATE TABLE comments (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, external_id TEXT NOT NULL,
                    author TEXT, initials TEXT, comment_date TEXT, text TEXT NOT NULL, anchor_text TEXT,
                    paragraph_text TEXT, section TEXT, parent_comment_id INTEGER);
                CREATE TABLE resolutions (id INTEGER PRIMARY KEY, comment_id INTEGER NOT NULL,
                    status TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(comment_id));
                INSERT INTO documents (id, filename, uploaded_at) VALUES (1, 'old.docx', '2026-01-01T00:00:00Z');
                INSERT INTO comments (id, document_id, external_id, text) VALUES (1, 1, '0', 'Existing comment');
                INSERT INTO resolutions (comment_id, status, updated_at) VALUES (1, 'accepted', '2026-01-01T00:00:00Z');
                """
            )
            raw.commit()
            raw.close()

            conn = get_connection(db_path)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(resolutions)").fetchall()}
            self.assertIn("note", columns)

            row = conn.execute("SELECT status, note FROM resolutions WHERE comment_id = 1").fetchone()
            self.assertEqual(row["status"], "accepted")
            self.assertIsNone(row["note"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
