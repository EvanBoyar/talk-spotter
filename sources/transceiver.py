#!/usr/bin/env python3
"""
Transceiver audio source for Talk Spotter.

Uses a sound card interface (e.g., Digirig) for audio and optionally
rigctld (Hamlib) for rig control (frequency/mode). Never transmits.

With rig_model set, it starts rigctld, tunes the rig, and polls for
frequency/mode changes. With rig_model: 0 (or omitted), it just
streams audio from the sound card with no CAT control.
"""

import logging
import os
import socket
import subprocess
import threading
import time
from typing import Callable, Optional

import numpy as np

from .base import AudioSource


class RigctldClient:
    """Simple TCP client for rigctld."""

    def __init__(self, host: str = "localhost", port: int = 4532):
        self.host = host
        self.port = port

    def _query(self, command: str, timeout: float = 2.0) -> Optional[str]:
        """Send a command to rigctld and return the response."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.host, self.port))
            sock.sendall((command + "\n").encode())
            response = sock.recv(1024).decode().strip()
            sock.close()
            if response.startswith("RPRT"):
                # RPRT 0 = success, RPRT -N = error
                code = int(response.split()[1])
                return response if code == 0 else None
            return response
        except (socket.error, OSError) as e:
            logging.debug(f"rigctld query failed: {e}")
            return None

    def get_frequency(self) -> Optional[float]:
        """Get current frequency in Hz."""
        resp = self._query("f")
        if resp:
            try:
                return float(resp)
            except ValueError:
                pass
        return None

    def get_mode(self) -> Optional[tuple[str, int]]:
        """Get current mode and passband. Returns (mode, passband_hz)."""
        resp = self._query("m")
        if resp:
            lines = resp.split("\n")
            if len(lines) >= 2:
                try:
                    return lines[0], int(lines[1])
                except ValueError:
                    return lines[0], 0
        return None

    def get_ptt(self) -> Optional[int]:
        """Get PTT status (0=RX, 1=TX)."""
        resp = self._query("t")
        if resp:
            try:
                return int(resp)
            except ValueError:
                pass
        return None

    def set_frequency(self, freq_hz: float) -> bool:
        """Set frequency in Hz."""
        resp = self._query(f"F {int(freq_hz)}")
        return resp is not None

    def set_mode(self, mode: str, passband: int = 0) -> bool:
        """Set mode (e.g., USB, LSB, AM, FM) and passband width."""
        resp = self._query(f"M {mode} {passband}")
        return resp is not None


class TransceiverSource(AudioSource):
    """Transceiver audio source using sound card + optional rigctld.

    Audio comes from a USB sound card (e.g., Digirig CM108).
    Rig control (frequency/mode) optionally comes from rigctld via TCP.
    Set rig_model to 0 to disable CAT control (audio-only mode).
    """

    def __init__(self, config: dict):
        """
        Initialize transceiver source.

        Config keys:
            frequency: Frequency in kHz (default: 0 = don't change, use rig's current)
            mode: Mode to set (usb, lsb, am, fm, etc. default: "" = don't change)
            rig_model: Hamlib rig model number (0 = no CAT control, audio only)
            serial_port: Serial port for CAT control (default: auto-detect digirig)
            baud_rate: Serial baud rate (default: 38400)
            rigctld_port: TCP port for rigctld (default: 4532)
            microphone_substring: Sound card name substring (default: "" for default mic)
            samplerate: Sound card sample rate (default: 48000)
            poll_interval: Rig polling interval in seconds (default: 5.0)
        """
        super().__init__(config)

        self._frequency_khz = config.get("frequency", 0)
        self._mode = config.get("mode", "")
        self._rig_model = config.get("rig_model", 0)
        self._serial_port = config.get("serial_port", "")
        self._baud_rate = config.get("baud_rate", 38400)
        self._rigctld_port = config.get("rigctld_port", 4532)
        self._poll_interval = config.get("poll_interval", 5.0)

        # Sound card settings
        self._mic_substring = config.get("microphone_substring", "")
        self._samplerate = config.get("samplerate", 48000)

        # State
        self._rigctld_process = None
        self._rig_client = None
        self._poll_thread = None
        self._audio_thread = None

        # Current rig state (updated by polling when CAT is active)
        self.frequency_hz = 0.0
        self.mode = ""
        self.passband = 0

    @property
    def _cat_enabled(self) -> bool:
        return self._rig_model > 0

    def _find_serial_port(self) -> str:
        """Find the serial port, preferring /dev/serial/by-id/ paths."""
        if self._serial_port:
            return self._serial_port

        # Look for digirig-style CP2102N in /dev/serial/by-id/
        by_id = "/dev/serial/by-id"
        if os.path.isdir(by_id):
            for entry in os.listdir(by_id):
                if "CP2102" in entry or "digirig" in entry.lower():
                    path = os.path.join(by_id, entry)
                    logging.info(f"Auto-detected serial port: {path}")
                    return path

        # Fallback to common serial devices
        for dev in ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]:
            if os.path.exists(dev):
                return dev

        raise ValueError("No serial port found. Set transceiver.serial_port in config.")

    def _start_rigctld(self):
        """Start rigctld as a subprocess."""
        serial_port = self._find_serial_port()
        cmd = [
            "rigctld",
            "-m", str(self._rig_model),
            "-r", serial_port,
            "-s", str(self._baud_rate),
            "-t", str(self._rigctld_port),
            "-P", "NONE",
            "-C", "serial_handshake=None",
            "-C", "rts_state=OFF",
            "-C", "dtr_state=OFF",
        ]

        print(f"Starting rigctld: rig model {self._rig_model}, port {serial_port}, "
              f"{self._baud_rate} baud")
        logging.info(f"rigctld command: {' '.join(cmd)}")

        self._rigctld_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for rigctld to be ready
        self._rig_client = RigctldClient("localhost", self._rigctld_port)
        for _ in range(10):
            time.sleep(0.5)
            # Check if process died
            if self._rigctld_process.poll() is not None:
                stderr = self._rigctld_process.stderr.read().decode()
                raise RuntimeError(f"rigctld exited with code {self._rigctld_process.returncode}: {stderr}")
            freq = self._rig_client.get_frequency()
            if freq is not None:
                self.frequency_hz = freq
                mode_info = self._rig_client.get_mode()
                if mode_info:
                    self.mode, self.passband = mode_info
                print(f"Rig connected: {self.frequency_hz / 1e3:.1f} kHz, {self.mode}")

                # Tune rig if frequency/mode specified in config
                if self._frequency_khz > 0:
                    target_hz = self._frequency_khz * 1e3
                    if self._rig_client.set_frequency(target_hz):
                        self.frequency_hz = target_hz
                        print(f"Tuned to: {self._frequency_khz:.1f} kHz")
                    else:
                        logging.warning(f"Failed to set frequency to {self._frequency_khz} kHz")

                if self._mode:
                    mode_upper = self._mode.upper()
                    if self._rig_client.set_mode(mode_upper):
                        self.mode = mode_upper
                        print(f"Mode set: {mode_upper}")
                    else:
                        logging.warning(f"Failed to set mode to {mode_upper}")

                return

        raise RuntimeError("rigctld started but rig not responding (check baud rate and serial port)")

    def _stop_rigctld(self):
        """Stop the rigctld subprocess."""
        if self._rigctld_process:
            self._rigctld_process.terminate()
            try:
                self._rigctld_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._rigctld_process.kill()
            self._rigctld_process = None

    def _poll_rig(self):
        """Periodically poll the rig for frequency/mode changes."""
        while self._running:
            try:
                freq = self._rig_client.get_frequency()
                if freq is not None and freq != self.frequency_hz:
                    old_khz = self.frequency_hz / 1e3
                    self.frequency_hz = freq
                    new_khz = freq / 1e3
                    logging.info(f"Frequency changed: {old_khz:.1f} -> {new_khz:.1f} kHz")

                mode_info = self._rig_client.get_mode()
                if mode_info and mode_info[0] != self.mode:
                    old_mode = self.mode
                    self.mode, self.passband = mode_info
                    logging.info(f"Mode changed: {old_mode} -> {self.mode}")

            except Exception as e:
                logging.debug(f"Rig poll error: {e}")

            # Sleep in small increments so we can stop quickly
            for _ in range(int(self._poll_interval * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def _record_audio(self):
        """Read audio from sound card and send to callback."""
        import soundcard

        mic_substring = self._mic_substring
        if mic_substring:
            logging.info(f"Looking for microphone matching: {mic_substring}")
            try:
                microphone = soundcard.get_microphone(mic_substring)
            except IndexError:
                logging.error("Microphone not found. Available microphones:")
                for mic in soundcard.all_microphones():
                    logging.error(f"  - {mic.name}")
                raise ValueError(f"No microphone matching '{mic_substring}' found")
        else:
            logging.info("Using default microphone")
            microphone = soundcard.default_microphone()

        print(f"Audio input: {microphone.name} ({self._samplerate} Hz)")

        with microphone.recorder(samplerate=self._samplerate, channels=1) as recorder:
            while self._running:
                try:
                    samples = recorder.record(numframes=1024).flatten()

                    # Convert float32 [-1.0, 1.0] to int16
                    samples_int16 = (samples * 32767).astype(np.int16)

                    # Resample to Vosk rate
                    resampled = self.resample_audio(
                        samples_int16, self._samplerate, self.VOSK_SAMPLE_RATE
                    )

                    if len(resampled) > 0:
                        self._audio_callback(resampled)
                except Exception as e:
                    if self._running:
                        logging.error(f"Audio read error: {e}")

    def start(self, audio_callback: Callable[[np.ndarray], None]):
        """Start transceiver source (sound card + optional rigctld)."""
        self._audio_callback = audio_callback
        self._running = True

        # Start rigctld if CAT control is configured
        if self._cat_enabled:
            self._start_rigctld()

            # Start rig polling thread
            self._poll_thread = threading.Thread(
                target=self._poll_rig,
                daemon=True,
                name="rig-poll"
            )
            self._poll_thread.start()
        else:
            print("No rig control configured (rig_model: 0), audio only")

        # Start audio recording thread
        self._audio_thread = threading.Thread(
            target=self._record_audio,
            daemon=True,
            name="transceiver-audio"
        )
        self._audio_thread.start()

        logging.info("Transceiver source started")

    def stop(self):
        """Stop transceiver source."""
        if not self._running:
            return
        self._running = False
        self._stop_rigctld()
        logging.info("Transceiver source stopped")
