"""Shared setup for tests that hit HTTP routes -- every route in the app
now requires a logged-in user, so every such test needs a temp DB, a
seeded account, and a TestClient that's already logged in as it.

Subclass AuthenticatedTestCase instead of unittest.TestCase to get:
  - self.client: a TestClient logged in as self.user_id
  - self.other_user_id: a second, separate account, seeded but not logged
    into self.client -- for cross-user isolation tests
  - self.login_as_other_user(): a second TestClient logged in as that
    second account
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from app import auth
from app.database import get_connection, get_db
from app.main import app

TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "correct horse battery staple"
OTHER_EMAIL = "other-tester@example.com"
OTHER_PASSWORD = "a different battery staple"


class AuthenticatedTestCase(unittest.TestCase):
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

        conn = get_connection(self.db_path)
        self.user_id = auth.create_user(conn, TEST_EMAIL, TEST_PASSWORD)
        self.other_user_id = auth.create_user(conn, OTHER_EMAIL, OTHER_PASSWORD)
        conn.close()

        self.client = TestClient(app, follow_redirects=False)
        login_resp = self.client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD})
        assert login_resp.status_code == 303, f"test login failed: {login_resp.status_code} {login_resp.text}"

    def tearDown(self):
        app.dependency_overrides.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def login_as_other_user(self) -> TestClient:
        client = TestClient(app, follow_redirects=False)
        resp = client.post("/login", data={"email": OTHER_EMAIL, "password": OTHER_PASSWORD})
        assert resp.status_code == 303, f"other-user login failed: {resp.status_code} {resp.text}"
        return client
