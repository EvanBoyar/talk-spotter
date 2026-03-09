#!/usr/bin/env python3
"""Unit tests for sota_spotter.py — SOTA spot posting client."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import requests

from spotters.sota_spotter import SOTAAuth, SOTASpotter


class TestSOTAAuthTokenStorage(unittest.TestCase):
    """Test token load/save/logout."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.token_file = os.path.join(self.tmpdir, "tokens.json")

    def tearDown(self):
        if os.path.exists(self.token_file):
            os.unlink(self.token_file)
        os.rmdir(self.tmpdir)

    def test_load_empty_when_no_file(self):
        auth = SOTAAuth(token_file=self.token_file)
        self.assertFalse(auth.is_authenticated)
        self.assertIsNone(auth.access_token)

    def test_save_and_load_tokens(self):
        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {
            "access_token": "acc123",
            "refresh_token": "ref456",
            "id_token": "id789",
            "expires_at": time.time() + 300,
        }
        auth._save_tokens()

        auth2 = SOTAAuth(token_file=self.token_file)
        self.assertTrue(auth2.is_authenticated)
        self.assertEqual(auth2.access_token, "acc123")
        self.assertEqual(auth2.id_token, "id789")

    def test_token_file_permissions(self):
        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {"refresh_token": "x"}
        auth._save_tokens()

        mode = os.stat(self.token_file).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_logout_clears_tokens_and_file(self):
        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {"refresh_token": "x"}
        auth._save_tokens()
        self.assertTrue(os.path.exists(self.token_file))

        auth.logout()
        self.assertFalse(auth.is_authenticated)
        self.assertFalse(os.path.exists(self.token_file))

    def test_load_invalid_json(self):
        with open(self.token_file, "w") as f:
            f.write("not json{{{")

        auth = SOTAAuth(token_file=self.token_file)
        self.assertFalse(auth.is_authenticated)


class TestSOTAAuthEnsureValidToken(unittest.TestCase):
    """Test ensure_valid_token() refresh logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.token_file = os.path.join(self.tmpdir, "tokens.json")

    def tearDown(self):
        if os.path.exists(self.token_file):
            os.unlink(self.token_file)
        os.rmdir(self.tmpdir)

    def test_returns_false_when_not_authenticated(self):
        auth = SOTAAuth(token_file=self.token_file)
        self.assertFalse(auth.ensure_valid_token())

    def test_returns_true_when_token_not_expired(self):
        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {
            "refresh_token": "ref",
            "access_token": "acc",
            "expires_at": time.time() + 300,
        }
        self.assertTrue(auth.ensure_valid_token())

    @patch("spotters.sota_spotter.requests.post")
    def test_refreshes_when_token_expired(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_acc",
            "id_token": "new_id",
            "expires_in": 300,
        }
        mock_post.return_value = mock_resp

        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {
            "refresh_token": "ref",
            "access_token": "old_acc",
            "expires_at": time.time() - 10,  # expired
        }
        self.assertTrue(auth.ensure_valid_token())
        self.assertEqual(auth.access_token, "new_acc")

    @patch("spotters.sota_spotter.requests.post")
    def test_refresh_failure_returns_false(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_grant"}
        mock_post.return_value = mock_resp

        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {
            "refresh_token": "ref",
            "access_token": "old",
            "expires_at": time.time() - 10,
        }
        self.assertFalse(auth.ensure_valid_token())

    @patch("spotters.sota_spotter.requests.post")
    def test_refresh_network_error_returns_false(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("no network")

        auth = SOTAAuth(token_file=self.token_file)
        auth._tokens = {
            "refresh_token": "ref",
            "access_token": "old",
            "expires_at": time.time() - 10,
        }
        self.assertFalse(auth.ensure_valid_token())


class TestSOTASpotterPostSpot(unittest.TestCase):
    """Test SOTASpotter.post_spot() success and error cases."""

    def _make_auth(self):
        auth = MagicMock(spec=SOTAAuth)
        auth.ensure_valid_token.return_value = True
        auth.access_token = "test_token"
        auth.id_token = "test_id_token"
        return auth

    @patch("spotters.sota_spotter.requests.post")
    def test_successful_spot(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        auth = self._make_auth()
        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot(
            activator="W1AW",
            frequency_khz=14285.0,
            summit_ref="W4C/CM-001",
            mode="SSB",
            comments="Test spot",
        )

        self.assertTrue(result["success"])

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["associationCode"], "W4C")
        self.assertEqual(payload["summitCode"], "CM-001")
        self.assertEqual(payload["activatorCallsign"], "W1AW")
        self.assertEqual(payload["frequency"], "14.2850")
        self.assertEqual(payload["mode"], "SSB")

    @patch("spotters.sota_spotter.requests.post")
    def test_callsign_uppercased(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        auth = self._make_auth()
        spotter = SOTASpotter("nr8e", auth)
        self.assertEqual(spotter.spotter_callsign, "NR8E")

        spotter.post_spot("w1aw", 14285.0, "w4c/cm-001")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["activatorCallsign"], "W1AW")
        self.assertEqual(payload["associationCode"], "W4C")

    def test_not_authenticated(self):
        auth = MagicMock(spec=SOTAAuth)
        auth.ensure_valid_token.return_value = False

        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "W4C/CM-001")

        self.assertFalse(result["success"])
        self.assertIn("Not authenticated", result["error"])

    def test_invalid_summit_reference(self):
        auth = self._make_auth()
        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "INVALID")

        self.assertFalse(result["success"])
        self.assertIn("Invalid summit reference", result["error"])

    @patch("spotters.sota_spotter.requests.post")
    def test_api_error_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"message": "Bad summit"}
        mock_resp.text = "Bad Request"
        mock_post.return_value = mock_resp

        auth = self._make_auth()
        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "W4C/CM-001")

        self.assertFalse(result["success"])
        self.assertIn("Bad summit", result["error"])

    @patch("spotters.sota_spotter.requests.post")
    def test_auth_retry_on_401(self, mock_post):
        """On 401, should refresh tokens and retry once."""
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_200 = MagicMock()
        resp_200.status_code = 200
        mock_post.side_effect = [resp_401, resp_200]

        auth = self._make_auth()
        auth.refresh_tokens.return_value = True
        auth.access_token = "refreshed_token"
        auth.id_token = "refreshed_id"

        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "W4C/CM-001")

        self.assertTrue(result["success"])
        auth.refresh_tokens.assert_called_once()
        self.assertEqual(mock_post.call_count, 2)

    @patch("spotters.sota_spotter.requests.post")
    def test_auth_retry_fails(self, mock_post):
        resp_401 = MagicMock()
        resp_401.status_code = 401
        mock_post.return_value = resp_401

        auth = self._make_auth()
        auth.refresh_tokens.return_value = False

        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "W4C/CM-001")

        self.assertFalse(result["success"])
        self.assertIn("Authentication failed", result["error"])

    @patch("spotters.sota_spotter.requests.post")
    def test_timeout_exception(self, mock_post):
        mock_post.side_effect = requests.Timeout("timed out")

        auth = self._make_auth()
        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "W4C/CM-001")

        self.assertFalse(result["success"])
        self.assertIn("timed out", result["error"])

    @patch("spotters.sota_spotter.requests.post")
    def test_network_exception(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        auth = self._make_auth()
        spotter = SOTASpotter("NR8E", auth)
        result = spotter.post_spot("W1AW", 14285.0, "W4C/CM-001")

        self.assertFalse(result["success"])
        self.assertIn("Connection refused", result["error"])


if __name__ == "__main__":
    unittest.main()
