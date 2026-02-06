#!/usr/bin/env python3
"""
KiwiSDR audio source for Talk Spotter.
"""

import logging
import os
import sys
import threading
import time
from queue import Queue, Empty
from typing import Callable

import numpy as np

# Add kiwiclient to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kiwiclient'))
from kiwi import KiwiSDRStream

from .base import AudioSource


class KiwiOptions:
    """Options object compatible with kiwiclient."""

    def __init__(self, host: str, port: int, freq: float, mode: str):
        self.server_host = host
        self.server_port = port
        self.frequency = freq
        self.modulation = mode

        # Required defaults
        self.user = 'TalkSpotter'
        self.password = ''
        self.tlimit_password = ''
        self.ws_timestamp = int(time.time())
        self.socket_timeout = 10
        self.wideband = False
        self.admin = False
        self.nolocal = False

        # Audio settings
        self.lp_cut = None
        self.hp_cut = None
        self.freq_offset = 0
        self.agc_gain = None
        self.agc_yaml = None
        self.no_api = False
        self.de_emp = False
        self.raw = False
        self.nb = False
        self.nb_gate = 100
        self.nb_thresh = 50

        # Not used but required by kiwiclient
        self.is_kiwi_tdoa = False
        self.is_kiwi_wav = False
        self.dir = None
        self.fn = None
        self.station = None
        self.filename = ''
        self.test_mode = False
        self.sq_thresh = None
        self.scan_yaml = None
        self.resample = 0
        self.freq_pbc = None
        self.S_meter = -1
        self.stats = False
        self.tstamp = False
        self.idx = 0
        self.tlimit = None
        self.sound = True
        self.sdt = 0
        self.netcat = False
        self.multiple_connections = False
        self.nb_test = False
        self.wf_cal = None
        self.camp_allow_1ch = False
        self.ADC_OV = False
        self.camp_chan = -1


class TalkSpotterKiwiClient(KiwiSDRStream):
    """KiwiSDR client that pipes audio to a queue for transcription."""

    def __init__(self, options: KiwiOptions, audio_queue: Queue):
        super().__init__()
        self._options = options
        self._audio_queue = audio_queue
        self._type = 'SND'
        self._freq = options.frequency
        self._start_ts = None
        self._start_time = None

    def _setup_rx_params(self):
        """Set up receiver parameters after connection."""
        self.set_name(self._options.user)
        mod = self._options.modulation
        lp = self._options.lp_cut
        hp = self._options.hp_cut
        self.set_mod(mod, lp, hp, self._freq)
        self.set_agc(on=True)

    def _process_audio_samples(self, seq, samples, rssi, fmt):
        """Called when audio samples are received."""
        if seq < 2:
            return
        if len(samples) > 0:
            self._audio_queue.put((samples, self._sample_rate))

    def _on_sample_rate_change(self):
        """Called when sample rate is established."""
        logging.info(f"KiwiSDR sample rate: {self._sample_rate} Hz")


class KiwiSDRSource(AudioSource):
    """KiwiSDR audio source implementation."""

    def __init__(self, config: dict):
        """
        Initialize KiwiSDR source.

        Config keys:
            host: KiwiSDR hostname
            port: KiwiSDR port (default: 8073)
            frequency: Frequency in kHz
            mode: Demodulation mode (usb, lsb, am, cw, nbfm)
        """
        super().__init__(config)
        self.host = config.get('host', '')
        self.port = config.get('port', 8073)
        self.frequency = config.get('frequency', 14230)
        self.mode = config.get('mode', 'usb')

        self._audio_queue = None
        self._client = None
        self._client_thread = None
        self._stop_event = None

    def start(self, audio_callback: Callable[[np.ndarray], None]):
        """Start streaming from KiwiSDR."""
        if not self.host:
            raise ValueError("KiwiSDR host is required")

        self._audio_callback = audio_callback
        self._audio_queue = Queue()
        self._stop_event = threading.Event()

        freq = self.frequency

        print(f"Connecting to KiwiSDR: {self.host}:{self.port}")
        print(f"Frequency: {freq:.1f} kHz, Mode: {self.mode.upper()}")

        options = KiwiOptions(self.host, self.port, freq, self.mode)
        self._client = TalkSpotterKiwiClient(options, self._audio_queue)

        # Connect
        self._client.connect(self.host, self.port)
        self._client.open()

        # Start client thread
        self._client_thread = threading.Thread(
            target=self._run_client,
            daemon=True
        )
        self._client_thread.start()

        # Start audio processing thread
        self._running = True
        self._process_thread = threading.Thread(
            target=self._process_audio,
            daemon=True
        )
        self._process_thread.start()

        logging.info("KiwiSDR source started")

    def _run_client(self):
        """Run the KiwiSDR client loop."""
        try:
            while not self._stop_event.is_set() and self._client:
                self._client.run()
        except Exception as e:
            if self._running:
                logging.error(f"KiwiSDR client error: {e}")

    def _process_audio(self):
        """Process audio from the queue and send to callback."""
        kiwi_sample_rate = 12000

        while self._running:
            try:
                samples, kiwi_sample_rate = self._audio_queue.get(timeout=0.5)

                # Resample to Vosk's expected rate
                resampled = self.resample_audio(
                    samples, kiwi_sample_rate, self.VOSK_SAMPLE_RATE
                )

                if len(resampled) > 0:
                    self._audio_callback(resampled)

            except Empty:
                continue
            except Exception as e:
                logging.error(f"Audio processing error: {e}")

    def stop(self):
        """Stop streaming."""
        if not self._running:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        client = self._client
        self._client = None
        if client:
            try:
                client.close()
            except Exception:
                pass
        logging.info("KiwiSDR source stopped")
