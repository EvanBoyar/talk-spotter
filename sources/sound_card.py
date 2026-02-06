#!/usr/bin/env python3
"""
Sound card audio source for Talk Spotter.

Allows using a sound card interface (e.g., Digirig) connected to
an HF rig as an audio source.

Requires the 'soundcard' package: pip install soundcard>=0.4.5
"""

import logging
import threading
from typing import Callable

import numpy as np
import soundcard

from .base import AudioSource


class SoundCardSource(AudioSource):
    """Sound card audio source implementation."""

    def __init__(self, config: dict):
        """
        Initialize sound card source.

        Config keys:
            microphone_substring: Substring to match microphone name (e.g., "CM108 Audio Controller")
            samplerate: Sample rate in Hz (default: 48000)
        """
        super().__init__(config)

        microphone_substring = config.get("microphone_substring", "")
        if microphone_substring:
            logging.info(f"Looking for microphone matching: {microphone_substring}")
            try:
                microphone = soundcard.get_microphone(microphone_substring)
            except IndexError:
                logging.error("Microphone not found. Available microphones:")
                for mic in soundcard.all_microphones():
                    logging.error(f"  - {mic.name}")
                raise ValueError(f"No microphone matching '{microphone_substring}' found")
        else:
            logging.info("Using default microphone")
            microphone = soundcard.default_microphone()

        self._samplerate = config.get("samplerate", 48000)
        logging.info(f"Sound card sample rate: {self._samplerate} Hz")

        self._recorder = microphone.recorder(samplerate=self._samplerate, channels=1)

    def start(self, audio_callback: Callable[[np.ndarray], None]):
        """Start streaming from sound card."""
        self._audio_callback = audio_callback
        self._running = True

        self._process_thread = threading.Thread(
            target=self._process_audio,
            daemon=True,
            name="soundcard-read"
        )
        self._process_thread.start()

        print(f"Sound card source started ({self._samplerate} Hz)")
        logging.info("SoundCard source started")

    def _process_audio(self):
        """Read and process audio from the sound card."""
        with self._recorder as recorder:
            while self._running:
                try:
                    # Record a chunk of float32 samples, flatten from (N,1) to (N,)
                    samples = recorder.record(numframes=1024).flatten()

                    # Convert float32 [-1.0, 1.0] to int16
                    samples_int16 = (samples * 32767).astype(np.int16)

                    # Resample to Vosk's expected rate
                    resampled = self.resample_audio(
                        samples_int16, self._samplerate, self.VOSK_SAMPLE_RATE
                    )

                    if len(resampled) > 0:
                        self._audio_callback(resampled)
                except Exception as e:
                    if self._running:
                        logging.error(f"Sound card read error: {e}")

    def stop(self):
        """Stop streaming."""
        if not self._running:
            return
        self._running = False
        logging.info("SoundCard source stopped")
