#!/usr/bin/env python3
"""
RTL-SDR Audio Streaming and Transcription

Streams audio from an RTL-SDR dongle with FM/USB/LSB demodulation
and transcribes using Vosk.
"""

import argparse
import json
import logging
import signal
import sys
import threading
import wave
from queue import Queue, Empty

import numpy as np
from rtlsdr import RtlSdr
from vosk import Model, KaldiRecognizer

# Target audio sample rate for Vosk
VOSK_SAMPLE_RATE = 16000


class Demodulator:
    """Audio demodulator for FM and SSB modes."""

    def __init__(self, mode: str, sample_rate: int, audio_rate: int = VOSK_SAMPLE_RATE):
        self.mode = mode.lower()
        self.sample_rate = sample_rate
        self.audio_rate = audio_rate
        self.decimation = sample_rate // audio_rate

        # FM demod state
        self._prev_phase = 0

        # SSB filter coefficients (simple FIR low-pass)
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
        """FM demodulation using phase differentiation."""
        # Calculate instantaneous phase
        phase = np.angle(iq)

        # Phase difference (with unwrapping)
        phase_diff = np.diff(phase)
        phase_diff = np.concatenate([[phase_diff[0]], phase_diff])

        # Handle phase wrapping
        phase_diff = np.where(phase_diff > np.pi, phase_diff - 2*np.pi, phase_diff)
        phase_diff = np.where(phase_diff < -np.pi, phase_diff + 2*np.pi, phase_diff)

        # Normalize and decimate
        audio = phase_diff / np.pi
        audio = self._decimate(audio)

        return (audio * 16000).astype(np.int16)

    def _demod_ssb(self, iq: np.ndarray, upper: bool = True) -> np.ndarray:
        """SSB demodulation (USB or LSB)."""
        # For USB: use the IQ signal directly (upper sideband is positive frequencies)
        # For LSB: conjugate to flip the spectrum
        if not upper:
            iq = np.conj(iq)

        # Apply low-pass filter to limit bandwidth
        filtered, self._filter_state = self._apply_filter(iq)

        # Take real part (this is the demodulated audio)
        audio = np.real(filtered)

        # Decimate to audio rate
        audio = self._decimate(audio)

        # Normalize and convert to int16
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio)) * 0.8

        return (audio * 32767).astype(np.int16)

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        """AM demodulation using envelope detection."""
        # Envelope is the magnitude of the IQ signal
        envelope = np.abs(iq)

        # Remove DC offset
        envelope = envelope - np.mean(envelope)

        # Decimate
        audio = self._decimate(envelope)

        # Normalize
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio)) * 0.8

        return (audio * 32767).astype(np.int16)

    def _apply_filter(self, samples: np.ndarray) -> tuple:
        """Apply FIR filter with state preservation."""
        # Concatenate with previous state
        extended = np.concatenate([self._filter_state, samples])
        filtered = np.convolve(extended, self._filter_taps, mode='valid')

        # Save state for next call
        new_state = extended[-(len(self._filter_taps) - 1):]

        return filtered, new_state

    def _decimate(self, samples: np.ndarray) -> np.ndarray:
        """Decimate samples to audio rate."""
        if self.decimation <= 1:
            return samples
        return samples[::self.decimation]


class RTLSDRStream:
    """RTL-SDR streaming with demodulation."""

    def __init__(self, frequency: float, mode: str, sample_rate: int = 256000,
                 gain: str = 'auto', ppm: int = 0, direct_sampling: int = 0,
                 agc: bool = False):
        """
        Initialize RTL-SDR stream.

        Args:
            frequency: Center frequency in Hz
            mode: Demodulation mode (fm, usb, lsb, am)
            sample_rate: SDR sample rate
            gain: Gain setting ('auto' or numeric dB)
            ppm: Frequency correction in PPM
            direct_sampling: 0=off, 1=I-branch, 2=Q-branch (for HF)
            agc: Enable hardware AGC
        """
        self.frequency = frequency
        self.mode = mode
        self.sample_rate = sample_rate
        self.gain = gain
        self.ppm = ppm
        self.direct_sampling = direct_sampling
        self.agc = agc

        self.sdr = None
        self.demodulator = None
        self._running = False

    def start(self, audio_callback):
        """Start streaming with callback for audio samples."""
        self.sdr = RtlSdr()

        # Configure SDR
        self.sdr.sample_rate = self.sample_rate
        self.sdr.center_freq = self.frequency

        # Enable direct sampling for HF (bypasses tuner)
        if self.direct_sampling > 0:
            self.sdr.set_direct_sampling(self.direct_sampling)
            logging.info(f"Direct sampling enabled: {'I' if self.direct_sampling == 1 else 'Q'}-branch")

        # Enable hardware AGC (important for direct sampling)
        if self.agc:
            try:
                self.sdr.set_agc_mode(True)
                logging.info("Hardware AGC enabled")
            except Exception as e:
                logging.warning(f"Could not enable AGC: {e}")

        # Only set ppm if non-zero (avoids error on some devices)
        if self.ppm != 0:
            try:
                self.sdr.freq_correction = self.ppm
            except Exception as e:
                logging.warning(f"Could not set PPM correction: {e}")

        if self.gain == 'auto':
            self.sdr.gain = 'auto'
        else:
            self.sdr.gain = float(self.gain)

        # Create demodulator
        self.demodulator = Demodulator(self.mode, self.sample_rate)

        self._running = True

        logging.info(f"RTL-SDR started: {self.frequency/1e3:.1f} kHz, mode={self.mode}, "
                     f"sample_rate={self.sample_rate}")

        # Read samples in a loop
        while self._running:
            try:
                # Read IQ samples
                # Read smaller chunks to avoid USB overflow at high sample rates
                iq_samples = self.sdr.read_samples(65536)

                # Demodulate to audio
                audio = self.demodulator.demodulate(iq_samples)

                # Send to callback
                audio_callback(audio)

            except Exception as e:
                if self._running:
                    logging.error(f"RTL-SDR read error: {e}")
                break

    def stop(self):
        """Stop streaming."""
        self._running = False
        if self.sdr:
            try:
                self.sdr.close()
            except:
                pass
            self.sdr = None


def main():
    parser = argparse.ArgumentParser(
        description="Stream audio from RTL-SDR and transcribe using Vosk"
    )
    parser.add_argument(
        "--freq", "-f",
        type=float,
        required=True,
        help="Frequency in kHz (e.g., 146520)"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["fm", "nbfm", "usb", "lsb", "am"],
        default="fm",
        help="Demodulation mode (default: fm)"
    )
    parser.add_argument(
        "--gain", "-g",
        default="auto",
        help="Gain in dB or 'auto' (default: auto)"
    )
    parser.add_argument(
        "--ppm",
        type=int,
        default=0,
        help="Frequency correction in PPM (default: 0)"
    )
    parser.add_argument(
        "--direct-sampling", "-D",
        type=int,
        choices=[0, 1, 2],
        default=0,
        help="Direct sampling mode: 0=off, 1=I-branch, 2=Q-branch (default: 0, use 2 for HF)"
    )
    parser.add_argument(
        "--agc",
        action="store_true",
        help="Enable hardware AGC (recommended for direct sampling)"
    )
    parser.add_argument(
        "--sample-rate", "-s",
        type=int,
        default=256000,
        help="SDR sample rate in Hz (default: 256000, use 1800000 for HF)"
    )
    parser.add_argument(
        "--model",
        default="vosk-model-small-en-us-0.15",
        help="Path to Vosk model"
    )
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        help="Keywords to detect"
    )
    parser.add_argument(
        "--save-wav",
        help="Save received audio to WAV file for debugging"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s %(levelname)s: %(message)s')

    # Convert frequency to Hz
    freq_hz = args.freq * 1e3

    print(f"Frequency: {args.freq:.1f} kHz, Mode: {args.mode.upper()}")
    print(f"Loading Vosk model from: {args.model}")

    # Load Vosk model
    try:
        model = Model(args.model)
        recognizer = KaldiRecognizer(model, VOSK_SAMPLE_RATE)
    except Exception as e:
        print(f"Error loading Vosk model: {e}")
        sys.exit(1)

    print("Vosk model loaded successfully")

    # Keywords
    keywords = args.keywords or []
    if keywords:
        print(f"Watching for keywords: {', '.join(keywords)}")

    # Create SDR stream
    rtl = RTLSDRStream(freq_hz, args.mode, sample_rate=args.sample_rate,
                        gain=args.gain, ppm=args.ppm,
                        direct_sampling=args.direct_sampling, agc=args.agc)

    # Graceful shutdown
    stop_event = threading.Event()

    def signal_handler(sig, frame):
        print("\nShutting down...")
        stop_event.set()
        rtl.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # WAV file for debugging
    wav_file = None
    if args.save_wav:
        wav_file = wave.open(args.save_wav, 'wb')
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(VOSK_SAMPLE_RATE)
        print(f"Saving audio to: {args.save_wav}")

    # Audio processing
    audio_buffer = b""
    last_partial = ""
    chunks_received = [0]  # Use list for closure

    def audio_callback(audio_samples):
        nonlocal audio_buffer, last_partial

        chunks_received[0] += 1
        if chunks_received[0] == 1:
            print(f"First audio chunk: {len(audio_samples)} samples")
        if chunks_received[0] % 20 == 0:
            print(f"Chunks received: {chunks_received[0]}")

        # Save to WAV if enabled
        if wav_file:
            wav_file.writeframes(audio_samples.tobytes())

        # Add to buffer
        audio_buffer += audio_samples.tobytes()

        # Process when we have enough (~0.5 sec)
        target_size = VOSK_SAMPLE_RATE  # 1 second of 16-bit audio = 32000 bytes
        while len(audio_buffer) >= target_size:
            chunk = audio_buffer[:target_size]
            audio_buffer = audio_buffer[target_size:]

            if recognizer.AcceptWaveform(chunk):
                result = json.loads(recognizer.Result())
                text = result.get("text", "")
                if text:
                    # Check for keywords
                    found = [kw for kw in keywords if kw.lower() in text.lower()]
                    if found:
                        print(f"[MATCH] {text}  <-- {', '.join(found)}")
                    else:
                        print(f"[FINAL] {text}")
            else:
                partial = json.loads(recognizer.PartialResult())
                partial_text = partial.get("partial", "")
                if partial_text and partial_text != last_partial:
                    print(f"[...] {partial_text}", end="\r", flush=True)
                    last_partial = partial_text

    print("\n" + "=" * 50)
    print("Transcription started. Press Ctrl+C to stop.")
    print("=" * 50 + "\n")

    try:
        rtl.start(audio_callback)
    except Exception as e:
        logging.error(f"Error: {e}")
        if args.debug:
            raise
        sys.exit(1)
    finally:
        rtl.stop()
        if wav_file:
            wav_file.close()
            print(f"Audio saved to: {args.save_wav}")
        print("Cleanup complete.")


if __name__ == "__main__":
    main()
