#!/usr/bin/env python3
"""Unit tests for sources/transceiver.py — RigctldClient and TransceiverSource."""

import socket
import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from sources.transceiver import RigctldClient, TransceiverSource


# ---------------------------------------------------------------------------
# RigctldClient tests
# ---------------------------------------------------------------------------

class TestRigctldClientQuery(unittest.TestCase):
    """Test the low-level _query method."""

    def _serve_once(self, response: bytes, port: int):
        """Run a one-shot TCP server that sends a canned response."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        srv.settimeout(2)
        try:
            conn, _ = srv.accept()
            conn.recv(256)  # consume the command
            conn.sendall(response)
            conn.close()
        finally:
            srv.close()

    def _query_with_server(self, response: bytes, command: str = "f", port: int = 14532):
        """Start a fake server, query it, return the result."""
        server = threading.Thread(target=self._serve_once, args=(response, port))
        server.daemon = True
        server.start()
        time.sleep(0.05)  # let the server bind
        client = RigctldClient("127.0.0.1", port)
        result = client._query(command)
        server.join(timeout=2)
        return result

    def test_plain_response(self):
        result = self._query_with_server(b"14278000\n", port=14533)
        self.assertEqual(result, "14278000")

    def test_rprt_success(self):
        result = self._query_with_server(b"RPRT 0\n", port=14534)
        self.assertEqual(result, "RPRT 0")

    def test_rprt_error(self):
        result = self._query_with_server(b"RPRT -1\n", port=14535)
        self.assertIsNone(result)

    def test_connection_refused(self):
        client = RigctldClient("127.0.0.1", 19999)
        result = client._query("f")
        self.assertIsNone(result)


class TestRigctldClientGetFrequency(unittest.TestCase):

    @patch.object(RigctldClient, '_query', return_value="14278000")
    def test_returns_float(self, mock_q):
        client = RigctldClient()
        self.assertEqual(client.get_frequency(), 14278000.0)
        mock_q.assert_called_once_with("f")

    @patch.object(RigctldClient, '_query', return_value=None)
    def test_returns_none_on_error(self, mock_q):
        client = RigctldClient()
        self.assertIsNone(client.get_frequency())

    @patch.object(RigctldClient, '_query', return_value="not_a_number")
    def test_returns_none_on_bad_data(self, mock_q):
        client = RigctldClient()
        self.assertIsNone(client.get_frequency())


class TestRigctldClientGetMode(unittest.TestCase):

    @patch.object(RigctldClient, '_query', return_value="USB\n2400")
    def test_returns_mode_and_passband(self, mock_q):
        client = RigctldClient()
        result = client.get_mode()
        self.assertEqual(result, ("USB", 2400))

    @patch.object(RigctldClient, '_query', return_value="LSB\n4000")
    def test_lsb(self, mock_q):
        client = RigctldClient()
        result = client.get_mode()
        self.assertEqual(result, ("LSB", 4000))

    @patch.object(RigctldClient, '_query', return_value=None)
    def test_returns_none_on_error(self, mock_q):
        client = RigctldClient()
        self.assertIsNone(client.get_mode())

    @patch.object(RigctldClient, '_query', return_value="FM")
    def test_single_line_response(self, mock_q):
        """If rigctld returns only mode without passband."""
        client = RigctldClient()
        self.assertIsNone(client.get_mode())


class TestRigctldClientGetPtt(unittest.TestCase):

    @patch.object(RigctldClient, '_query', return_value="0")
    def test_rx(self, mock_q):
        client = RigctldClient()
        self.assertEqual(client.get_ptt(), 0)

    @patch.object(RigctldClient, '_query', return_value="1")
    def test_tx(self, mock_q):
        client = RigctldClient()
        self.assertEqual(client.get_ptt(), 1)

    @patch.object(RigctldClient, '_query', return_value=None)
    def test_returns_none_on_error(self, mock_q):
        client = RigctldClient()
        self.assertIsNone(client.get_ptt())


class TestRigctldClientSetFrequency(unittest.TestCase):

    @patch.object(RigctldClient, '_query', return_value="RPRT 0")
    def test_success(self, mock_q):
        client = RigctldClient()
        self.assertTrue(client.set_frequency(7278000))
        mock_q.assert_called_once_with("F 7278000")

    @patch.object(RigctldClient, '_query', return_value=None)
    def test_failure(self, mock_q):
        client = RigctldClient()
        self.assertFalse(client.set_frequency(7278000))


class TestRigctldClientSetMode(unittest.TestCase):

    @patch.object(RigctldClient, '_query', return_value="RPRT 0")
    def test_success(self, mock_q):
        client = RigctldClient()
        self.assertTrue(client.set_mode("USB", 2400))
        mock_q.assert_called_once_with("M USB 2400")

    @patch.object(RigctldClient, '_query', return_value=None)
    def test_failure(self, mock_q):
        client = RigctldClient()
        self.assertFalse(client.set_mode("USB"))


# ---------------------------------------------------------------------------
# TransceiverSource tests
# ---------------------------------------------------------------------------

class TestTransceiverSourceConfig(unittest.TestCase):
    """Test config parsing and defaults."""

    def test_defaults(self):
        src = TransceiverSource({})
        self.assertEqual(src._frequency_khz, 0)
        self.assertEqual(src._mode, "")
        self.assertEqual(src._rig_model, 0)
        self.assertEqual(src._baud_rate, 38400)
        self.assertEqual(src._rigctld_port, 4532)
        self.assertEqual(src._samplerate, 48000)
        self.assertEqual(src._mic_substring, "")
        self.assertEqual(src._poll_interval, 5.0)

    def test_custom_config(self):
        src = TransceiverSource({
            "frequency": 14278,
            "mode": "usb",
            "rig_model": 1034,
            "serial_port": "/dev/ttyUSB0",
            "baud_rate": 9600,
            "rigctld_port": 5000,
            "microphone_substring": "C-Media",
            "samplerate": 44100,
            "poll_interval": 10.0,
        })
        self.assertEqual(src._frequency_khz, 14278)
        self.assertEqual(src._mode, "usb")
        self.assertEqual(src._rig_model, 1034)
        self.assertEqual(src._serial_port, "/dev/ttyUSB0")
        self.assertEqual(src._baud_rate, 9600)
        self.assertEqual(src._rigctld_port, 5000)
        self.assertEqual(src._mic_substring, "C-Media")
        self.assertEqual(src._samplerate, 44100)
        self.assertEqual(src._poll_interval, 10.0)

    def test_cat_enabled_with_model(self):
        src = TransceiverSource({"rig_model": 1034})
        self.assertTrue(src._cat_enabled)

    def test_cat_disabled_without_model(self):
        src = TransceiverSource({})
        self.assertFalse(src._cat_enabled)

    def test_cat_disabled_with_zero(self):
        src = TransceiverSource({"rig_model": 0})
        self.assertFalse(src._cat_enabled)


class TestTransceiverSourceFindSerial(unittest.TestCase):

    def test_explicit_port(self):
        src = TransceiverSource({"serial_port": "/dev/ttyUSB5"})
        self.assertEqual(src._find_serial_port(), "/dev/ttyUSB5")

    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=[
        "usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_abc123-if00-port0"
    ])
    def test_auto_detect_cp2102(self, mock_listdir, mock_isdir):
        src = TransceiverSource({})
        port = src._find_serial_port()
        self.assertIn("CP2102", port)

    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=[
        "usb-Digirig_Mobile_DR123-if00-port0"
    ])
    def test_auto_detect_digirig(self, mock_listdir, mock_isdir):
        src = TransceiverSource({})
        port = src._find_serial_port()
        self.assertIn("Digirig", port)

    @patch("os.path.isdir", return_value=False)
    @patch("os.path.exists", side_effect=lambda p: p == "/dev/ttyUSB0")
    def test_fallback_ttyusb0(self, mock_exists, mock_isdir):
        src = TransceiverSource({})
        self.assertEqual(src._find_serial_port(), "/dev/ttyUSB0")

    @patch("os.path.isdir", return_value=False)
    @patch("os.path.exists", return_value=False)
    def test_no_port_raises(self, mock_exists, mock_isdir):
        src = TransceiverSource({})
        with self.assertRaises(ValueError):
            src._find_serial_port()


class TestTransceiverSourceStartStop(unittest.TestCase):
    """Test start/stop lifecycle."""

    @patch("sources.transceiver.TransceiverSource._record_audio")
    def test_start_audio_only(self, mock_record):
        """With rig_model=0, should start audio without rigctld."""
        src = TransceiverSource({"rig_model": 0})
        callback = MagicMock()

        src.start(callback)

        self.assertTrue(src._running)
        self.assertIsNone(src._rigctld_process)
        self.assertIsNone(src._poll_thread)
        self.assertIsNotNone(src._audio_thread)

        src.stop()
        self.assertFalse(src._running)

    @patch("sources.transceiver.TransceiverSource._record_audio")
    @patch("sources.transceiver.TransceiverSource._start_rigctld")
    def test_start_with_cat(self, mock_rigctld, mock_record):
        """With rig_model set, should start rigctld and polling."""
        src = TransceiverSource({"rig_model": 1034})
        callback = MagicMock()

        src.start(callback)

        mock_rigctld.assert_called_once()
        self.assertTrue(src._running)
        self.assertIsNotNone(src._poll_thread)
        self.assertIsNotNone(src._audio_thread)

        src.stop()
        self.assertFalse(src._running)

    def test_stop_idempotent(self):
        """Calling stop() when not running should be safe."""
        src = TransceiverSource({})
        src.stop()  # should not raise
        src.stop()  # should not raise


class TestTransceiverSourceRigctld(unittest.TestCase):
    """Test rigctld subprocess management."""

    def test_stop_rigctld_when_none(self):
        """_stop_rigctld should handle None process gracefully."""
        src = TransceiverSource({})
        src._rigctld_process = None
        src._stop_rigctld()  # should not raise

    @patch("subprocess.Popen")
    def test_stop_rigctld_terminates(self, mock_popen):
        """_stop_rigctld should terminate the subprocess."""
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        src = TransceiverSource({})
        src._rigctld_process = mock_proc

        src._stop_rigctld()

        mock_proc.terminate.assert_called_once()
        self.assertIsNone(src._rigctld_process)

    @patch("subprocess.Popen")
    def test_stop_rigctld_kills_on_timeout(self, mock_popen):
        """_stop_rigctld should kill if terminate times out."""
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("rigctld", 3)
        src = TransceiverSource({})
        src._rigctld_process = mock_proc

        src._stop_rigctld()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        self.assertIsNone(src._rigctld_process)


class TestTransceiverSourceRigctldCommand(unittest.TestCase):
    """Test that _start_rigctld builds the correct command."""

    @patch.object(RigctldClient, 'get_mode', return_value=("USB", 2400))
    @patch.object(RigctldClient, 'get_frequency', return_value=14278000.0)
    @patch("subprocess.Popen")
    def test_rigctld_command_flags(self, mock_popen, mock_freq, mock_mode):
        """Verify rigctld is started with PTT disabled and RTS/DTR off."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        src = TransceiverSource({
            "rig_model": 1034,
            "serial_port": "/dev/ttyUSB0",
            "baud_rate": 38400,
        })

        src._start_rigctld()

        args = mock_popen.call_args[0][0]
        self.assertIn("-P", args)
        self.assertEqual(args[args.index("-P") + 1], "NONE")
        self.assertIn("serial_handshake=None", args)
        self.assertIn("rts_state=OFF", args)
        self.assertIn("dtr_state=OFF", args)
        self.assertIn("-m", args)
        self.assertEqual(args[args.index("-m") + 1], "1034")
        self.assertIn("-s", args)
        self.assertEqual(args[args.index("-s") + 1], "38400")

        src._stop_rigctld()

    @patch.object(RigctldClient, 'set_mode', return_value=True)
    @patch.object(RigctldClient, 'set_frequency', return_value=True)
    @patch.object(RigctldClient, 'get_mode', return_value=("LSB", 4000))
    @patch.object(RigctldClient, 'get_frequency', return_value=7205000.0)
    @patch("subprocess.Popen")
    def test_tunes_on_startup(self, mock_popen, mock_getf, mock_getm, mock_setf, mock_setm):
        """When frequency and mode are configured, rig should be tuned on connect."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        src = TransceiverSource({
            "rig_model": 1034,
            "serial_port": "/dev/ttyUSB0",
            "frequency": 7278,
            "mode": "lsb",
        })

        src._start_rigctld()

        mock_setf.assert_called_once_with(7278000.0)
        mock_setm.assert_called_once_with("LSB")
        self.assertEqual(src.frequency_hz, 7278000.0)
        self.assertEqual(src.mode, "LSB")

        src._stop_rigctld()

    @patch.object(RigctldClient, 'get_mode', return_value=("USB", 2400))
    @patch.object(RigctldClient, 'get_frequency', return_value=14278000.0)
    @patch("subprocess.Popen")
    def test_no_tune_when_zero(self, mock_popen, mock_getf, mock_getm):
        """With frequency=0 and mode='', should not try to set frequency/mode."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        src = TransceiverSource({
            "rig_model": 1034,
            "serial_port": "/dev/ttyUSB0",
            "frequency": 0,
            "mode": "",
        })

        with patch.object(RigctldClient, 'set_frequency') as mock_setf, \
             patch.object(RigctldClient, 'set_mode') as mock_setm:
            src._start_rigctld()
            mock_setf.assert_not_called()
            mock_setm.assert_not_called()

        # Should read the rig's current values
        self.assertEqual(src.frequency_hz, 14278000.0)
        self.assertEqual(src.mode, "USB")

        src._stop_rigctld()


class TestTransceiverSourcePollRig(unittest.TestCase):
    """Test frequency/mode polling."""

    def test_poll_detects_frequency_change(self):
        src = TransceiverSource({"rig_model": 1034})
        src._running = True
        src.frequency_hz = 7278000.0
        src.mode = "LSB"

        mock_client = MagicMock()
        mock_client.get_frequency.return_value = 14278000.0
        mock_client.get_mode.return_value = ("USB", 2400)
        src._rig_client = mock_client

        # Run one poll cycle then stop
        src._poll_interval = 0.1
        poll_thread = threading.Thread(target=src._poll_rig)
        poll_thread.daemon = True
        poll_thread.start()
        time.sleep(0.3)
        src._running = False
        poll_thread.join(timeout=2)

        self.assertEqual(src.frequency_hz, 14278000.0)
        self.assertEqual(src.mode, "USB")

    def test_poll_handles_query_failure(self):
        """Poll should not crash if rigctld queries fail."""
        src = TransceiverSource({"rig_model": 1034})
        src._running = True
        src.frequency_hz = 7278000.0
        src.mode = "LSB"

        mock_client = MagicMock()
        mock_client.get_frequency.return_value = None
        mock_client.get_mode.return_value = None
        src._rig_client = mock_client

        src._poll_interval = 0.1
        poll_thread = threading.Thread(target=src._poll_rig)
        poll_thread.daemon = True
        poll_thread.start()
        time.sleep(0.3)
        src._running = False
        poll_thread.join(timeout=2)

        # Should retain original values
        self.assertEqual(src.frequency_hz, 7278000.0)
        self.assertEqual(src.mode, "LSB")


class TestTransceiverSourceIntegration(unittest.TestCase):
    """Test create_source integration with talk_spotter.py."""

    def test_create_transceiver_source(self):
        """Verify create_source returns a TransceiverSource for 'transceiver'."""
        from talk_spotter import Config
        config = Config("config.yaml")
        config.data["radio"] = "transceiver"
        config.data["transceiver"] = {"rig_model": 0}

        from talk_spotter import create_source
        source = create_source(config)
        self.assertIsInstance(source, TransceiverSource)
        self.assertFalse(source._cat_enabled)

    def test_create_transceiver_with_cat(self):
        """Verify create_source passes rig_model through."""
        from talk_spotter import Config
        config = Config("config.yaml")
        config.data["radio"] = "transceiver"
        config.data["transceiver"] = {"rig_model": 1034}

        from talk_spotter import create_source
        source = create_source(config)
        self.assertIsInstance(source, TransceiverSource)
        self.assertTrue(source._cat_enabled)


# ---------------------------------------------------------------------------
# --list-audio tests
# ---------------------------------------------------------------------------

class TestListAudio(unittest.TestCase):
    """Test the --list-audio flag in talk_spotter.main()."""

    @patch("sys.argv", ["talk_spotter.py", "--list-audio"])
    @patch.dict("sys.modules", {"soundcard": MagicMock()})
    def test_lists_microphones(self):
        """Should print numbered list of microphone names and exit 0."""
        import sys
        mock_sc = sys.modules["soundcard"]
        mic1 = MagicMock()
        mic1.name = "USB Audio Device"
        mic2 = MagicMock()
        mic2.name = "Built-in Microphone"
        mock_sc.all_microphones.return_value = [mic1, mic2]

        from talk_spotter import main
        from io import StringIO
        captured = StringIO()
        with patch("sys.stdout", captured), self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 0)
        output = captured.getvalue()
        self.assertIn("USB Audio Device", output)
        self.assertIn("Built-in Microphone", output)
        self.assertIn("1.", output)
        self.assertIn("2.", output)

    @patch("sys.argv", ["talk_spotter.py", "--list-audio"])
    @patch.dict("sys.modules", {"soundcard": MagicMock()})
    def test_no_devices(self):
        """Should print 'No audio input devices found.' when list is empty."""
        import sys
        mock_sc = sys.modules["soundcard"]
        mock_sc.all_microphones.return_value = []

        from talk_spotter import main
        from io import StringIO
        captured = StringIO()
        with patch("sys.stdout", captured), self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("No audio input devices found", captured.getvalue())

    @patch("sys.argv", ["talk_spotter.py", "--list-audio"])
    def test_soundcard_not_installed(self):
        """Should print helpful error and exit 1 when soundcard is missing."""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "soundcard":
                raise ImportError("No module named 'soundcard'")
            return real_import(name, *args, **kwargs)

        from talk_spotter import main
        from io import StringIO
        captured = StringIO()
        with patch("builtins.__import__", side_effect=fake_import), \
             patch("sys.stdout", captured), \
             self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)
        output = captured.getvalue()
        self.assertIn("pip install soundcard", output)


if __name__ == "__main__":
    unittest.main()
