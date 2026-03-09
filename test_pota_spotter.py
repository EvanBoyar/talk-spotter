#!/usr/bin/env python3
"""Unit tests for pota_spotter.py — POTA spot posting client."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from pota_spotter import POTASpotter


class TestPOTASpotterSuccess(unittest.TestCase):
    """Test successful spot posting."""

    @patch("pota_spotter.requests.post")
    def test_successful_spot(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        spotter = POTASpotter("NR8E")
        result = spotter.post_spot(
            activator="W1AW",
            frequency_khz=14250.0,
            park_ref="K-1234",
            mode="SSB",
            comments="CQ POTA"
        )

        self.assertTrue(result["success"])

        # Verify correct URL and payload
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs.kwargs["json"]["activator"], "W1AW")
        self.assertEqual(call_kwargs.kwargs["json"]["spotter"], "NR8E")
        self.assertEqual(call_kwargs.kwargs["json"]["frequency"], "14250.0")
        self.assertEqual(call_kwargs.kwargs["json"]["reference"], "K-1234")
        self.assertEqual(call_kwargs.kwargs["json"]["mode"], "SSB")
        self.assertEqual(call_kwargs.kwargs["json"]["comments"], "CQ POTA")
        self.assertIn("pota.app", call_kwargs.args[0])


class TestPOTASpotterErrors(unittest.TestCase):
    """Test error handling."""

    @patch("pota_spotter.requests.post")
    def test_api_error_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"message": "Invalid park reference"}
        mock_resp.text = "Bad Request"
        mock_post.return_value = mock_resp

        spotter = POTASpotter("NR8E")
        result = spotter.post_spot("W1AW", 14250.0, "INVALID")

        self.assertFalse(result["success"])
        self.assertIn("Invalid park reference", result["error"])

    @patch("pota_spotter.requests.post")
    def test_non_json_error_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        spotter = POTASpotter("NR8E")
        result = spotter.post_spot("W1AW", 14250.0, "K-1234")

        self.assertFalse(result["success"])
        self.assertIn("Internal Server Error", result["error"])

    @patch("pota_spotter.requests.post")
    def test_network_exception(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        spotter = POTASpotter("NR8E")
        result = spotter.post_spot("W1AW", 14250.0, "K-1234")

        self.assertFalse(result["success"])
        self.assertIn("Connection refused", result["error"])

    @patch("pota_spotter.requests.post")
    def test_timeout_exception(self, mock_post):
        mock_post.side_effect = requests.Timeout("timed out")

        spotter = POTASpotter("NR8E")
        result = spotter.post_spot("W1AW", 14250.0, "K-1234")

        self.assertFalse(result["success"])
        self.assertIn("timed out", result["error"])


class TestPOTASpotterCallsign(unittest.TestCase):
    """Test callsign handling."""

    def test_callsign_uppercased(self):
        spotter = POTASpotter("nr8e")
        self.assertEqual(spotter.spotter_callsign, "NR8E")

    @patch("pota_spotter.requests.post")
    def test_activator_uppercased(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        spotter = POTASpotter("NR8E")
        spotter.post_spot("w1aw", 14250.0, "k-1234")

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["activator"], "W1AW")
        self.assertEqual(payload["reference"], "K-1234")


if __name__ == "__main__":
    unittest.main()
