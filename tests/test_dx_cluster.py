#!/usr/bin/env python3
"""Unit tests for dx_cluster.py — DX Cluster telnet client."""

import socket
import unittest
from unittest.mock import MagicMock, patch, call

from spotters.dx_cluster import DXCluster


def _make_mock_sock(recv_sequence):
    """Create a mock socket with a recv side_effect that raises socket.timeout on exhaustion."""
    seq = list(recv_sequence)

    def recv_side_effect(bufsize):
        if seq:
            return seq.pop(0)
        raise socket.timeout("no more data")

    mock_sock = MagicMock()
    mock_sock.recv.side_effect = recv_side_effect
    return mock_sock


class TestDXClusterConnect(unittest.TestCase):
    """Test DXCluster.connect()."""

    @patch("spotters.dx_cluster.socket.socket")
    def test_connect_sends_callsign(self, mock_socket_cls):
        mock_sock = _make_mock_sock([
            b"Welcome to DX Cluster\nlogin: ",  # welcome prompt (ends with :)
            b"Hello NR8E\n>",                    # login response (ends with >)
        ])
        mock_socket_cls.return_value = mock_sock

        cluster = DXCluster("host", 7300, "NR8E")
        result = cluster.connect()

        mock_sock.connect.assert_called_once_with(("host", 7300))
        # Should have sent callsign
        calls = mock_sock.sendall.call_args_list
        self.assertTrue(any(b"NR8E" in c[0][0] for c in calls))
        self.assertIn("Welcome", result)

    @patch("spotters.dx_cluster.socket.socket")
    def test_connect_timeout(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = socket.timeout("timed out")

        cluster = DXCluster("host", 7300, "NR8E", timeout=1.0)
        with self.assertRaises(socket.timeout):
            cluster.connect()


class TestDXClusterSpot(unittest.TestCase):
    """Test DXCluster.spot()."""

    def _connected_cluster(self, mock_socket_cls, extra_recv=None):
        """Helper: create a connected DXCluster with mock socket."""
        recv_data = [
            b"login: ",     # welcome
            b"NR8E>\n>",    # login response
        ]
        if extra_recv:
            recv_data.extend(extra_recv)
        mock_sock = _make_mock_sock(recv_data)
        mock_socket_cls.return_value = mock_sock
        cluster = DXCluster("host", 7300, "NR8E")
        cluster.connect()
        mock_sock.sendall.reset_mock()
        return cluster, mock_sock

    @patch("spotters.dx_cluster.socket.socket")
    def test_spot_format(self, mock_socket_cls):
        cluster, mock_sock = self._connected_cluster(
            mock_socket_cls, [b"Spot posted\n>"]
        )

        cluster.spot(14250.0, "W1AW", "CQ CQ")

        sent = mock_sock.sendall.call_args[0][0]
        self.assertIn(b"DX 14250.0 W1AW CQ CQ", sent)

    @patch("spotters.dx_cluster.socket.socket")
    def test_spot_sanitizes_newlines(self, mock_socket_cls):
        cluster, mock_sock = self._connected_cluster(
            mock_socket_cls, [b">"]
        )

        cluster.spot(14250.0, "W1AW\r\nINJECTED", "evil\r\ncommand")

        sent = mock_sock.sendall.call_args[0][0]
        # \r\n should be stripped so the injected text can't become a separate command
        # The entire spot should be a single line (only trailing \r\n)
        lines = sent.split(b"\r\n")
        self.assertEqual(len(lines), 2)  # command + empty after trailing \r\n
        self.assertIn(b"W1AW", lines[0])
        # No embedded newlines that would allow command injection
        self.assertNotIn(b"\r", lines[0])
        self.assertNotIn(b"\n", lines[0])

    def test_spot_raises_when_not_connected(self):
        cluster = DXCluster("host", 7300, "NR8E")
        with self.assertRaises(RuntimeError):
            cluster.spot(14250.0, "W1AW")


class TestDXClusterDisconnect(unittest.TestCase):
    """Test DXCluster.disconnect()."""

    @patch("spotters.dx_cluster.socket.socket")
    def test_disconnect_sends_bye(self, mock_socket_cls):
        mock_sock = _make_mock_sock([b"login: ", b">"])
        mock_socket_cls.return_value = mock_sock

        cluster = DXCluster("host", 7300, "NR8E")
        cluster.connect()
        mock_sock.sendall.reset_mock()

        cluster.disconnect()

        sent = mock_sock.sendall.call_args[0][0]
        self.assertIn(b"BYE", sent)
        mock_sock.close.assert_called_once()
        self.assertIsNone(cluster.sock)

    def test_disconnect_when_not_connected(self):
        cluster = DXCluster("host", 7300, "NR8E")
        cluster.disconnect()  # should not raise


class TestDXClusterContextManager(unittest.TestCase):
    """Test context manager protocol."""

    @patch("spotters.dx_cluster.socket.socket")
    def test_context_manager(self, mock_socket_cls):
        mock_sock = _make_mock_sock([b"login: ", b">"])
        mock_socket_cls.return_value = mock_sock

        with DXCluster("host", 7300, "NR8E") as cluster:
            self.assertIsNotNone(cluster.sock)

        # After exiting, disconnect should have been called
        mock_sock.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
