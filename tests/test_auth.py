"""Tests for accounts, login/logout, and -- the most important part --
that one user's documents are completely unreachable from another user's
session, including through comment_id/document_id combinations that don't
actually belong together."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import auth
from app.database import get_connection
from app.main import app
from tests.auth_helpers import TEST_EMAIL, TEST_PASSWORD, AuthenticatedTestCase

SAMPLE = pathlib.Path(__file__).parent / "sample_docs" / "comment_insight_synthetic_sample.docx"


class AccountTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test.db"
        self.conn = get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_password_is_never_stored_in_plain_text(self):
        auth.create_user(self.conn, "a@example.com", "hunter2")
        row = self.conn.execute("SELECT password_hash FROM users WHERE email = ?", ("a@example.com",)).fetchone()
        self.assertNotEqual(row["password_hash"], "hunter2")
        self.assertNotIn("hunter2", row["password_hash"])

    def test_authenticate_accepts_correct_password(self):
        auth.create_user(self.conn, "a@example.com", "hunter2")
        user = auth.authenticate(self.conn, "a@example.com", "hunter2")
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "a@example.com")

    def test_authenticate_rejects_wrong_password(self):
        auth.create_user(self.conn, "a@example.com", "hunter2")
        self.assertIsNone(auth.authenticate(self.conn, "a@example.com", "wrong-password"))

    def test_authenticate_rejects_unknown_email(self):
        self.assertIsNone(auth.authenticate(self.conn, "nobody@example.com", "anything"))

    def test_email_is_case_insensitive_and_trimmed(self):
        auth.create_user(self.conn, "  A@Example.com  ", "hunter2")
        self.assertIsNotNone(auth.authenticate(self.conn, "a@example.com", "hunter2"))

    def test_duplicate_email_is_rejected(self):
        auth.create_user(self.conn, "a@example.com", "hunter2")
        with self.assertRaises(ValueError):
            auth.create_user(self.conn, "a@example.com", "some-other-password")

    def test_repeated_failed_logins_are_rate_limited(self):
        auth.create_user(self.conn, "ratelimited@example.com", "hunter2")
        for _ in range(5):
            auth.authenticate(self.conn, "ratelimited@example.com", "wrong")

        # 6th attempt is blocked even with the *correct* password now.
        self.assertIsNone(auth.authenticate(self.conn, "ratelimited@example.com", "hunter2"))


class LoginRouteTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from app.database import get_db

        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test.db"

        def override_get_db():
            conn = get_connection(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

        app.dependency_overrides[get_db] = override_get_db
        conn = get_connection(self.db_path)
        auth.create_user(conn, TEST_EMAIL, TEST_PASSWORD)
        conn.close()
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_protected_page_redirects_to_login_when_not_authenticated(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_protected_post_route_also_redirects_to_login(self):
        resp = self.client.post("/documents/1/delete")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_api_route_also_requires_login(self):
        resp = self.client.get("/api/documents")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_wrong_password_shows_friendly_error_not_a_500(self):
        resp = self.client.post("/login", data={"email": TEST_EMAIL, "password": "wrong"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Incorrect email or password", resp.text)

    def test_correct_password_logs_in_and_reaches_the_app(self):
        resp = self.client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD})
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/")

        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(TEST_EMAIL, home.text)

    def test_logout_ends_the_session(self):
        self.client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD})
        self.assertEqual(self.client.get("/").status_code, 200)

        self.client.post("/logout")

        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")


class CrossUserIsolationTests(AuthenticatedTestCase):
    """self.client is logged in as user_id; these confirm nothing it can
    reach belongs to other_user_id, and vice versa."""

    def _upload_as_self(self):
        with open(SAMPLE, "rb") as f:
            resp = self.client.post(
                "/upload",
                files={"file": ("mine.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        assert resp.status_code == 303
        return int(resp.headers["location"].rsplit("/", 1)[-1])

    def test_document_list_only_shows_your_own_documents(self):
        self._upload_as_self()
        other = self.login_as_other_user()
        with open(SAMPLE, "rb") as f:
            other.post(
                "/upload",
                files={"file": ("theirs.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

        mine = self.client.get("/")
        self.assertIn("mine.docx", mine.text)
        self.assertNotIn("theirs.docx", mine.text)

        theirs = other.get("/")
        self.assertIn("theirs.docx", theirs.text)
        self.assertNotIn("mine.docx", theirs.text)

    def test_cannot_view_another_users_document_by_guessing_the_id(self):
        document_id = self._upload_as_self()
        other = self.login_as_other_user()

        resp = other.get(f"/documents/{document_id}")
        self.assertEqual(resp.status_code, 404)

    def test_cannot_export_another_users_document(self):
        document_id = self._upload_as_self()
        other = self.login_as_other_user()

        self.assertEqual(other.get(f"/documents/{document_id}/export").status_code, 404)

    def test_cannot_delete_another_users_document(self):
        document_id = self._upload_as_self()
        other = self.login_as_other_user()

        resp = other.post(f"/documents/{document_id}/delete")
        self.assertEqual(resp.status_code, 404)

        # Still there, from the owner's side.
        self.assertEqual(self.client.get(f"/documents/{document_id}").status_code, 200)

    def test_cannot_reach_another_users_document_via_the_json_api(self):
        document_id = self._upload_as_self()
        other = self.login_as_other_user()

        self.assertEqual(other.get(f"/api/documents/{document_id}").status_code, 404)
        self.assertEqual(other.get(f"/api/documents/{document_id}/comments").status_code, 404)

    def test_analysis_page_only_aggregates_your_own_documents(self):
        self._upload_as_self()
        other = self.login_as_other_user()

        resp = other.get("/analysis")
        self.assertIn("0 documents", resp.text)

    def test_cannot_set_resolution_on_a_comment_via_a_document_id_you_own(self):
        # The attack this guards against: naming your *own* document_id in
        # the URL (which passes the document-ownership check) but a
        # comment_id that actually belongs to someone else's document.
        my_document_id = self._upload_as_self()

        other = self.login_as_other_user()
        with open(SAMPLE, "rb") as f:
            their_upload = other.post(
                "/upload",
                files={"file": ("theirs.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        their_document_id = int(their_upload.headers["location"].rsplit("/", 1)[-1])
        their_comment_id = other.get(f"/api/documents/{their_document_id}/comments").json()[0]["id"]

        # Logged in as *me*, naming *my* document_id but *their* comment_id.
        resp = self.client.post(
            f"/documents/{my_document_id}/comments/{their_comment_id}/resolution",
            data={"status": "accepted"},
        )
        self.assertEqual(resp.status_code, 404)

        # Confirm it truly wasn't touched.
        their_comments = other.get(f"/api/documents/{their_document_id}/comments").json()
        touched = next(c for c in their_comments if c["id"] == their_comment_id)
        self.assertIsNone(touched["resolution_status"])

    def test_cannot_set_category_on_a_comment_via_a_document_id_you_own(self):
        my_document_id = self._upload_as_self()

        other = self.login_as_other_user()
        with open(SAMPLE, "rb") as f:
            their_upload = other.post(
                "/upload",
                files={"file": ("theirs.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        their_document_id = int(their_upload.headers["location"].rsplit("/", 1)[-1])
        their_comment_id = other.get(f"/api/documents/{their_document_id}/comments").json()[0]["id"]

        resp = self.client.post(
            f"/documents/{my_document_id}/comments/{their_comment_id}/category",
            data={"category": "Editorial"},
        )
        self.assertEqual(resp.status_code, 404)

        their_comments = other.get(f"/api/documents/{their_document_id}/comments").json()
        touched = next(c for c in their_comments if c["id"] == their_comment_id)
        self.assertIsNone(touched["category"])


if __name__ == "__main__":
    unittest.main()
