#!/usr/bin/env python3
"""
Base class for audio sources.
"""

from abc import ABC, abstractmethod
from typing import Callable
import numpy as np


class AudioSource(ABC):
    """Abstract base class for audio sources."""

    # Target sample rate for Vosk
    VOSK_SAMPLE_RATE = 16000

    def __init__(self, config: dict):
        """
        Initialize the audio source.

        Args:
            config: Configuration dictionary for this source
        """
        self.config = config
        self._running = False
        self._audio_callback = None

    @abstractmethod
    def start(self, audio_callback: Callable[[np.ndarray], None]):
        """
        Start streaming audio.

        Args:
            audio_callback: Function to call with audio samples (16kHz, int16)
        """
        pass

    @abstractmethod
    def stop(self):
        """Stop streaming audio."""
        pass

    @property
    def is_running(self) -> bool:
        """Check if the source is currently running."""
        return self._running

    @staticmethod
    def resample_audio(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """
        Resample audio using linear interpolation.

        Args:
            samples: Input audio samples
            from_rate: Original sample rate
            to_rate: Target sample rate

        Returns:
            Resampled audio as int16 array
        """
        if from_rate == to_rate:
            return samples.astype(np.int16) if samples.dtype != np.int16 else samples

        n = len(samples)
        ratio = to_rate / from_rate
        out_len = int(n * ratio)

        if out_len == 0:
            return np.array([], dtype=np.int16)

        xa = np.arange(out_len) / ratio
        xp = np.arange(n)
        resampled = np.round(np.interp(xa, xp, samples)).astype(np.int16)

        return resampled
