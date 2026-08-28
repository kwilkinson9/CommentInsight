"""Tests for the Resend email wrapper -- that it fails clearly (rather than
crashing) when unconfigured, and sends the right payload when it is, without
ever making a real network call in the test suite."""

import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import email as email_module


class SendInviteEmailTests(unittest.TestCase):
    def test_missing_api_key_raises_a_clear_error_not_a_crash(self):
        with patch.object(email_module, "RESEND_API_KEY", None):
            with self.assertRaises(email_module.EmailNotConfigured):
                email_module.send_invite_email("tester@example.com", "https://example.com/accept-invite/abc")

    def test_configured_send_posts_to_resend_with_expected_fields(self):
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()

        with patch.object(email_module, "RESEND_API_KEY", "fake-key"), \
             patch.object(email_module, "INVITE_FROM_EMAIL", "Comment Insight <invites@example.com>"), \
             patch("app.email.httpx.post", return_value=fake_response) as mock_post:
            email_module.send_invite_email("tester@example.com", "https://example.com/accept-invite/abc")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-key")
        payload = kwargs["json"]
        self.assertEqual(payload["from"], "Comment Insight <invites@example.com>")
        self.assertEqual(payload["to"], ["tester@example.com"])
        self.assertIn("Comment Insight", payload["subject"])
        self.assertIn("https://example.com/accept-invite/abc", payload["html"])
        self.assertIn("Dossentra", payload["html"])
        fake_response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
