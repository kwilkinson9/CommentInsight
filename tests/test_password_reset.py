"""Tests for admin-generated password reset links: token creation/consumption
in app.auth, and the /reset-password/{token} routes -- including that a
token can't be reused, doesn't outlive its expiry, and a bogus token gets
the same generic error as an expired/used one."""

import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import auth
from app.database import get_connection, get_db
from app.main import app
from tests.auth_helpers import TEST_EMAIL, TEST_PASSWORD, AuthenticatedTestCase


class ResetTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.conn = get_connection(self.tmpdir / "test.db")
        auth.create_user(self.conn, "a@example.com", "original-password")

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_email_returns_none_without_creating_a_token(self):
        self.assertIsNone(auth.create_reset_token(self.conn, "nobody@example.com"))

    def test_valid_token_resets_the_password(self):
        token = auth.create_reset_token(self.conn, "a@example.com")
        self.assertTrue(auth.reset_password(self.conn, token, "brand-new-password"))
        self.assertIsNotNone(auth.authenticate(self.conn, "a@example.com", "brand-new-password"))
        self.assertIsNone(auth.authenticate(self.conn, "a@example.com", "original-password"))

    def test_token_cannot_be_used_twice(self):
        token = auth.create_reset_token(self.conn, "a@example.com")
        self.assertTrue(auth.reset_password(self.conn, token, "first-new-password"))
        self.assertFalse(auth.reset_password(self.conn, token, "second-new-password"))
        # Still logged in with the first reset's password, not the second.
        self.assertIsNotNone(auth.authenticate(self.conn, "a@example.com", "first-new-password"))

    def test_made_up_token_is_rejected(self):
        self.assertIsNone(auth.get_valid_reset_token(self.conn, "not-a-real-token"))
        self.assertFalse(auth.reset_password(self.conn, "not-a-real-token", "whatever"))

    def test_expired_token_is_rejected(self):
        token = auth.create_reset_token(self.conn, "a@example.com")
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.conn.execute(
            "UPDATE password_reset_tokens SET expires_at = ? WHERE token_hash = ?",
            (expired, auth._hash_token(token)),
        )
        self.conn.commit()

        self.assertIsNone(auth.get_valid_reset_token(self.conn, token))
        self.assertFalse(auth.reset_password(self.conn, token, "whatever"))

    def test_raw_token_is_not_stored_in_the_database(self):
        token = auth.create_reset_token(self.conn, "a@example.com")
        row = self.conn.execute("SELECT token_hash FROM password_reset_tokens").fetchone()
        self.assertNotEqual(row["token_hash"], token)
        self.assertNotIn(token, row["token_hash"])


class ResetPasswordRouteTests(AuthenticatedTestCase):
    def _issue_token(self, email=TEST_EMAIL):
        conn = get_connection(self.db_path)
        try:
            token = auth.create_reset_token(conn, email)
        finally:
            conn.close()
        return token

    def test_valid_token_shows_the_reset_form(self):
        token = self._issue_token()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.get(f"/reset-password/{token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("New password", resp.text)

    def test_bogus_token_shows_generic_invalid_message_not_a_500(self):
        anon = TestClient(app, follow_redirects=False)
        resp = anon.get("/reset-password/not-a-real-token")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("invalid, expired, or already used", resp.text)

    def test_submitting_a_new_password_logs_it_in_going_forward(self):
        token = self._issue_token()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.post(
            f"/reset-password/{token}",
            data={"password": "a-brand-new-password", "confirm_password": "a-brand-new-password"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Password updated", resp.text)

        login = anon.post("/login", data={"email": TEST_EMAIL, "password": "a-brand-new-password"})
        self.assertEqual(login.status_code, 303)
        old_login = anon.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD})
        self.assertEqual(old_login.status_code, 401)

    def test_mismatched_confirmation_is_rejected(self):
        token = self._issue_token()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.post(
            f"/reset-password/{token}",
            data={"password": "a-brand-new-password", "confirm_password": "does-not-match"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Passwords didn", resp.text)
        # Original password still works -- nothing was changed.
        self.assertEqual(
            anon.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD}).status_code, 303
        )

    def test_too_short_password_is_rejected(self):
        token = self._issue_token()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.post(f"/reset-password/{token}", data={"password": "short", "confirm_password": "short"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least 8 characters", resp.text)

    def test_token_only_resets_the_account_it_was_issued_for(self):
        token = self._issue_token(email=TEST_EMAIL)
        anon = TestClient(app, follow_redirects=False)
        anon.post(
            f"/reset-password/{token}",
            data={"password": "a-brand-new-password", "confirm_password": "a-brand-new-password"},
        )

        conn = get_connection(self.db_path)
        try:
            other = auth.get_user_by_id(conn, self.other_user_id)
            self.assertTrue(auth.verify_password("a different battery staple", other["password_hash"]))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
