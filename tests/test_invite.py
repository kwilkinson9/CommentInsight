"""Tests for admin-generated invite links: token creation/consumption in
app.auth, and the /accept-invite/{token} routes -- including that an
invite can't be reused, doesn't outlive its expiry, and that accepting one
actually creates a working, logged-in account."""

import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import auth
from app.database import get_connection
from app.main import app
from tests.auth_helpers import TEST_EMAIL, AuthenticatedTestCase


class InviteTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.conn = get_connection(self.tmpdir / "test.db")

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invite_for_existing_email_is_rejected(self):
        auth.create_user(self.conn, "a@example.com", "some-password")
        with self.assertRaises(ValueError):
            auth.create_invite(self.conn, "a@example.com")

    def test_accepting_a_valid_invite_creates_a_working_account(self):
        token = auth.create_invite(self.conn, "new-tester@example.com")
        user_id = auth.accept_invite(self.conn, token, "a-brand-new-password")
        self.assertIsNotNone(user_id)
        self.assertIsNotNone(auth.authenticate(self.conn, "new-tester@example.com", "a-brand-new-password"))

    def test_invite_cannot_be_accepted_twice(self):
        token = auth.create_invite(self.conn, "new-tester@example.com")
        self.assertIsNotNone(auth.accept_invite(self.conn, token, "first-password"))
        self.assertIsNone(auth.accept_invite(self.conn, token, "second-password"))

    def test_made_up_invite_token_is_rejected(self):
        self.assertIsNone(auth.get_valid_invite(self.conn, "not-a-real-token"))
        self.assertIsNone(auth.accept_invite(self.conn, "not-a-real-token", "whatever"))

    def test_expired_invite_is_rejected(self):
        token = auth.create_invite(self.conn, "new-tester@example.com")
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.conn.execute(
            "UPDATE invites SET expires_at = ? WHERE token_hash = ?",
            (expired, auth._hash_token(token)),
        )
        self.conn.commit()

        self.assertIsNone(auth.get_valid_invite(self.conn, token))
        self.assertIsNone(auth.accept_invite(self.conn, token, "whatever"))

    def test_raw_token_is_not_stored_in_the_database(self):
        token = auth.create_invite(self.conn, "new-tester@example.com")
        row = self.conn.execute("SELECT token_hash FROM invites").fetchone()
        self.assertNotEqual(row["token_hash"], token)
        self.assertNotIn(token, row["token_hash"])

    def test_email_is_lowercased_and_trimmed(self):
        token = auth.create_invite(self.conn, "  New-Tester@Example.com  ")
        auth.accept_invite(self.conn, token, "a-brand-new-password")
        self.assertIsNotNone(auth.authenticate(self.conn, "new-tester@example.com", "a-brand-new-password"))


class AcceptInviteRouteTests(AuthenticatedTestCase):
    def _issue_invite(self, email="new-tester@example.com"):
        conn = get_connection(self.db_path)
        try:
            token = auth.create_invite(conn, email)
        finally:
            conn.close()
        return token

    def test_valid_invite_shows_the_signup_form_with_the_invited_email(self):
        token = self._issue_invite()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.get(f"/accept-invite/{token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("new-tester@example.com", resp.text)

    def test_bogus_invite_shows_generic_invalid_message_not_a_500(self):
        anon = TestClient(app, follow_redirects=False)
        resp = anon.get("/accept-invite/not-a-real-token")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("invalid, expired, or already used", resp.text)

    def test_submitting_creates_the_account_and_logs_in(self):
        token = self._issue_invite()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.post(
            f"/accept-invite/{token}",
            data={"password": "a-brand-new-password", "confirm_password": "a-brand-new-password"},
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/")

        home = anon.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("new-tester@example.com", home.text)

    def test_account_did_not_exist_before_accepting(self):
        token = self._issue_invite()
        conn = get_connection(self.db_path)
        try:
            self.assertIsNone(auth.get_user_by_email(conn, "new-tester@example.com"))
        finally:
            conn.close()

    def test_mismatched_confirmation_is_rejected(self):
        token = self._issue_invite()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.post(
            f"/accept-invite/{token}",
            data={"password": "a-brand-new-password", "confirm_password": "does-not-match"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Passwords didn", resp.text)

    def test_too_short_password_is_rejected(self):
        token = self._issue_invite()
        anon = TestClient(app, follow_redirects=False)
        resp = anon.post(f"/accept-invite/{token}", data={"password": "short", "confirm_password": "short"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least 8 characters", resp.text)

    def test_invite_does_not_collide_with_existing_accounts(self):
        with self.assertRaises(ValueError):
            conn = get_connection(self.db_path)
            try:
                auth.create_invite(conn, TEST_EMAIL)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
