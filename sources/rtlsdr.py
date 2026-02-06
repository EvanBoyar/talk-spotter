#!/usr/bin/env python3
"""
RTL-SDR audio source for Talk Spotter.
"""

import logging
import threading
import time
from queue import Queue, Empty
from typing import Callable

import numpy as np
from rtlsdr import RtlSdr

from .base import AudioSource


class Demodulator:
    """Audio demodulator for FM and SSB modes."""

    def __init__(self, mode: str, sample_rate: int, audio_rate: int = 16000):
        self.mode = mode.lower()
        self.sample_rate = sample_rate
        self.audio_rate = audio_rate
        if sample_rate % audio_rate != 0:
            raise ValueError(
                f"Sample rate {sample_rate} must be divisible by audio rate {audio_rate} "
                "for decimation. Choose a sample_rate like 256000 or 960000."
            )
        self.decimation = sample_rate // audio_rate

        # FM demod state
        self._prev_phase = 0

        # NBFM filter - 12.5kHz channel, so ~6kHz audio bandwidth
        self._fm_filter_taps = self._design_lowpass(6000, sample_rate, num_taps=128)
        self._fm_filter_state = np.zeros(len(self._fm_filter_taps) - 1)

        # SSB filter coefficients - 3kHz audio bandwidth
        self._filter_taps = self._design_lowpass(3000, sample_rate)
        self._filter_state = np.zeros(len(self._filter_taps) - 1)

    def _design_lowpass(self, cutoff: float, sample_rate: int, num_taps: int = 64) -> np.ndarray:
        """Design a simple FIR low-pass filter."""
        fc = cutoff / sample_rate
        n = np.arange(num_taps)
        h = np.sinc(2 * fc * (n - (num_taps - 1) / 2))
        h *= np.hamming(num_taps)
        h /= np.sum(h)
        return h

    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        """Demodulate IQ samples to audio."""
        if self.mode == 'fm' or self.mode == 'nbfm':
            return self._demod_fm(iq_samples)
        elif self.mode == 'usb':
            return self._demod_ssb(iq_samples, upper=True)
        elif self.mode == 'lsb':
            return self._demod_ssb(iq_samples, upper=False)
        elif self.mode == 'am':
            return self._demod_am(iq_samples)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def _demod_fm(self, iq: np.ndarray) -> np.ndarray:
        """FM demodulation using phase differentiation with filtering."""
        # Apply low-pass filter with state preservation across chunks
        filtered, self._fm_filter_state = self._apply_fm_filter(iq)

        # FM demodulation via phase differentiation
        phase = np.angle(filtered)

        # Compute phase diff, using previous chunk's last phase for continuity
        phase_diff = np.empty_like(phase)
        phase_diff[0] = phase[0] - self._prev_phase
        phase_diff[1:] = np.diff(phase)
        self._prev_phase = phase[-1]

        # Unwrap phase jumps
        phase_diff = np.where(phase_diff > np.pi, phase_diff - 2*np.pi, phase_diff)
        phase_diff = np.where(phase_diff < -np.pi, phase_diff + 2*np.pi, phase_diff)

        # Normalize - for NBFM, deviation is ~2.5kHz, so scale appropriately
        audio = phase_diff * (self.sample_rate / (2 * np.pi * 2500))

        # Decimate to audio rate
        audio = self._decimate(audio)

        # Remove DC offset (critical for speech recognition)
        audio = audio - np.mean(audio)

        # Normalize to int16 range
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val * 0.8

        return (audio * 32767).astype(np.int16)

    def _demod_ssb(self, iq: np.ndarray, upper: bool = True) -> np.ndarray:
        """SSB demodulation (USB or LSB)."""
        if not upper:
            iq = np.conj(iq)
        filtered, self._filter_state = self._apply_filter(iq)
        audio = np.real(filtered)
        audio = self._decimate(audio)
        # Remove DC offset
        audio = audio - np.mean(audio)
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio)) * 0.8
        return (audio * 32767).astype(np.int16)

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        """AM demodulation using envelope detection."""
        envelope = np.abs(iq)
        audio = self._decimate(envelope)
        # Remove DC offset
        audio = audio - np.mean(audio)
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio)) * 0.8
        return (audio * 32767).astype(np.int16)

    def _apply_filter(self, samples: np.ndarray) -> tuple:
        """Apply SSB FIR filter with state preservation."""
        extended = np.concatenate([self._filter_state, samples])
        filtered = np.convolve(extended, self._filter_taps, mode='valid')
        new_state = extended[-(len(self._filter_taps) - 1):]
        return filtered, new_state

    def _apply_fm_filter(self, samples: np.ndarray) -> tuple:
        """Apply FM FIR filter with state preservation."""
        extended = np.concatenate([self._fm_filter_state, samples])
        filtered = np.convolve(extended, self._fm_filter_taps, mode='valid')
        new_state = extended[-(len(self._fm_filter_taps) - 1):]
        return filtered, new_state

    def _decimate(self, samples: np.ndarray) -> np.ndarray:
        """Decimate samples to audio rate."""
        if self.decimation <= 1:
            return samples
        return samples[::self.decimation]


class RTLSDRSource(AudioSource):
    """RTL-SDR audio source implementation."""

    # Timeout for detecting stalled streams (seconds)
    STALL_TIMEOUT = 5.0

    def __init__(self, config: dict):
        """
        Initialize RTL-SDR source.

        Config keys:
            frequency: Frequency in kHz
            mode: Demodulation mode (fm, nbfm, usb, lsb, am)
            gain: Gain in dB or 'auto' (default: auto)
            ppm: Frequency correction in PPM (default: 0)
            direct_sampling: 0=off, 1=I-branch, 2=Q-branch (default: 0)
            agc: Enable hardware AGC (default: False)
            sample_rate: SDR sample rate (default: 256000)
        """
        super().__init__(config)
        self.frequency = config.get('frequency', 146520) * 1e3  # Convert kHz to Hz
        self.mode = config.get('mode', 'fm')
        self.gain = config.get('gain', 'auto')
        self.ppm = config.get('ppm', 0)
        self.direct_sampling = config.get('direct_sampling', 0)
        self.agc = config.get('agc', False)
        self.sample_rate = config.get('sample_rate', 256000)

        self._sdr = None
        self._demodulator = None
        self._stream_thread = None
        self._process_thread = None
        self._iq_queue = None
        self._last_sample_time = None

    def start(self, audio_callback: Callable[[np.ndarray], None]):
        """Start streaming from RTL-SDR."""
        self._audio_callback = audio_callback
        self._sdr = RtlSdr()
        self._iq_queue = Queue(maxsize=10)  # Limit queue size to prevent memory buildup

        # Configure SDR
        self._sdr.sample_rate = self.sample_rate
        self._sdr.center_freq = self.frequency

        # Enable direct sampling for HF
        if self.direct_sampling > 0:
            self._sdr.set_direct_sampling(self.direct_sampling)
            logging.info(f"Direct sampling enabled: {'I' if self.direct_sampling == 1 else 'Q'}-branch")

        # Enable hardware AGC
        if self.agc:
            try:
                self._sdr.set_agc_mode(True)
                logging.info("Hardware AGC enabled")
            except Exception as e:
                logging.warning(f"Could not enable AGC: {e}")

        # Set PPM correction
        if self.ppm != 0:
            try:
                self._sdr.freq_correction = self.ppm
            except Exception as e:
                logging.warning(f"Could not set PPM correction: {e}")

        # Set gain
        if self.gain == 'auto':
            self._sdr.gain = 'auto'
        else:
            self._sdr.gain = float(self.gain)

        # Create demodulator
        self._demodulator = Demodulator(self.mode, self.sample_rate, self.VOSK_SAMPLE_RATE)

        self._running = True
        self._last_sample_time = time.time()

        print(f"RTL-SDR: {self.frequency/1e3:.1f} kHz, Mode: {self.mode.upper()}")
        logging.info(f"RTL-SDR started: {self.frequency/1e3:.1f} kHz, mode={self.mode}, "
                     f"sample_rate={self.sample_rate}")

        # Start reading thread (reads from SDR, puts in queue)
        self._stream_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="rtlsdr-read"
        )
        self._stream_thread.start()

        # Start processing thread (reads from queue, demodulates, calls callback)
        self._process_thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name="rtlsdr-process"
        )
        self._process_thread.start()

    def _read_loop(self):
        """Read IQ samples from SDR and put in queue."""
        while self._running:
            try:
                # Read IQ samples
                iq_samples = self._sdr.read_samples(65536)
                self._last_sample_time = time.time()

                # Put in queue, drop if full (prevents memory buildup)
                try:
                    self._iq_queue.put_nowait(iq_samples)
                except Exception:
                    # Queue full, drop samples
                    logging.debug("RTL-SDR queue full, dropping samples")

            except Exception as e:
                if self._running:
                    logging.error(f"RTL-SDR read error: {e}")
                    self._running = False
                break

    def _process_loop(self):
        """Process IQ samples from queue."""
        while self._running:
            try:
                # Get samples with timeout
                iq_samples = self._iq_queue.get(timeout=0.5)

                # Demodulate to audio
                audio = self._demodulator.demodulate(iq_samples)

                # Send to callback
                if len(audio) > 0:
                    self._audio_callback(audio)

            except Empty:
                # Check for stall
                if self._last_sample_time:
                    elapsed = time.time() - self._last_sample_time
                    if elapsed > self.STALL_TIMEOUT:
                        logging.warning(f"RTL-SDR stalled - no data for {elapsed:.1f}s")
                        # Don't break, just warn - might recover
                continue
            except Exception as e:
                if self._running:
                    logging.error(f"RTL-SDR processing error: {e}")

    def stop(self):
        """Stop streaming."""
        self._running = False
        if self._sdr:
            try:
                self._sdr.close()
            except:
                pass
            self._sdr = None
        logging.info("RTL-SDR source stopped")
